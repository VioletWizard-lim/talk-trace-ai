import streamlit as st
from db import (
    fetch_room_entry_code,
    find_duplicate_session,
    check_and_log_presence,
    find_number_switch_abuse,
)
from validators import validate_student_number
from config import AUTO_JOIN_ON_REFRESH


def _apply_lobby_room_pick():
    st.session_state['student_room_select'] = st.session_state['lobby_room_picker']


def render_lobby_page(supabase, user_role, teacher_auth, room_name, student_number, available_rooms=None):
    admin_auth = st.session_state.get('admin_auth', False)
    if admin_auth and teacher_auth:
        col_title, col_btn1 = st.columns([6, 2])
        with col_title:
            st.title("🚪 말자취 AI 대기실")
        with col_btn1:
            if st.button("📝 ID 요청 수락", use_container_width=True):
                st.session_state['page'] = "admin_approval"
                st.rerun()
    else:
        st.title("🚪 말자취 AI 대기실")
    if user_role == "교사" and not teacher_auth:
        st.warning("🚨 승인된 교사 계정으로 로그인해야 입장할 수 있습니다.")
    elif not room_name.strip():
        st.error("🚨 접속할 방을 먼저 선택해 주세요.")
    else:
        if user_role == "학생":
            if available_rooms:
                st.selectbox(
                    "🏠 접속할 방 선택", available_rooms, key="lobby_room_picker",
                    index=available_rooms.index(room_name) if room_name in available_rooms else 0,
                    on_change=_apply_lobby_room_pick,
                )
            student_pw = st.text_input("🔒 방 입장 암호 (공개방이면 비워두세요)", type="password")
            number_ok, _, _, number_error_message = validate_student_number(student_number)
            if st.button(f"🚀 '{room_name}' 입장하기", type="primary", use_container_width=True):
                real_pw = fetch_room_entry_code(supabase, room_name)
                if real_pw is None:
                    st.error("🚨 방 암호 정보를 확인할 수 없어 입장을 차단했습니다. 잠시 후 다시 시도해 주세요.")
                elif real_pw and student_pw != real_pw:
                    st.error("❌ 암호가 틀렸습니다.")
                elif not number_ok:
                    st.error(f"❌ {number_error_message}")
                else:
                    session_id = st.session_state.get("session_uuid", "")
                    already_used = find_number_switch_abuse(supabase, room_name, session_id, student_number)
                    if already_used:
                        st.error(
                            f"❌ 이 브라우저는 이미 {len(already_used)}개의 다른 학번({', '.join(already_used)})으로 "
                            "이 방에 입장한 기록이 있습니다. 학번을 여러 번 바꿔 입장할 수 없습니다."
                        )
                    else:
                        is_duplicate = (
                            check_and_log_presence(supabase, room_name, student_number, session_id)
                            or find_duplicate_session(supabase, room_name, student_number, session_id)
                        )
                        if is_duplicate:
                            st.toast(
                                "⚠️ 이 학번은 다른 기기/브라우저에서 이미 접속 중인 것 같습니다. 본인이 맞는지 확인해 주세요.",
                                icon="⚠️",
                            )
                        st.session_state['joined'] = True
                        st.rerun()
        else:
            if AUTO_JOIN_ON_REFRESH and teacher_auth and not admin_auth:
                st.session_state['joined'] = True
                st.rerun()
            if st.button(f"🚀 '{room_name}' 관리자 권한으로 입장", type="primary", use_container_width=True):
                st.session_state['joined'] = True
                st.rerun()
    st.stop()
