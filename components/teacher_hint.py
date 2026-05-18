import streamlit as st

from db import create_teacher_hint, fetch_live_messages
from env import get_secret
from services.ai import generate_ai_response, build_hint_prompt
from utils import get_kst_now_str, log_audit
from config import AI_MODEL_NAME, AI_HINT_ENABLED


@st.fragment
def render_hint_section(supabase, room_name, user_role, student_name, current_topic, act_type, df_all):
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
                fetch_live_messages.clear()
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
                    prompt, model_name=AI_MODEL_NAME, api_key=get_secret("GEMINI_API_KEY", ""),
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
