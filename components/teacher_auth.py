import streamlit as st

from auth import _is_hashed, _verify_password
from db import (
    fetch_teacher_account,
    request_teacher_account,
    upgrade_teacher_password,
)
from validators import validate_teacher_credential
from utils import to_bool_flag


def _reset_auth_state():
    st.session_state['teacher_auth'] = False
    st.session_state['admin_auth'] = False
    st.session_state['teacher_id'] = ""


def _redirect_from_admin_if_needed():
    if st.session_state.get('page') == "admin_approval" and not st.session_state.get('admin_auth', False):
        st.session_state['page'] = "lobby"


def _handle_login(supabase, teacher_id_input, teacher_pw_input):
    id_ok, safe_teacher_id, id_error_code, id_error_message = validate_teacher_credential(
        teacher_id_input, field_name="교사 ID", max_len=60
    )
    pw_ok, safe_pw, pw_error_code, pw_error_message = validate_teacher_credential(
        teacher_pw_input, field_name="교사 PW", max_len=60
    )
    if not id_ok:
        st.error(f"❌ {id_error_message}")
        st.stop()
    if not pw_ok:
        st.error(f"❌ {pw_error_message}")
        st.stop()

    account = fetch_teacher_account(supabase, safe_teacher_id)
    if isinstance(account, dict) and account.get("_query_failed"):
        _reset_auth_state()
        _redirect_from_admin_if_needed()
        st.error("🚨 교사 계정 조회에 실패했습니다. Supabase RLS 정책/권한 및 DB 연결 상태를 확인해 주세요.")
    elif not account:
        _reset_auth_state()
        _redirect_from_admin_if_needed()
        st.error("🚨 등록되지 않은 교사 ID입니다.")
    elif not _verify_password(safe_pw, account.get("teacher_pw", "")):
        _reset_auth_state()
        _redirect_from_admin_if_needed()
        st.error("❌ 비밀번호가 일치하지 않습니다.")
    elif not account.get("is_approved"):
        _reset_auth_state()
        _redirect_from_admin_if_needed()
        st.warning("⏳ 최고관리자 승인 후 로그인할 수 있습니다.")
    else:
        st.session_state['teacher_auth'] = True
        st.session_state['admin_auth'] = to_bool_flag(account.get("is_admin", False))
        st.session_state['teacher_id'] = safe_teacher_id
        _redirect_from_admin_if_needed()
        if not _is_hashed(account.get("teacher_pw", "")):
            upgrade_teacher_password(supabase, account["id"], safe_pw)
        if st.session_state['admin_auth']:
            st.session_state['page'] = "admin_approval"
            st.toast("✅ 관리자 계정 로그인 성공", icon="✅")
            st.rerun()
        else:
            st.toast("✅ 교사 로그인 성공", icon="✅")
            st.rerun()


def _render_signup(supabase):
    req_teacher_id = st.text_input("신청할 교사 ID", key="req_teacher_id")
    req_teacher_pw = st.text_input("신청할 교사 PW", type="password", key="req_teacher_pw")
    if st.button("교사 계정 신청", type="primary", use_container_width=True):
        id_ok, safe_id, id_error_code, id_error_message = validate_teacher_credential(
            req_teacher_id, field_name="교사 ID", max_len=60
        )
        pw_ok, safe_pw, pw_error_code, pw_error_message = validate_teacher_credential(
            req_teacher_pw, field_name="교사 PW", max_len=60
        )
        if not id_ok:
            st.error(f"❌ {id_error_message}")
        elif not pw_ok:
            st.error(f"❌ {pw_error_message}")
        elif fetch_teacher_account(supabase, safe_id):
            st.warning("이미 존재하는 ID입니다. 다른 ID를 사용해 주세요.")
        else:
            req_res = request_teacher_account(supabase, safe_id, safe_pw)
            if req_res is not None:
                st.success("신청 완료! 최고관리자 승인 후 로그인할 수 있습니다.")


def render_teacher_auth(supabase) -> None:
    """교사 로그인/회원가입/로그아웃 UI를 렌더링하고 session_state를 업데이트합니다."""
    already_logged_in = st.session_state.get('teacher_auth', False)

    if not already_logged_in:
        auth_mode = st.radio("교사 계정", ["로그인", "ID/PW 신청"], horizontal=True)
    else:
        auth_mode = "로그인"

    if auth_mode == "로그인" and not already_logged_in:
        with st.form("teacher_login_form"):
            teacher_id_input = st.text_input("교사 ID", key="teacher_id_input")
            teacher_pw_input = st.text_input("교사 PW", type="password", key="teacher_pw_input")
            login_submitted = st.form_submit_button("교사 로그인", use_container_width=True)
        if login_submitted:
            _handle_login(supabase, teacher_id_input, teacher_pw_input)
    elif auth_mode == "ID/PW 신청":
        _render_signup(supabase)

    if st.session_state.get('teacher_auth', False):
        teacher_id = st.session_state.get("teacher_id", "")
        st.caption(f"🔐 {teacher_id} 로그인 중")
        if st.button("🚪 로그아웃", use_container_width=True):
            _reset_auth_state()
            st.session_state['teacher_id_input'] = ""
            st.session_state['teacher_pw_input'] = ""
            st.session_state['joined'] = False
            st.session_state['page'] = "lobby"
            st.session_state.pop('_admin_redirected', None)
            st.rerun()
        st.divider()
