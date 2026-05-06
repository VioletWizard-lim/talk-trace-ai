import html
import io
import logging

import pandas as pd
import plotly.express as px
import streamlit as st

from db import (
    create_teacher_hint,
    delete_student_record,
    destroy_room_data,
    fetch_live_messages,
    fetch_student_records,
    save_student_record,
    _get_secret,
)
from services.ai import generate_ai_response
from services.prompts import build_hint_prompt, build_summary_prompt, build_record_prompt
from validators import with_fallback_author_role
from utils import compact_ai_report_output, get_kst_now, get_kst_now_str, log_audit
from config import (
    AI_MODEL_NAME,
    AI_HINT_ENABLED,
    DASHBOARD_FETCH_LIMIT,
    RECORDS_FETCH_LIMIT,
    ROOM_DESTROY_ENABLED,
    UI_FONT_FAMILY,
)

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

    @st.fragment
    def teacher_hint_section():
        st.subheader(f"💡 AI {act_type} 촉진 (Teacher-in-the-loop)")
        st.info("AI 제안을 수정 후 전송하세요.")

        def send_hint():
            val = st.session_state.get('hint_input_widget', '').strip()
            if val:
                now = get_kst_now_str()
                try:
                    res = create_teacher_hint(supabase, {
                        "room_name": room_name, "timestamp": now,
                        "student_name": "👨‍🏫 선생님 (AI 보조)",
                        "content": val, "sentiment": "❓ 질문", "author_role": "교사"
                    })
                    if res is None:
                        return
                    log_audit("teacher_hint_sent", room_name=room_name, actor_name=student_name, role=user_role)
                    st.session_state['hint_input_widget'] = ""
                except Exception as e:
                    st.error(f"힌트 전송 실패: {e}")

        if AI_HINT_ENABLED:
            if st.button("🪄 AI 힌트 초안 생성", use_container_width=True):
                st.toast("👀 AI가 대화 맥락을 읽고 있습니다...", icon="⏳")
                with st.spinner("✍️ 예리한 질문을 작성하고 있습니다..."):
                    context = "\n".join(df_all['content'].tail(5).tolist()) if not df_all.empty else "대화 없음"
                    prompt = build_hint_prompt(act_type, current_topic, context)
                    res_text = generate_ai_response(
                        prompt, model_name=AI_MODEL_NAME, api_key=_get_secret("GEMINI_API_KEY", ""),
                        log_message="AI 힌트 생성 실패", room_name=room_name,
                    )
                    if res_text:
                        st.session_state['hint_input_widget'] = res_text.strip().split('\n')[0]
                        st.session_state['ai_hint_manual_mode'] = False
                        st.toast("✅ 힌트 작성 완료!", icon="🎉")
                    else:
                        st.session_state['ai_hint_manual_mode'] = True
                        st.toast("🚨 AI 호출 오류: 수동 모드로 전환되었습니다.", icon="❌")
        else:
            st.session_state['ai_hint_manual_mode'] = True

        col_edit_txt, col_edit_btn = st.columns([8, 2])
        with col_edit_txt:
            st.text_input("선생님의 검토 및 수정", key="hint_input_widget", label_visibility="collapsed", placeholder="여기에 AI 힌트가 나타납니다.")
        with col_edit_btn:
            st.button("🚀 학생 화면 전송", use_container_width=True, type="primary", on_click=send_hint)

    teacher_hint_section()
    st.divider()

    @st.fragment
    def teacher_summary_section():
        st.subheader(f"📝 수업 종료 및 전체 {act_type} 요약 리포트")
        if st.button(f"{act_type} 요약 및 베스트 발언 추출 🪄", use_container_width=True):
            st.toast("👀 AI가 전체 기록을 꼼꼼히 읽고 있습니다...", icon="⏳")
            with st.spinner("✍️ 요약 리포트를 작성하고 있습니다..."):
                if not df_all.empty:
                    full_history = "\n".join([
                        f"[{row['student_name']} - {row['sentiment']}] {row['content']}"
                        for _, row in df_all.iterrows()
                    ])
                    prompt = build_summary_prompt(act_type, current_topic, full_history)
                    res_text = generate_ai_response(
                        prompt, model_name=AI_MODEL_NAME, api_key=_get_secret("GEMINI_API_KEY", ""),
                        log_message="AI 요약 리포트 생성 실패", room_name=room_name,
                    )
                    if res_text:
                        st.session_state['ai_report_text'] = compact_ai_report_output(res_text)
                        st.toast("✅ 리포트 작성 완료!", icon="🎉")
                    else:
                        st.toast("🚨 AI 호출 오류가 발생했습니다.", icon="❌")
                else:
                    st.toast("🚨 분석할 데이터가 없습니다.", icon="⚠️")
        if st.session_state.get('ai_report_text'):
            st.info(f"📊 **AI 수업 {act_type} 요약 리포트**")
            report_html = html.escape(st.session_state['ai_report_text']).replace("\n", "<br>")
            st.markdown(f"<div style='line-height:1.8;'>{report_html}</div>", unsafe_allow_html=True)

    teacher_summary_section()
    st.divider()

    @st.fragment
    def teacher_record_section():
        def delete_selected_record():
            del_id = st.session_state.get('del_record_dropdown')
            if del_id:
                try:
                    if delete_student_record(supabase, del_id) is None:
                        return
                    log_audit("record_deleted", room_name=room_name, actor_name=student_name, role=user_role, record_id=del_id)
                    st.toast("기록이 삭제되었습니다.", icon="🗑️")
                except Exception as e:
                    st.error(f"기록 삭제 실패: {e}")

        col3, col4 = st.columns([1, 1])
        with col3:
            st.subheader("📥 활동 데이터 다운로드")
            if not df_all.empty:
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    df_all.to_excel(writer, index=False)
                st.download_button(
                    f"{act_type} 전체 활동 로그 (Excel)",
                    data=buffer.getvalue(),
                    file_name=f"{room_name}_log_{get_kst_now().strftime('%Y%m%d_%H%M')}.xlsx",
                )

        with col4:
            st.subheader("🤖 개인별 AI 세특 초안 생성")
            student_list = student_only_df['student_name'].unique() if not student_only_df.empty else []
            if len(student_list) > 0:
                selected_student = st.selectbox("학생을 선택하세요", student_list)
                if st.button(f"'{selected_student}' 세특 생성 🪄", use_container_width=True):
                    st.toast(f"👀 AI가 '{selected_student}' 학생의 활동을 분석합니다...", icon="⏳")
                    with st.spinner(f"✍️ '{selected_student}' 학생의 세특 초안 작성 중..."):
                        try:
                            student_data = df_all[df_all['student_name'] == selected_student]
                            debate_history = "\n".join([f"- [{row['sentiment']}] {row['content']}" for _, row in student_data.iterrows()])
                            prompt = build_record_prompt(act_type, current_topic, selected_student, debate_history)
                            res_text = generate_ai_response(
                                prompt, model_name=AI_MODEL_NAME, api_key=_get_secret("GEMINI_API_KEY", ""),
                                log_message="AI 세특 생성 실패", room_name=room_name, student=selected_student,
                            )
                            if res_text:
                                st.session_state['ai_result_text'] = res_text
                                now = get_kst_now_str()
                                save_res = save_student_record(supabase, {
                                    "room_name": room_name, "timestamp": now,
                                    "student_name": selected_student, "content": res_text,
                                })
                                if save_res is None:
                                    raise RuntimeError("보관함 저장 실패")
                                st.toast("✅ 세특 생성 및 보관함 저장 완료!", icon="🎉")
                            else:
                                raise RuntimeError("AI 응답 비어있음")
                        except Exception:
                            logger.exception("세특 생성 후처리 실패")
                            st.toast("🚨 오류가 발생했습니다. 다시 시도해주세요.", icon="❌")
                if st.session_state.get('ai_result_text'):
                    st.success("🤖 **개인별 세특 초안** (보관함에 자동 저장되었습니다)")
                    st.text_area("내용 수정 후 복사하여 사용하세요", value=st.session_state['ai_result_text'], height=200, label_visibility="collapsed")
            else:
                st.info("실명 참여 학생이 없습니다.")

        st.divider()
        st.subheader("📂 저장된 세특 기록 보관함")
        records_df = fetch_student_records(supabase, room_name, RECORDS_FETCH_LIMIT)
        if not records_df.empty:
            records_display_df = records_df.rename(columns={"id": "No.", "content": "세특 내용"})
            records_html = records_display_df.to_html(index=False, escape=True)
            st.markdown(f"<div class='records-db-table-wrap'>{records_html}</div>", unsafe_allow_html=True)
            col_down, col_del = st.columns([1, 1])
            with col_down:
                buffer_records = io.BytesIO()
                with pd.ExcelWriter(buffer_records, engine='openpyxl') as writer:
                    records_df.drop(columns=['id']).to_excel(writer, index=False)
                st.download_button("📥 세특 보관함 다운로드 (Excel)", data=buffer_records.getvalue(), file_name=f"{room_name}_세특보관함.xlsx")
            with col_del:
                st.selectbox("🗑️ 삭제할 '고유 번호(No.)' 선택", records_df['id'].tolist(), key="del_record_dropdown")
                st.button("선택한 세특 기록 영구 삭제", type="primary", on_click=delete_selected_record)
        else:
            st.info("저장된 기록이 없습니다.")

    teacher_record_section()

    st.divider()
    st.subheader("🚨 위험 구역 (방 폭파)")
    with st.expander("이 방 전체 삭제하기 (클릭 시 펼쳐짐)", expanded=False):
        if not ROOM_DESTROY_ENABLED:
            st.warning("운영 안전 모드로 방 폭파 기능이 비활성화되어 있습니다.")
        else:
            st.error(f"🚨 경고: '{room_name}' 방의 모든 {act_type} 기록과 세특 보관함이 완전히 삭제됩니다.")
            if st.button(f"네, '{room_name}' 방의 모든 데이터를 영구 삭제합니다", type="primary", use_container_width=True):
                try:
                    if destroy_room_data(supabase, room_name) is None:
                        st.stop()
                    log_audit("room_destroyed", room_name=room_name, actor_name=student_name, role=user_role)
                    st.success("성공적으로 파괴되었습니다.")
                    st.session_state['ai_result_text'] = ""
                    st.rerun()
                except Exception as e:
                    st.error(f"삭제 중 오류 발생: {e}")
