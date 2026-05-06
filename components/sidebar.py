import streamlit as st
from db import (
    fetch_room_names,
    fetch_room_names_by_owner,
    fetch_teacher_account,
    request_teacher_account,
    topic_owner_column_available,
    topic_entry_code_column_available,
    upsert_topic_room,
    using_service_role_key,
    _verify_password,
    _is_hashed,
    upgrade_teacher_password,
    _get_secret,
)
from validators import (
    normalize_user_text,
    validate_entry_code,
    validate_opinion_content,
    validate_room_name,
    validate_teacher_credential,
)
from utils import log_audit, to_bool_flag
from config import MAX_ROOM_NAME_LEN, MAX_TOPIC_LEN, MAX_ENTRY_CODE_LEN


def reset_joined_state():
    st.session_state['joined'] = False
    st.session_state['teacher_auth'] = False
    st.session_state['admin_auth'] = False
    st.session_state['teacher_id'] = ""


def redirect_from_admin_page_if_needed():
    if st.session_state.get('page') == "admin_approval" and not st.session_state.get('admin_auth', False):
        st.session_state['page'] = "lobby"


def render_sidebar(supabase) -> dict:
    with st.sidebar:
        st.header("👤 접속 권한")
        user_role = st.radio("모드 선택", ["학생", "교사"], on_change=reset_joined_state)
        st.divider()

        try:
            all_rooms = fetch_room_names(supabase)
        except Exception:
            all_rooms = []

        room_name = ""
        teacher_auth = False
        admin_auth = False
        student_number = ""
        teacher_id_for_scope = st.session_state.get("teacher_id", "")

        if user_role == "교사":
            auth_mode = st.radio("교사 계정", ["로그인", "ID/PW 신청"], horizontal=True)

            if auth_mode == "로그인":
                with st.form("teacher_login_form"):
                    teacher_id_input = st.text_input("교사 ID", key="teacher_id_input")
                    teacher_pw_input = st.text_input("교사 PW", type="password", key="teacher_pw_input")
                    login_submitted = st.form_submit_button("교사 로그인", use_container_width=True)

                if login_submitted:
                    id_ok, safe_teacher_id, id_error_code, id_error_message = validate_teacher_credential(teacher_id_input, field_name="교사 ID", max_len=60)
                    pw_ok, safe_pw, pw_error_code, pw_error_message = validate_teacher_credential(teacher_pw_input, field_name="교사 PW", max_len=60)
                    if not id_ok:
                        st.error(f"❌ {id_error_message} ({id_error_code})")
                        st.stop()
                    if not pw_ok:
                        st.error(f"❌ {pw_error_message} ({pw_error_code})")
                        st.stop()
                    account = fetch_teacher_account(supabase, safe_teacher_id)
                    if isinstance(account, dict) and account.get("_query_failed"):
                        st.session_state['teacher_auth'] = False
                        st.session_state['admin_auth'] = False
                        st.session_state['teacher_id'] = ""
                        redirect_from_admin_page_if_needed()
                        st.error("🚨 교사 계정 조회에 실패했습니다. Supabase RLS 정책/권한 및 DB 연결 상태를 확인해 주세요.")
                    elif not account:
                        st.session_state['teacher_auth'] = False
                        st.session_state['admin_auth'] = False
                        st.session_state['teacher_id'] = ""
                        redirect_from_admin_page_if_needed()
                        st.error("🚨 등록되지 않은 교사 ID입니다.")
                        if not using_service_role_key():
                            st.warning(
                                "⚠️ 현재 앱이 SERVICE ROLE KEY 없이 동작 중입니다. "
                                "teacher_accounts 테이블에 RLS 정책이 없으면 Data API 조회 결과가 0건으로 나와 "
                                "등록된 계정도 미등록으로 보일 수 있습니다."
                            )
                        try:
                            supabase_url = str(_get_secret("SUPABASE_URL", ""))
                            project_ref = supabase_url.split("//", 1)[-1].split(".", 1)[0] if supabase_url else ""
                            if project_ref:
                                st.caption(f"현재 앱 연결 DB 프로젝트: `{project_ref}`")
                        except Exception:
                            pass
                    elif not _verify_password(safe_pw, account.get("teacher_pw", "")):
                        st.session_state['teacher_auth'] = False
                        st.session_state['admin_auth'] = False
                        st.session_state['teacher_id'] = ""
                        redirect_from_admin_page_if_needed()
                        st.error("❌ 비밀번호가 일치하지 않습니다.")
                    elif not account.get("is_approved"):
                        st.session_state['teacher_auth'] = False
                        st.session_state['admin_auth'] = False
                        st.session_state['teacher_id'] = ""
                        redirect_from_admin_page_if_needed()
                        st.warning("⏳ 최고관리자 승인 후 로그인할 수 있습니다.")
                    else:
                        st.session_state['teacher_auth'] = True
                        st.session_state['admin_auth'] = to_bool_flag(account.get("is_admin", False))
                        st.session_state['teacher_id'] = safe_teacher_id
                        redirect_from_admin_page_if_needed()
                        if not _is_hashed(account.get("teacher_pw", "")):
                            upgrade_teacher_password(supabase, account["id"], safe_pw)
                        if st.session_state['admin_auth']:
                            st.session_state['page'] = "admin_approval"
                            st.toast("✅ 관리자 계정 로그인 성공", icon="✅")
                            st.rerun()
                        else:
                            st.toast("✅ 교사 로그인 성공", icon="✅")
            else:
                req_teacher_id = st.text_input("신청할 교사 ID", key="req_teacher_id")
                req_teacher_pw = st.text_input("신청할 교사 PW", type="password", key="req_teacher_pw")
                if st.button("교사 계정 신청", type="primary", use_container_width=True):
                    id_ok, safe_id, id_error_code, id_error_message = validate_teacher_credential(req_teacher_id, field_name="교사 ID", max_len=60)
                    pw_ok, safe_pw, pw_error_code, pw_error_message = validate_teacher_credential(req_teacher_pw, field_name="교사 PW", max_len=60)
                    if not id_ok:
                        st.error(f"❌ {id_error_message} ({id_error_code})")
                    elif not pw_ok:
                        st.error(f"❌ {pw_error_message} ({pw_error_code})")
                    elif fetch_teacher_account(supabase, safe_id):
                        st.warning("이미 존재하는 ID입니다. 다른 ID를 사용해 주세요.")
                    else:
                        req_res = request_teacher_account(supabase, safe_id, safe_pw)
                        if req_res is not None:
                            st.success("신청 완료! 최고관리자 승인 후 로그인할 수 있습니다.")

            teacher_auth = st.session_state['teacher_auth']
            admin_auth = st.session_state['admin_auth']
            teacher_id_for_scope = st.session_state.get("teacher_id", "")

            if teacher_auth:
                st.caption(f"🔐 {teacher_id_for_scope} 로그인 중")
                if st.button("🚪 로그아웃", use_container_width=True):
                    st.session_state['teacher_auth'] = False
                    st.session_state['admin_auth'] = False
                    st.session_state['teacher_id'] = ""
                    st.session_state['joined'] = False
                    st.session_state['page'] = "lobby"
                    st.rerun()
                st.divider()

            if teacher_auth and admin_auth:
                st.caption("관리자 바로가기")
                if st.button("📝 ID 요청 수락", use_container_width=True):
                    st.session_state['page'] = "admin_approval"
                    st.rerun()
                if st.button("🚪 말자취(Talk-Trace) AI 대기실", use_container_width=True):
                    st.session_state['page'] = "lobby"
                    st.rerun()
                st.divider()

            if teacher_auth:
                existing_rooms = all_rooms if admin_auth else (
                    fetch_room_names_by_owner(supabase, teacher_id_for_scope)
                    if topic_owner_column_available()
                    else []
                )
                if not admin_auth and not topic_owner_column_available():
                    st.warning("교사별 방 조회를 위해 topic.created_by_teacher_id(권장) 또는 topic.created_by 컬럼이 필요합니다.")

                room_opt = st.radio("방 관리", ["기존 방 선택", "새 방 만들기"])
                if room_opt == "기존 방 선택" and existing_rooms:
                    room_name = st.selectbox("토론/토의방 목록", existing_rooms)
                else:
                    new_room = st.text_input("새로 만들 방 이름 (예: 1학년 3반)")
                    new_title = st.text_input("주제 직접 입력 (예: 인공지능 윤리)")
                    new_mode = st.radio("진행 방식", ["⚔️ 찬반 토론", "💡 자유 토의"], horizontal=True)
                    new_pw = st.text_input("🔒 학생 입장용 암호 (비워두면 공개방)")
                    if st.button("새 방 개설하기", type="primary"):
                        room_ok, safe_new_room, room_error_code, room_error_message = validate_room_name(new_room, max_len=MAX_ROOM_NAME_LEN)
                        title_ok, safe_new_title, title_error_code, title_error_message = validate_opinion_content(new_title, max_len=MAX_TOPIC_LEN)
                        entry_ok, safe_new_pw, entry_error_code, entry_error_message = validate_entry_code(new_pw, max_len=MAX_ENTRY_CODE_LEN)
                        can_store_room_pw = topic_entry_code_column_available()
                        if not room_ok:
                            st.error(f"❌ {room_error_message} ({room_error_code})")
                        elif not title_ok:
                            st.error(f"❌ {title_error_message} ({title_error_code})")
                        elif not entry_ok:
                            st.error(f"❌ {entry_error_message} ({entry_error_code})")
                        elif safe_new_pw and not can_store_room_pw:
                            st.error("현재 DB 구조에서는 방 비밀번호 저장을 지원하지 않습니다.")
                        elif safe_new_room and safe_new_title:
                            res = upsert_topic_room(
                                supabase=supabase, room_name=safe_new_room, title=safe_new_title,
                                mode=new_mode, entry_code=safe_new_pw, created_by=teacher_id_for_scope,
                            )
                            if res is not None:
                                st.success(f"'{safe_new_room}' 방이 개설되었습니다! '기존 방 선택'을 눌러 입장하세요.")
                        room_name = ""
        else:
            st.session_state['teacher_auth'] = False
            st.session_state['admin_auth'] = False
            st.session_state['teacher_id'] = ""
            redirect_from_admin_page_if_needed()
            student_number = st.text_input("학번", key="student_number_input", placeholder="예: 1101")
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
            st.session_state['ai_result_text'] = ""
            if st.session_state['joined']:
                st.session_state['joined'] = False
                log_audit("room_switched_to_lobby", room_name=room_name, actor_name=student_name, role=user_role, previous_room=prev_room)
                st.rerun()

        if st.session_state['joined']:
            st.divider()
            if st.button("🚪 방 나가기 (대기실로)"):
                st.session_state['joined'] = False
                st.rerun()

    return {
        'user_role': user_role,
        'room_name': room_name,
        'teacher_auth': teacher_auth,
        'admin_auth': admin_auth,
        'student_name': student_name,
        'student_number': student_number,
    }
