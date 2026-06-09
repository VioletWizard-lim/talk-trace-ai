import streamlit as st

from db import (
    fetch_room_names,
    fetch_room_names_by_owner,
    topic_owner_column_available,
    topic_entry_code_column_available,
    upsert_topic_room,
)
from validators import (
    normalize_user_text,
    validate_entry_code,
    validate_opinion_content,
    validate_room_name,
)
from utils import log_audit
from config import MAX_ROOM_NAME_LEN, MAX_TOPIC_LEN, MAX_ENTRY_CODE_LEN
from components.teacher_auth import render_teacher_auth


def _reset_joined_state():
    st.session_state['joined'] = False
    st.session_state['teacher_auth'] = False
    st.session_state['admin_auth'] = False
    st.session_state['teacher_id'] = ""
    st.session_state.pop('_admin_redirected', None)


def render_sidebar(supabase) -> dict:
    with st.sidebar:
        st.header("👤 접속 권한")
        user_role = st.radio("모드 선택", ["학생", "교사"], on_change=_reset_joined_state)
        st.divider()

        try:
            all_rooms = fetch_room_names(supabase)
        except Exception:
            all_rooms = []

        room_name = ""
        teacher_auth = False
        admin_auth = False
        student_number = ""

        if user_role == "교사":
            render_teacher_auth(supabase)
            teacher_auth = st.session_state['teacher_auth']
            admin_auth = st.session_state['admin_auth']
            teacher_id_for_scope = st.session_state.get("teacher_id", "")

            if teacher_auth:
                existing_rooms = all_rooms if admin_auth else (
                    fetch_room_names_by_owner(supabase, teacher_id_for_scope)
                    if topic_owner_column_available()
                    else []
                )
                if not admin_auth and not topic_owner_column_available():
                    st.warning("교사별 방 조회를 위해 topic.created_by_teacher_id(권장) 또는 topic.created_by 컬럼이 필요합니다.")

                room_opt = st.radio("방 관리", ["기존 방 선택", "새 방 만들기"])

                if room_opt == "기존 방 선택":
                    if existing_rooms:
                        current = st.session_state.get('current_room', '')
                        default_idx = existing_rooms.index(current) if current in existing_rooms else 0
                        room_name = st.selectbox("토론/토의방 목록", existing_rooms, index=default_idx)
                    else:
                        st.info("아직 개설된 방이 없습니다. '새 방 만들기'를 선택해 첫 번째 방을 만들어보세요.")
                        room_name = ""
                else:
                    new_room = st.text_input("새로 만들 방 이름 (예: 1학년 3반)")
                    new_title = st.text_input("주제 직접 입력 (예: 인공지능 윤리)")
                    new_mode = st.radio("진행 방식", ["⚔️ 찬반 토론", "💡 자유 토의"], horizontal=True)
                    new_pw = st.text_input("🔒 학생 입장용 암호 (비워두면 공개방)")
                    if st.button("새 방 개설하기", type="primary"):
                        room_ok, safe_new_room, _, room_error_message = validate_room_name(new_room, max_len=MAX_ROOM_NAME_LEN)
                        title_ok, safe_new_title, _, title_error_message = validate_opinion_content(new_title, max_len=MAX_TOPIC_LEN)
                        entry_ok, safe_new_pw, _, entry_error_message = validate_entry_code(new_pw, max_len=MAX_ENTRY_CODE_LEN)
                        can_store_room_pw = topic_entry_code_column_available()
                        if not room_ok:
                            st.error(f"❌ {room_error_message}")
                        elif not title_ok:
                            st.error(f"❌ {title_error_message}")
                        elif not entry_ok:
                            st.error(f"❌ {entry_error_message}")
                        elif safe_new_pw and not can_store_room_pw:
                            st.error("현재 DB 구조에서는 방 비밀번호 저장을 지원하지 않습니다.")
                        elif safe_new_room and safe_new_title:
                            res = upsert_topic_room(
                                supabase=supabase, room_name=safe_new_room, title=safe_new_title,
                                mode=new_mode, entry_code=safe_new_pw, created_by=teacher_id_for_scope,
                            )
                            if res is not None:
                                fetch_room_names.clear()
                                fetch_room_names_by_owner.clear()
                                st.session_state['current_room'] = safe_new_room
                                st.toast(f"'{safe_new_room}' 방이 개설되었습니다!", icon="🎉")
                                st.rerun()
                    room_name = ""
        else:
            st.session_state['teacher_auth'] = False
            st.session_state['admin_auth'] = False
            st.session_state['teacher_id'] = ""
            if st.session_state.get('page') == "admin_approval":
                st.session_state['page'] = "lobby"
            _joined = st.session_state.get('joined', False)
            student_number = st.text_input(
                "학번",
                key="student_number_input",
                placeholder="예: 1101",
                disabled=_joined,
                help="방 입장 후에는 학번을 변경할 수 없습니다." if _joined else None,
            )
            if all_rooms:
                room_name = st.selectbox("🏠 접속할 방 선택", all_rooms)
            else:
                st.warning("선생님이 아직 열어둔 방이 없습니다.")
                room_name = ""

        student_name = normalize_user_text(student_number, max_len=20) if user_role == "학생" else "교사"

        if room_name and room_name != st.session_state['current_room']:
            prev_room = st.session_state['current_room']
            st.session_state['current_room'] = room_name
            st.session_state['ai_hint_text'] = ""
            st.session_state['ai_report_text'] = ""
            st.session_state.pop('_admin_redirected', None)
            if st.session_state['joined']:
                st.session_state['joined'] = False
                log_audit("room_switched_to_lobby", room_name=room_name, actor_name=student_name, role=user_role, previous_room=prev_room)
                st.rerun()

        if st.session_state['joined']:
            st.divider()
            if st.button("🚪 방 나가기 (대기실로)"):
                st.session_state['joined'] = False
                st.session_state.pop('_admin_redirected', None)
                st.rerun()

    return {
        'user_role': user_role,
        'room_name': room_name,
        'teacher_auth': teacher_auth,
        'admin_auth': admin_auth,
        'student_name': student_name,
        'student_number': student_number,
    }
