import logging

import plotly.express as px
import streamlit as st

from db import destroy_room_data, fetch_live_messages
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
