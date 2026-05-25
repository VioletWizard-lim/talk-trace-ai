import time
import streamlit as st
import plotly.express as px
from collections import Counter
from db import fetch_live_messages, delete_opinion_message, fetch_room_likes, toggle_like, likes_available
from validators import with_fallback_author_role, mask_ip_for_teacher
from utils import format_kst_datetime, get_client_ip, log_audit
from wordcloud import build_word_frequencies, build_circular_wordcloud_html
from config import DASHBOARD_FETCH_LIMIT, LIVE_BOARD_FETCH_LIMIT, LIVE_REFRESH_INTERVAL, UI_FONT_FAMILY


_RANK_BADGES = {1: "🥇", 2: "🥈", 3: "🥉"}
_LIKE_COOLDOWN = 3


def _anon_ip(raw_ip: str) -> str:
    parts = raw_ip.split(".")
    return f"{parts[0]}.X.X.{parts[3]}" if len(parts) == 4 else ""


def _live_chat_board_core(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type):
    opinion_df = with_fallback_author_role(
        fetch_live_messages(supabase, room_name, LIVE_BOARD_FETCH_LIMIT)
    )
    stats_opinion_df = opinion_df

    st.subheader("📊 실시간 의견 통계")
    if not stats_opinion_df.empty:
        left_col, right_col = st.columns(2)
        with left_col:
            st.caption("의견 유형 분포 그래프")
            live_pie_fig = px.pie(stats_opinion_df, names="sentiment", hole=0.4, height=320)
            live_pie_fig.update_layout(font={"family": UI_FONT_FAMILY})
            st.plotly_chart(live_pie_fig, use_container_width=True, config={'displayModeBar': False, 'scrollZoom': False})
        with right_col:
            st.caption("누적 토의/토론 워드클라우드")
            frequencies = build_word_frequencies(stats_opinion_df["content"])
            if frequencies:
                st.markdown(build_circular_wordcloud_html(frequencies), unsafe_allow_html=True)
                top_words = ", ".join([f"{word}({count})" for word, count in frequencies.most_common(8)])
                st.caption(f"상위 키워드: {top_words}")
            else:
                st.info("워드클라우드를 만들 단어가 아직 부족합니다.")
    else:
        st.write("데이터 수집 중...")

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

        # 공감 데이터 로드
        use_likes = likes_available()
        likes_count = {}
        my_likes = set()
        badge_map = {}
        my_anon_ip = ""
        on_like_cooldown = False
        if use_likes:
            likes_data = fetch_room_likes(supabase, room_name)
            likes_count = Counter(item['opinion_id'] for item in likes_data)
            my_likes = {item['opinion_id'] for item in likes_data if item['student_name'] == student_name}
            raw_client_ip = get_client_ip()
            if raw_client_ip:
                my_anon_ip = _anon_ip(raw_client_ip)
            # 동점 처리: 같은 공감 수 = 같은 등수 (dense rank)
            distinct_counts = sorted({c for c in likes_count.values() if c > 0}, reverse=True)[:3]
            count_to_rank = {c: rank for rank, c in enumerate(distinct_counts, 1)}
            badge_map = {
                oid: _RANK_BADGES[count_to_rank[cnt]]
                for oid, cnt in likes_count.items()
                if cnt > 0 and cnt in count_to_rank
            }
            # 쿨다운 확인
            on_like_cooldown = (time.time() - st.session_state.get('_last_like_ts', 0)) < _LIKE_COOLDOWN

        def delete_chat_msg(msg_id):
            try:
                if delete_opinion_message(supabase, msg_id) is None:
                    return
                fetch_live_messages.clear()
                log_audit("chat_deleted", room_name=room_name, actor_name=student_name, role=user_role, message_id=msg_id)
                st.toast("의견이 즉시 삭제되었습니다.", icon="🗑️")
            except Exception as e:
                st.error(f"삭제 실패: {e}")

        def do_toggle_like(msg_id):
            toggle_like(supabase, msg_id, room_name, student_name)
            fetch_room_likes.clear()
            st.session_state['_last_like_ts'] = time.time()

        def render_msg(row):
            formatted_timestamp = format_kst_datetime(row.get("timestamp", ""))
            msg_id = row['id']
            count = likes_count.get(msg_id, 0)
            is_liked = msg_id in my_likes
            badge = badge_map.get(msg_id, "")

            # 셀프 공감 차단: 의견 작성자 IP와 현재 사용자 IP 비교
            row_ip = str(row.get("ip_address", "")).strip() if hasattr(row, "get") else ""
            is_self = bool(my_anon_ip and row_ip and my_anon_ip == row_ip)
            like_disabled = is_self or not use_likes or on_like_cooldown
            like_label = f"👍 {count}" if count > 0 else "👍"
            like_type = "primary" if is_liked else "secondary"

            name_badge = f"{badge} " if badge else ""

            if user_role == "교사" and teacher_auth:
                c_name, c_like, c_del = st.columns([5, 1, 1])
                with c_name:
                    st.markdown(
                        f"**{name_badge}{row['student_name']}** "
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
                    st.button("❌", key=f"del_{msg_id}", help="강제 삭제",
                              on_click=delete_chat_msg, args=(msg_id,))
            else:
                c_name, c_like = st.columns([5, 1])
                with c_name:
                    st.markdown(
                        f"**{name_badge}{row['student_name']}** "
                        f"<span style='color:gray; font-size:14px;'>{formatted_timestamp}</span>",
                        unsafe_allow_html=True,
                    )
                with c_like:
                    st.button(like_label, key=f"like_{msg_id}", disabled=like_disabled,
                              type=like_type, use_container_width=True,
                              on_click=do_toggle_like, args=(msg_id,))
            st.info(row['content'])
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
            col_idea, col_plus, col_q = st.columns(3)
            with col_idea:
                st.markdown("### 💡 아이디어")
                with st.container(height=450):
                    for _, row in student_df[student_df['sentiment'] == '💡 아이디어'].iterrows():
                        render_msg(row)
            with col_plus:
                st.markdown("### ➕ 보충")
                with st.container(height=450):
                    for _, row in student_df[student_df['sentiment'] == '➕ 보충'].iterrows():
                        render_msg(row)
            with col_q:
                st.markdown("### ❓ 질문")
                with st.container(height=450):
                    for _, row in student_df[student_df['sentiment'] == '❓ 질문'].iterrows():
                        render_msg(row)
    else:
        st.info(f"아직 대화가 없습니다. 첫 {act_type} 의견을 남겨주세요!")


@st.fragment(run_every=LIVE_REFRESH_INTERVAL)
def _live_chat_board_auto(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type):
    _live_chat_board_core(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type)


def render_chat_board(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type):
    if st.session_state.get('is_working', False):
        _live_chat_board_core(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type)
    else:
        _live_chat_board_auto(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type)
