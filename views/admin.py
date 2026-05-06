import streamlit as st
from db import fetch_pending_teacher_accounts, approve_teacher_account
from utils import format_kst_datetime, get_kst_now_str


def render_admin_approval_panel(supabase):
    st.subheader("📝 교사 계정 승인")
    pending_accounts = fetch_pending_teacher_accounts(supabase)
    if not pending_accounts:
        st.info("승인 대기 중인 교사 계정이 없습니다.")
        return
    for pending in pending_accounts:
        acc_id = pending.get("id")
        pending_teacher_id = pending.get("teacher_id", "")
        requested_at = pending.get("requested_at", "") or "-"
        c_left, c_right = st.columns([3, 2])
        with c_left:
            st.write(f"ID: {pending_teacher_id}")
        with c_right:
            st.caption(f"신청 시각: {format_kst_datetime(requested_at)}")
            if st.button("승인", key=f"approve_{acc_id}"):
                res = approve_teacher_account(supabase, acc_id, get_kst_now_str())
                if res is not None:
                    st.success(f"{pending_teacher_id} 계정을 승인했습니다.")
                    st.rerun()


def render_admin_page(supabase, user_role, teacher_auth, admin_auth):
    if not (user_role == "교사" and teacher_auth and admin_auth):
        st.session_state['page'] = "lobby"
        st.toast("관리자 페이지에서 나와 대기실로 이동했습니다.", icon="ℹ️")
        st.rerun()
    st.title("🛠️ 관리자 ID 요청 수락 페이지")
    render_admin_approval_panel(supabase)
    st.stop()
