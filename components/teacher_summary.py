import html

import streamlit as st

from env import get_secret
from services.ai import generate_ai_response, build_summary_prompt
from utils import compact_ai_report_output
from config import AI_MODEL_NAME


@st.fragment
def render_summary_section(room_name, act_type, current_topic, df_all):
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
                try:
                    res_text = generate_ai_response(
                        prompt, model_name=AI_MODEL_NAME, api_key=get_secret("GEMINI_API_KEY", ""),
                        log_message="AI 요약 리포트 생성 실패", room_name=room_name,
                    )
                except Exception as e:
                    st.error(f"🚨 AI 호출 중 오류가 발생했습니다: {e}")
                    res_text = None
                if res_text:
                    st.session_state['ai_report_text'] = compact_ai_report_output(res_text)
                    st.toast("✅ 리포트 작성 완료!", icon="🎉")
                elif res_text is not None:
                    st.toast("🚨 AI 호출 오류가 발생했습니다.", icon="❌")
            else:
                st.toast("🚨 분석할 데이터가 없습니다.", icon="⚠️")
    if st.session_state.get('ai_report_text'):
        st.info(f"📊 **AI 수업 {act_type} 요약 리포트**")
        report_html = html.escape(st.session_state['ai_report_text']).replace("\n", "<br>")
        st.markdown(f"<div style='line-height:1.8;'>{report_html}</div>", unsafe_allow_html=True)
