import streamlit as st
from db import fetch_room_entry_code
from validators import normalize_user_text
from config import AUTO_JOIN_ON_REFRESH


def render_lobby_page(supabase, user_role, teacher_auth, room_name, student_number):
    st.title("🚪 말자취(Talk-Trace) AI 대기실")
    if user_role == "교사" and not teacher_auth:
        st.warning("🚨 승인된 교사 계정으로 로그인해야 입장할 수 있습니다.")
    elif not room_name.strip():
        st.error("🚨 접속할 방을 먼저 선택해 주세요.")
    else:
        if user_role == "학생":
            student_pw = st.text_input("🔒 방 입장 암호 (공개방이면 비워두세요)", type="password")
            if st.button(f"🚀 '{room_name}' 입장하기", type="primary", use_container_width=True):
                real_pw = fetch_room_entry_code(supabase, room_name)
                if real_pw is None:
                    st.error("🚨 방 암호 정보를 확인할 수 없어 입장을 차단했습니다. 잠시 후 다시 시도해 주세요.")
                elif real_pw and student_pw != real_pw:
                    st.error("❌ 암호가 틀렸습니다.")
                elif not normalize_user_text(student_number, max_len=20):
                    st.error("❌ 학번을 입력해야 입장할 수 있습니다.")
                else:
                    st.session_state['joined'] = True
                    st.rerun()
        else:
            if AUTO_JOIN_ON_REFRESH and teacher_auth:
                st.session_state['joined'] = True
                st.rerun()
            if st.button(f"🚀 '{room_name}' 관리자 권한으로 입장", type="primary", use_container_width=True):
                st.session_state['joined'] = True
                st.rerun()
    st.stop()
