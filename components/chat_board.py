import streamlit as st
import plotly.express as px
from db import fetch_live_messages, delete_opinion_message
from validators import with_fallback_author_role, mask_ip_for_teacher
from utils import format_kst_datetime, log_audit
from wordcloud import build_word_frequencies, build_circular_wordcloud_html
from config import DASHBOARD_FETCH_LIMIT, LIVE_BOARD_FETCH_LIMIT, LIVE_REFRESH_INTERVAL, UI_FONT_FAMILY


def _live_chat_board_core(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type):
    all_df = with_fallback_author_role(
        fetch_live_messages(supabase, room_name, DASHBOARD_FETCH_LIMIT)
    )
    opinion_df = all_df.head(LIVE_BOARD_FETCH_LIMIT) if not all_df.empty else all_df
    stats_opinion_df = all_df

    st.subheader("📊 실시간 의견 통계")
    if not stats_opinion_df.empty:
        left_col, right_col = st.columns(2)
        with left_col:
            st.caption("감정 분포 그래프")
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

        def delete_chat_msg(msg_id):
            try:
                if delete_opinion_message(supabase, msg_id) is None:
                    return
                log_audit("chat_deleted", room_name=room_name, actor_name=student_name, role=user_role, message_id=msg_id)
                st.toast("의견이 즉시 삭제되었습니다.", icon="🗑️")
            except Exception as e:
                st.error(f"삭제 실패: {e}")

        def render_msg(row):
            formatted_timestamp = format_kst_datetime(row.get("timestamp", ""))
            if user_role == "교사" and teacher_auth:
                c_name, c_btn = st.columns([5, 1])
                with c_name:
                    st.markdown(f"**{row['student_name']}** <span style='color:gray; font-size:14px;'>{formatted_timestamp}</span>", unsafe_allow_html=True)
                    row_ip = str(row.get("ip_address", "")).strip() if hasattr(row, "get") else ""
                    if row_ip:
                        st.caption(f"IP: {mask_ip_for_teacher(row_ip)}")
                with c_btn:
                    st.button("❌", key=f"del_{row['id']}", help="강제 삭제", on_click=delete_chat_msg, args=(row['id'],))
                st.info(row['content'])
            else:
                st.markdown(f"**{row['student_name']}** <span style='color:gray; font-size:14px;'>{formatted_timestamp}</span>", unsafe_allow_html=True)
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
