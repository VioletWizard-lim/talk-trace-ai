import time
import streamlit as st
import plotly.io as pio
from collections import Counter
from db import (
    fetch_live_messages, fetch_latest_message_id, delete_opinion_message, fetch_room_likes, toggle_like, likes_available, debate_soft_delete_available,
    comments_available, comment_likes_available, fetch_comments_for_room, fetch_comment_likes_for_room,
    create_comment, delete_comment, toggle_comment_like,
    fetch_debate_status, session_control_available,
)
from validators import with_fallback_author_role, mask_ip_for_teacher, validate_opinion_content
from utils import anonymize_ip, format_kst_datetime, get_client_ip, log_audit
from wordcloud import build_word_frequencies, build_circular_wordcloud_html
from config import DASHBOARD_FETCH_LIMIT, LIVE_BOARD_FETCH_LIMIT, UI_FONT_FAMILY


_RANK_BADGES = {1: "🥇", 2: "🥈", 3: "🥉"}
_LIKE_COOLDOWN = 3
_COMMENT_TYPES = ["🤔 반박", "➕ 보충"]
_COMMENT_MAX_LEN = 300
_NEW_MSG_POLL_INTERVAL = 5       # 가벼운 변경 확인 주기(초)
_HEAVY_REFRESH_MIN_INTERVAL = 15  # 무거운 재렌더링 최소 간격(초) — 폭주 시 안전장치

_SENTIMENT_COLORS = {
    "🔵 찬성": "#1565C0",
    "🔴 반대": "#C62828",
    "💡 아이디어": "#F9A825",
    "➕ 보충": "#2E7D32",
    "❓ 질문": "#6A1B9A",
}

_PRO_PALETTE  = ["#0D47A1", "#1565C0", "#1976D2", "#1E88E5", "#42A5F5"]
_CON_PALETTE  = ["#B71C1C", "#C62828", "#D32F2F", "#E53935", "#EF5350"]
_FREE_PALETTE = ["#00695C", "#0077B6", "#0B3D91", "#1F8EFA", "#A3CFE2"]


def _escape_md(text: str) -> str:
    s = str(text or "")
    for ch in ('\\', '`', '*', '_', '~'):
        s = s.replace(ch, '\\' + ch)
    return s


@st.cache_data(ttl=60)
def _cached_wordcloud(content_tuple: tuple, palette_key: str = "free"):
    """같은 데이터면 워드클라우드를 재생성하지 않고 캐시 반환."""
    import pandas as pd
    palette_map = {"pro": _PRO_PALETTE, "con": _CON_PALETTE, "free": _FREE_PALETTE}
    palette = palette_map.get(palette_key, _FREE_PALETTE)
    frequencies = build_word_frequencies(pd.Series(list(content_tuple)))
    if not frequencies:
        return None, None
    wc_html = build_circular_wordcloud_html(frequencies, palette=palette)
    top_words = ", ".join([f"{w}({c})" for w, c in frequencies.most_common(8)])
    return wc_html, top_words


@st.cache_data(ttl=20)
def _cached_pie_chart_json(sentiment_tuple: tuple) -> str:
    import plotly.express as px
    import pandas as pd
    df = pd.DataFrame({"sentiment": list(sentiment_tuple)})
    fig = px.pie(df, names="sentiment", hole=0.4, height=400,
                 color="sentiment",
                 color_discrete_map=_SENTIMENT_COLORS,
                 category_orders={
                     "sentiment": ["🔴 반대", "🔵 찬성", "💡 아이디어", "➕ 보충", "❓ 질문"]
                 })
    fig.update_layout(font={"family": UI_FONT_FAMILY})
    return fig.to_json()


@st.fragment
def _live_chat_board_core(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type):
    opinion_df = with_fallback_author_role(
        fetch_live_messages(supabase, room_name, LIVE_BOARD_FETCH_LIMIT)
    )
    debate_ended = session_control_available() and fetch_debate_status(supabase, room_name) == "ended"

    col_board_title, col_board_ref = st.columns([8, 2])
    with col_board_title:
        st.subheader(f"💬 실시간 {act_type} 보드")
    with col_board_ref:
        if user_role == "교사" and teacher_auth:
            st.button("🔄 실시간 보드 새로고침", use_container_width=True, key="refresh_chat_board")

    if not opinion_df.empty:
        teacher_df = opinion_df[opinion_df['student_name'].str.contains('선생님', na=False)]
        if not teacher_df.empty:
            st.success(f"👨‍🏫 **선생님의 생각 힌트!** ➡️ {teacher_df.iloc[0]['content']}")

        student_df = opinion_df[~opinion_df['student_name'].str.contains('선생님', na=False)]

        use_likes = likes_available()
        likes_count = {}
        my_likes = set()
        badge_map = {}
        on_like_cooldown = False
        if use_likes:
            _live_msg_ids = set(opinion_df['id'].tolist())
            likes_data = fetch_room_likes(supabase, room_name)
            likes_count = Counter(
                item['opinion_id'] for item in likes_data if item['opinion_id'] in _live_msg_ids
            )
            my_likes = {item['opinion_id'] for item in likes_data if item['student_name'] == student_name}
            distinct_counts = sorted({c for c in likes_count.values() if c > 0}, reverse=True)[:3]
            count_to_rank = {c: rank for rank, c in enumerate(distinct_counts, 1)}
            badge_map = {
                oid: _RANK_BADGES[count_to_rank[cnt]]
                for oid, cnt in likes_count.items()
                if cnt > 0 and cnt in count_to_rank
            }
            on_like_cooldown = (time.time() - st.session_state.get('_last_like_ts', 0)) < _LIKE_COOLDOWN

        use_comments = comments_available()
        comments_by_debate_id = {}
        use_comment_likes = comment_likes_available()
        comment_likes_count = {}
        my_comment_likes = set()
        if use_comments:
            for c in fetch_comments_for_room(supabase, room_name):
                comments_by_debate_id.setdefault(c["debate_id"], []).append(c)
            if use_comment_likes:
                comment_likes_data = fetch_comment_likes_for_room(supabase, room_name)
                comment_likes_count = Counter(item['comment_id'] for item in comment_likes_data)
                my_comment_likes = {item['comment_id'] for item in comment_likes_data if item['student_name'] == student_name}
        on_comment_like_cooldown = (time.time() - st.session_state.get('_last_comment_like_ts', 0)) < _LIKE_COOLDOWN

        def do_toggle_comment_like(comment_id):
            toggle_comment_like(supabase, comment_id, room_name, student_name)
            fetch_comment_likes_for_room.clear()
            st.session_state['_last_comment_like_ts'] = time.time()

        def do_toggle_like(msg_id):
            toggle_like(supabase, msg_id, room_name, student_name)
            fetch_room_likes.clear()
            st.session_state['_last_like_ts'] = time.time()

        def render_reply_thread(msg_id):
            comments = comments_by_debate_id.get(msg_id, [])
            with st.expander(f"💬 답글 ({len(comments)})", expanded=False):
                for c in comments:
                    c_id = c["id"]
                    c_count = comment_likes_count.get(c_id, 0)
                    c_is_liked = c_id in my_comment_likes
                    c_is_self = bool(student_name and c.get('student_name') == student_name)
                    c_like_disabled = c_is_self or not use_comment_likes or (on_comment_like_cooldown and not c_is_liked)
                    c_like_label = f"👍 {c_count}" if c_count > 0 else "👍"
                    c_like_type = "primary" if c_is_liked else "secondary"

                    with st.container(border=True):
                        col_c_text, col_c_actions = st.columns([6, 2])
                        with col_c_text:
                            _header_html = (
                                f"`{c.get('comment_type', '')}` **{c.get('student_name', '')}** "
                                f"<span style='color:gray; font-size:12px;'>{format_kst_datetime(c.get('timestamp', ''))}</span>"
                            )
                            _id_html = ""
                            if user_role == "교사" and teacher_auth:
                                c_ip = str(c.get("ip_address") or "").strip()
                                c_session = str(c.get("session_id") or "").strip()
                                _id_lines = []
                                if c_ip:
                                    _id_lines.append(f"IP: {mask_ip_for_teacher(c_ip)}")
                                if c_session:
                                    _id_lines.append(f"세션: {c_session[:8]}")
                                if _id_lines:
                                    _id_html = "<br>".join(
                                        f"<span style='color:gray; font-size:12px;'>{line}</span>" for line in _id_lines
                                    )
                            st.markdown(
                                "<br>".join(filter(None, [_header_html, _id_html, _escape_md(c.get('content', ''))])),
                                unsafe_allow_html=True,
                            )
                        with col_c_actions:
                            if user_role == "교사" and teacher_auth:
                                c_like, c_del = st.columns([1, 1], gap="small")
                                with c_like:
                                    st.button(c_like_label, key=f"clike_{c_id}", disabled=c_like_disabled,
                                              type=c_like_type,
                                              on_click=do_toggle_comment_like, args=(c_id,))
                                with c_del:
                                    if st.button("❌", key=f"cdel_{c_id}", help="댓글 삭제"):
                                        if delete_comment(supabase, c_id, deleted_by=student_name) is not None:
                                            fetch_comments_for_room.clear()
                                            st.toast("댓글이 보관소로 이동되었습니다.", icon="🗑️")
                                            st.rerun(scope="app")
                            else:
                                st.button(c_like_label, key=f"clike_{c_id}", disabled=c_like_disabled,
                                          type=c_like_type, use_container_width=True,
                                          on_click=do_toggle_comment_like, args=(c_id,))

                if debate_ended:
                    st.caption(f"🔒 {act_type}이(가) 종료되어 답글을 작성할 수 없습니다.")
                else:
                    comment_type = st.radio(
                        "답글 유형", _COMMENT_TYPES, horizontal=True,
                        key=f"comment_type_{msg_id}", label_visibility="collapsed",
                    )
                    _comment_reset_n = st.session_state.get(f"comment_reset_{msg_id}", 0)
                    comment_input = st.text_input(
                        "답글 내용", key=f"comment_input_{msg_id}_{_comment_reset_n}",
                        placeholder="반박이나 보충할 내용을 적어주세요.",
                        label_visibility="collapsed",
                    )
                    if st.button("답글 등록", key=f"comment_submit_{msg_id}", use_container_width=True):
                        ok, safe_content, _, error_message = validate_opinion_content(comment_input, max_len=_COMMENT_MAX_LEN)
                        if not ok:
                            st.warning(error_message)
                        elif debate_ended:
                            st.warning(f"🔒 {act_type}이(가) 종료되어 답글을 작성할 수 없습니다.")
                        else:
                            _client_ip = get_client_ip()
                            _anon_ip = anonymize_ip(_client_ip) if _client_ip else None
                            _session_id = st.session_state.get("session_uuid")
                            if create_comment(
                                supabase, room_name, msg_id, student_name, comment_type, safe_content,
                                ip_address=_anon_ip, session_id=_session_id,
                            ) is not None:
                                fetch_comments_for_room.clear()
                                st.session_state[f"comment_reset_{msg_id}"] = _comment_reset_n + 1
                                st.toast("✅ 답글이 등록되었습니다.", icon="💬")
                                st.rerun(scope="app")

        def render_msg(row, show_sentiment_tag=False):
            formatted_timestamp = format_kst_datetime(row.get("timestamp", ""))
            msg_id = row['id']
            count = likes_count.get(msg_id, 0)
            is_liked = msg_id in my_likes
            badge = badge_map.get(msg_id, "")
            is_self = bool(student_name and row.get('student_name') == student_name)
            like_disabled = is_self or not use_likes or (on_like_cooldown and not is_liked)
            like_label = f"👍 {count}" if count > 0 else "👍"
            like_type = "primary" if is_liked else "secondary"
            name_badge = f"{badge} " if badge else ""
            row_ip = str(row.get("ip_address") or "").strip() if hasattr(row, "get") else ""
            row_session = str(row.get("session_id") or "").strip() if hasattr(row, "get") else ""
            sentiment_tag = f"`{row.get('sentiment', '')}` " if show_sentiment_tag else ""

            if user_role == "교사" and teacher_auth:
                with st.container(border=True):
                    c_name, c_actions = st.columns([7, 2])
                    with c_name:
                        st.markdown(
                            f"{sentiment_tag}**{name_badge}{row['student_name']}** "
                            f"<span style='color:gray; font-size:14px;'>{formatted_timestamp}</span>",
                            unsafe_allow_html=True,
                        )
                        if row_ip or row_session:
                            _id_bits = []
                            if row_ip:
                                _id_bits.append(f"IP: {mask_ip_for_teacher(row_ip)}")
                            if row_session:
                                _id_bits.append(f"세션: {row_session[:8]}")
                            st.caption(" · ".join(_id_bits))
                    with c_actions:
                        c_like, c_del = st.columns([1, 1], gap="small")
                        with c_like:
                            st.button(like_label, key=f"like_{msg_id}", disabled=like_disabled,
                                      type=like_type,
                                      on_click=do_toggle_like, args=(msg_id,))
                        with c_del:
                            if st.button("❌", key=f"del_{msg_id}", help="강제 삭제"):
                                st.session_state[f"confirm_del_msg_{msg_id}"] = True
                    st.info(_escape_md(row['content']))
                    if use_comments:
                        render_reply_thread(msg_id)

                if st.session_state.get(f"confirm_del_msg_{msg_id}"):
                    _del_notice = (
                        "삭제된 발언은 교사 대시보드의 삭제 보관소에서 복구할 수 있습니다."
                        if debate_soft_delete_available()
                        else "삭제하면 완전히 사라지며 복구할 수 없습니다."
                    )
                    st.warning(f"⚠️ 정말 삭제하시겠습니까? ({_del_notice})\n\n> {_escape_md(row['content'])}")
                    col_yes, col_no = st.columns(2)
                    with col_yes:
                        if st.button("✅ 삭제 확인", key=f"del_yes_{msg_id}", type="primary", use_container_width=True):
                            try:
                                if delete_opinion_message(supabase, msg_id, deleted_by=student_name) is not None:
                                    fetch_live_messages.clear()
                                    fetch_room_likes.clear()
                                    _cached_wordcloud.clear()
                                    log_audit("chat_deleted", room_name=room_name, actor_name=student_name,
                                              role=user_role, message_id=msg_id)
                                    st.session_state.pop(f"confirm_del_msg_{msg_id}", None)
                                    if debate_soft_delete_available():
                                        st.toast("의견이 보관소로 이동되었습니다.", icon="🗑️")
                                    else:
                                        st.toast("의견이 삭제되었습니다.", icon="🗑️")
                                    st.rerun(scope="app")
                            except Exception as e:
                                st.error(f"삭제 실패: {e}")
                    with col_no:
                        if st.button("취소", key=f"del_no_{msg_id}", use_container_width=True):
                            st.session_state.pop(f"confirm_del_msg_{msg_id}", None)
                            st.rerun()
            else:
                with st.container(border=True):
                    c_name, c_actions = st.columns([7, 2])
                    with c_name:
                        st.markdown(
                            f"{sentiment_tag}**{name_badge}{row['student_name']}** "
                            f"<span style='color:gray; font-size:14px;'>{formatted_timestamp}</span>",
                            unsafe_allow_html=True,
                        )
                    with c_actions:
                        st.button(like_label, key=f"like_{msg_id}", disabled=like_disabled,
                                  type=like_type, use_container_width=True,
                                  on_click=do_toggle_like, args=(msg_id,))
                    st.info(_escape_md(row['content']))
                    if use_comments:
                        render_reply_thread(msg_id)
            st.write("")

        if current_mode == "⚔️ 찬반 토론":
            col_pro, col_con = st.columns(2)
            with col_pro:
                st.markdown("### 🔵 찬성 측")
                with st.container(height=450):
                    for _, row in student_df[student_df['sentiment'] == '🔵 찬성'].iterrows():
                        render_msg(row)
            with col_con:
                st.markdown("### 🔴 반대 측")
                with st.container(height=450):
                    for _, row in student_df[student_df['sentiment'] == '🔴 반대'].iterrows():
                        render_msg(row)
        else:
            st.markdown("### 💬 아이디어 · 보충 · 질문")
            with st.container(height=450):
                _discuss_df = student_df[
                    student_df['sentiment'].isin(['💡 아이디어', '➕ 보충', '❓ 질문'])
                ]
                for _, row in _discuss_df.iterrows():
                    render_msg(row, show_sentiment_tag=True)
    else:
        st.info(f"아직 대화가 없습니다. 첫 {act_type} 의견을 남겨주세요!")


@st.fragment(run_every=60)
def _render_stats_section(supabase, room_name, current_mode):
    """통계(파이차트 + 워드클라우드)를 60초 주기로 갱신 — CPU 집약적 렌더링 분리."""
    df = with_fallback_author_role(fetch_live_messages(supabase, room_name, LIVE_BOARD_FETCH_LIMIT))
    if df.empty:
        with st.expander("📊 실시간 의견 통계", expanded=False):
            st.write("데이터 수집 중...")
        return

    student_df = df[~df['student_name'].str.contains('선생님', na=False)]

    with st.expander("📊 실시간 의견 통계", expanded=True):
        _pie_json = _cached_pie_chart_json(
            tuple(df["sentiment"].fillna("").tolist())
        )

        if current_mode == "⚔️ 찬반 토론":
            # 찬성 워드클라우드 | 파이차트 | 반대 워드클라우드
            pro_contents = tuple(
                student_df[student_df['sentiment'] == '🔵 찬성']['content'].fillna("").tolist()
            )
            con_contents = tuple(
                student_df[student_df['sentiment'] == '🔴 반대']['content'].fillna("").tolist()
            )
            wc_col_pro, pie_col, wc_col_con = st.columns(3)
            with wc_col_pro:
                st.caption("🔵 찬성 측 키워드")
                if pro_contents:
                    wc_html, top_words = _cached_wordcloud(pro_contents, palette_key="pro")
                    if wc_html:
                        st.markdown(wc_html, unsafe_allow_html=True)
                        st.caption(f"상위: {top_words}")
                    else:
                        st.info("단어가 아직 부족합니다.")
                else:
                    st.info("찬성 의견 없음")
            with pie_col:
                st.caption("의견 유형 분포")
                st.plotly_chart(pio.from_json(_pie_json), use_container_width=True,
                                config={'displayModeBar': False, 'scrollZoom': False})
            with wc_col_con:
                st.caption("🔴 반대 측 키워드")
                if con_contents:
                    wc_html, top_words = _cached_wordcloud(con_contents, palette_key="con")
                    if wc_html:
                        st.markdown(wc_html, unsafe_allow_html=True)
                        st.caption(f"상위: {top_words}")
                    else:
                        st.info("단어가 아직 부족합니다.")
                else:
                    st.info("반대 의견 없음")
        else:
            pie_col, wc_col = st.columns([1, 2])
            with pie_col:
                st.caption("의견 유형 분포")
                st.plotly_chart(pio.from_json(_pie_json), use_container_width=True,
                                config={'displayModeBar': False, 'scrollZoom': False})
            with wc_col:
                st.caption("누적 워드클라우드")
                all_contents = tuple(student_df["content"].fillna("").tolist())
                if all_contents:
                    wc_html, top_words = _cached_wordcloud(all_contents, palette_key="free")
                    if wc_html:
                        st.markdown(wc_html, unsafe_allow_html=True)
                        st.caption(f"상위 키워드: {top_words}")
                    else:
                        st.info("워드클라우드를 만들 단어가 아직 부족합니다.")


@st.fragment(run_every=_NEW_MSG_POLL_INTERVAL)
def _poll_new_messages(supabase, room_name):
    """새 발언 유무만 가볍게 확인하고, 있을 때만 무거운 보드 재렌더링을 트리거한다.

    기존에는 접속자 전원이 고정 주기마다 무조건 전체 게시판을
    다시 그렸는데(과부하의 원인), 이제는 id 하나만 조회하는 저비용 쿼리로
    변경 여부만 자주 확인하고, 실제로 새 발언이 있을 때만 무거운 재렌더링
    (전체 앱 rerun)을 일으킨다. 다만 여러 학생이 짧은 시간에 몰려서 올리는
    경우에도 무거운 재렌더링이 너무 잦아지지 않도록 최소 간격
    (_HEAVY_REFRESH_MIN_INTERVAL)을 두어, 폭주 상황에서도 기존 방식보다
    나빠지지 않도록 안전장치를 둔다.
    """
    latest_id = fetch_latest_message_id(supabase, room_name)
    last_seen_key = f"_last_seen_msg_id_{room_name}"
    last_render_key = f"_last_heavy_render_ts_{room_name}"

    if latest_id == st.session_state.get(last_seen_key):
        return

    last_render_ts = st.session_state.get(last_render_key, 0)
    if time.time() - last_render_ts < _HEAVY_REFRESH_MIN_INTERVAL:
        return  # 새 발언은 있지만 안전장치 간격 전 — 다음 틱에 다시 확인

    st.session_state[last_seen_key] = latest_id
    st.session_state[last_render_key] = time.time()
    fetch_live_messages.clear()
    fetch_room_likes.clear()
    if comments_available():
        fetch_comments_for_room.clear()
        fetch_comment_likes_for_room.clear()
    st.rerun(scope="app")


def render_chat_board(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type):
    _live_chat_board_core(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type)
    if not st.session_state.get('is_working', False):
        _poll_new_messages(supabase, room_name)
    # 통계 섹션은 별도 60초 fragment — 메시지 보드와 독립적으로 갱신
    _render_stats_section(supabase, room_name, current_mode)
