import io
import logging

import pandas as pd
import streamlit as st

from db import delete_student_record, fetch_student_records, save_student_record
from env import get_secret
from services.ai import generate_ai_response, build_record_prompt
from utils import get_kst_now, get_kst_now_str, log_audit
from config import AI_MODEL_NAME, RECORDS_FETCH_LIMIT

logger = logging.getLogger("talk_trace_ai")


@st.fragment
def render_records_section(supabase, room_name, user_role, student_name, act_type, current_topic, df_all, student_only_df):
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
                            prompt, model_name=AI_MODEL_NAME, api_key=get_secret("GEMINI_API_KEY", ""),
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
