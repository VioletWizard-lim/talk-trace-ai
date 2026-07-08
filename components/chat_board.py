import time
import streamlit as st
import plotly.io as pio
from collections import Counter
from db import fetch_live_messages, delete_opinion_message, fetch_room_likes, toggle_like, likes_available
from validators import with_fallback_author_role, mask_ip_for_teacher
from utils import format_kst_datetime, log_audit
from wordcloud import build_word_frequencies, build_circular_wordcloud_html
from config import DASHBOARD_FETCH_LIMIT, LIVE_BOARD_FETCH_LIMIT, LIVE_REFRESH_INTERVAL, UI_FONT_FAMILY


_RANK_BADGES = {1: "🥇", 2: "🥈", 3: "🥉"}
_LIKE_COOLDOWN = 3

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
                 color_discrete_map=_SENTIMENT_COLORS)
    fig.update_layout(font={"family": UI_FONT_FAMILY})
    return fig.to_json()


def _live_chat_board_core(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type):
    opinion_df = with_fallback_author_role(
        fetch_live_messages(supabase, room_name, LIVE_BOARD_FETCH_LIMIT)
    )

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
            likes_data = fetch_room_likes(supabase, room_name)
            likes_count = Counter(item['opinion_id'] for item in likes_data)
            my_likes = {item['opinion_id'] for item in likes_data if item['student_name'] == student_name}
            distinct_counts = sorted({c for c in likes_count.values() if c > 0}, reverse=True)[:3]
            count_to_rank = {c: rank for rank, c in enumerate(distinct_counts, 1)}
            badge_map = {
                oid: _RANK_BADGES[count_to_rank[cnt]]
                for oid, cnt in likes_count.items()
                if cnt > 0 and cnt in count_to_rank
            }
            on_like_cooldown = (time.time() - st.session_state.get('_last_like_ts', 0)) < _LIKE_COOLDOWN

        def do_toggle_like(msg_id):
            toggle_like(supabase, msg_id, room_name, student_name)
            fetch_room_likes.clear()
            st.session_state['_last_like_ts'] = time.time()

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
            sentiment_tag = f"`{row.get('sentiment', '')}` " if show_sentiment_tag else ""

            if user_role == "교사" and teacher_auth:
                c_name, c_like, c_del = st.columns([5, 1, 1])
                with c_name:
                    st.markdown(
                        f"{sentiment_tag}**{name_badge}{row['student_name']}** "
                        f"<span style='color:gray; font-size:14px;'>{formatted_timestamp}</span>",
                        unsafe_allow_html=True,
                    )
                    if row_ip:
                        st.caption(f"IP: {mask_ip_for_teacher(row_ip)}")
                with c_like:
                    st.button(like_label, key=f"like_{msg_id}", disabled=like_disabled,
                              type=like_type, use_container_width=True,
                              on_click=do_toggle_like, args=(msg_id,))
                with c_del:
                    if st.button("❌", key=f"del_{msg_id}", help="강제 삭제"):
                        try:
                            if delete_opinion_message(supabase, msg_id) is not None:
                                fetch_live_messages.clear()
                                _cached_wordcloud.clear()
                                log_audit("chat_deleted", room_name=room_name, actor_name=student_name,
                                          role=user_role, message_id=msg_id)
                                st.toast("의견이 즉시 삭제되었습니다.", icon="🗑️")
                                st.rerun(scope="app")
                        except Exception as e:
                            st.error(f"삭제 실패: {e}")
            else:
                c_name, c_like = st.columns([5, 1])
                with c_name:
                    st.markdown(
                        f"{sentiment_tag}**{name_badge}{row['student_name']}** "
                        f"<span style='color:gray; font-size:14px;'>{formatted_timestamp}</span>",
                        unsafe_allow_html=True,
                    )
                with c_like:
                    st.button(like_label, key=f"like_{msg_id}", disabled=like_disabled,
                              type=like_type, use_container_width=True,
                              on_click=do_toggle_like, args=(msg_id,))
            st.info(_escape_md(row['content']))
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


@st.fragment(run_every=LIVE_REFRESH_INTERVAL)
def _live_chat_board_auto(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type):
    _live_chat_board_core(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type)


def render_chat_board(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type):
    if st.session_state.get('is_working', False):
        _live_chat_board_core(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type)
    else:
        _live_chat_board_auto(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type)
    # 통계 섹션은 별도 60초 fragment — 메시지 보드와 독립적으로 갱신
    _render_stats_section(supabase, room_name, current_mode)
