import logging

import plotly.express as px
import streamlit as st

from db import destroy_room_data, fetch_all_opinion_changes, fetch_debate_status, fetch_live_messages, opinion_changes_available, session_control_available, set_debate_status, stance_available
from utils import create_analysis_image
from components.opinion_change import _render_image_download, _STANCE_OPTIONS
from wordcloud import build_word_frequencies, build_circular_wordcloud_html
from validators import with_fallback_author_role
from utils import log_audit
from config import DASHBOARD_FETCH_LIMIT, ROOM_DESTROY_ENABLED, UI_FONT_FAMILY
from components.teacher_hint import render_hint_section
from components.teacher_summary import render_summary_section
from components.teacher_records import render_records_section

logger = logging.getLogger("talk_trace_ai")


def render_teacher_dashboard(supabase, room_name, user_role, student_name, current_topic, current_mode, act_type):
    st.divider()
    col_dash_title, col_dash_refresh = st.columns([8, 2])
    with col_dash_title:
        st.header("👨‍🏫 교사 관리 대시보드")
    with col_dash_refresh:
        if st.button("🔄 대시보드 수동 새로고침", use_container_width=True):
            st.rerun()

    df_all = with_fallback_author_role(fetch_live_messages(supabase, room_name, DASHBOARD_FETCH_LIMIT))
    student_only_df = (
        df_all[
            (df_all['author_role'] == '학생') &
            ~df_all['student_name'].str.contains('익명|AI', na=False, regex=True)
        ].copy()
        if not df_all.empty else df_all
    )

    st.subheader("📊 학생 참여도 현황")
    if not df_all.empty:
        if not student_only_df.empty:
            counts = student_only_df['student_name'].astype(str).value_counts().reset_index()
            counts.columns = ['학생 이름', '참여 횟수']
            counts['학생 이름'] = counts['학생 이름'] + " "
            fig = px.bar(counts, x='학생 이름', y='참여 횟수', text='참여 횟수', color='학생 이름')
            fig.update_xaxes(type='category', title="")
            fig.update_layout(yaxis_title="의견 수", dragmode=False, showlegend=False, font={"family": UI_FONT_FAMILY})
            st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False})
        else:
            st.info("실명 참여 데이터가 없습니다.")
    else:
        st.info(f"{act_type} 데이터가 없습니다.")

    if opinion_changes_available():
        df_oc = fetch_all_opinion_changes(supabase, room_name)
        if not df_oc.empty:
            st.divider()
            st.subheader("🔍 학생별 배움 분석")
            students = df_oc["student_name"].tolist()
            selected = st.selectbox("학생 선택", students, key="oc_student_select")
            row = df_oc[df_oc["student_name"] == selected].iloc[0]
            pre  = row.get("pre_opinion")  or "(없음)"
            post = row.get("post_opinion") or "(없음)"
            ai   = row.get("ai_analysis")  or ""

            if stance_available() and act_type == "토론":
                init_s = row.get("initial_stance") or ""
                final_s = row.get("final_stance") or ""
                if init_s or final_s:
                    col_is, col_fs = st.columns(2)
                    with col_is:
                        st.caption("📌 토론 전 입장")
                        st.info(init_s or "(미입력)")
                    with col_fs:
                        st.caption("🗳️ 토론 후 최종 입장")
                        st.info(final_s or "(미입력)")

            col_pre, col_post = st.columns(2)
            with col_pre:
                st.caption("📌 토론 전 생각")
                st.info(pre)
            with col_post:
                st.caption("🔄 토론 후 생각")
                st.info(post)
            if ai:
                st.caption("🤖 AI 배움 분석")
                st.markdown(ai.replace("\n", "\n\n"))
                _render_image_download(
                    selected, current_topic, pre, post, ai,
                    session_key=f"img_teacher_{room_name}_{selected}",
                    btn_key="dl_analysis_teacher",
                )
            else:
                st.caption("AI 분석이 아직 없습니다.")

            # 입장 변화 도넛 차트 (토론) / 워드클라우드 (토의)
            if stance_available():
                st.divider()
                if act_type == "토론":
                    st.subheader("📊 입장 변화 현황")
                    col_d1, col_d2 = st.columns(2)
                    for col, col_name, label in [
                        (col_d1, "initial_stance", "토론 전 초기 입장"),
                        (col_d2, "final_stance",   "토론 후 최종 입장"),
                    ]:
                        if col_name in df_oc.columns:
                            counts = (
                                df_oc[col_name]
                                .dropna()
                                .value_counts()
                                .reindex(_STANCE_OPTIONS, fill_value=0)
                                .reset_index()
                            )
                            counts.columns = ["입장", "인원"]
                            with col:
                                st.caption(label)
                                if counts["인원"].sum() > 0:
                                    fig = px.pie(
                                        counts, names="입장", values="인원",
                                        hole=0.45,
                                        color="입장",
                                        color_discrete_map={
                                            "🔵 찬성": "#1558a0",
                                            "🔴 반대": "#d62728",
                                        },
                                    )
                                    fig.update_layout(
                                        margin=dict(t=10, b=10, l=10, r=10),
                                        font={"family": UI_FONT_FAMILY},
                                        showlegend=True,
                                        legend=dict(orientation="h"),
                                    )
                                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                                else:
                                    st.info("아직 입력된 입장이 없습니다.")
                elif act_type == "토의":
                    if "discussion_conclusion" in df_oc.columns:
                        conclusions = df_oc["discussion_conclusion"].dropna()
                        if not conclusions.empty:
                            st.subheader("☁️ 결론 워드클라우드")
                            freq = build_word_frequencies(conclusions)
                            if freq:
                                st.markdown(build_circular_wordcloud_html(freq), unsafe_allow_html=True)
                        else:
                            st.info("아직 제출된 결론이 없습니다.")

    if session_control_available():
        st.divider()
        st.subheader("🎛️ 토론 진행 제어")
        debate_status = fetch_debate_status(supabase, room_name)
        if debate_status == "ended":
            st.warning("🔴 **토론이 종료된 상태입니다.** 학생들은 '토론 후 생각 변화'를 작성 중입니다.")
            if st.button("▶️ 토론 재개", use_container_width=True):
                if set_debate_status(supabase, room_name, "active") is not None:
                    st.toast("✅ 토론이 재개되었습니다.", icon="▶️")
                    st.rerun()
        else:
            st.success("🟢 **토론 진행 중입니다.**")
            if st.button("⏹️ 토론 종료 (학생 입력 마감)", use_container_width=True, type="primary"):
                if set_debate_status(supabase, room_name, "ended") is not None:
                    st.toast("⏹️ 토론이 종료되었습니다. 학생들에게 생각 변화 입력창이 표시됩니다.", icon="✅")
                    st.rerun()

    st.divider()
    render_hint_section(supabase, room_name, user_role, student_name, current_topic, act_type, df_all)
    st.divider()
    render_summary_section(room_name, act_type, current_topic, df_all)
    st.divider()
    render_records_section(room_name, act_type, df_all)

    st.divider()
    st.subheader("🚨 위험 구역 (방 폭파)")
    with st.expander("이 방 전체 삭제하기 (클릭 시 펼쳐짐)", expanded=False):
        if not ROOM_DESTROY_ENABLED:
            st.warning("운영 안전 모드로 방 폭파 기능이 비활성화되어 있습니다.")
        else:
            st.error(f"🚨 경고: '{room_name}' 방의 모든 {act_type} 기록이 완전히 삭제됩니다.")
            if st.button(f"네, '{room_name}' 방의 모든 데이터를 영구 삭제합니다", type="primary", use_container_width=True):
                try:
                    if destroy_room_data(supabase, room_name) is None:
                        st.stop()
                    log_audit("room_destroyed", room_name=room_name, actor_name=student_name, role=user_role)
                    st.success("성공적으로 파괴되었습니다.")
                    st.rerun()
                except Exception as e:
                    st.error(f"삭제 중 오류 발생: {e}")
