import streamlit as st
from db import fetch_pending_teacher_accounts, approve_teacher_account, reject_teacher_account
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
        c_id, c_date, c_approve, c_reject = st.columns([3, 2, 1, 1])
        with c_id:
            st.write(f"ID: {pending_teacher_id}")
        with c_date:
            st.caption(f"신청 시각: {format_kst_datetime(requested_at)}")
        with c_approve:
            if st.button("✅ 승인", key=f"approve_{acc_id}", use_container_width=True):
                res = approve_teacher_account(supabase, acc_id, get_kst_now_str())
                if res is not None:
                    st.success(f"{pending_teacher_id} 계정을 승인했습니다.")
                    st.rerun()
        with c_reject:
            if st.button("❌ 거절", key=f"reject_{acc_id}", use_container_width=True, type="secondary"):
                res = reject_teacher_account(supabase, acc_id)
                if res is not None:
                    st.warning(f"{pending_teacher_id} 계정 신청을 거절했습니다.")
                    st.rerun()


def render_admin_page(supabase, user_role, teacher_auth, admin_auth):
    if not (user_role == "교사" and teacher_auth and admin_auth):
        st.session_state['page'] = "lobby"
        st.toast("관리자 페이지에서 나와 대기실로 이동했습니다.", icon="ℹ️")
        st.rerun()
    col_title, col_btn1, col_btn2 = st.columns([4, 1, 1])
    with col_title:
        st.title("🛠️ 관리자 ID 요청 수락 페이지")
    with col_btn1:
        if st.button("📝 ID 요청 수락", use_container_width=True):
            st.session_state['page'] = "admin_approval"
            st.rerun()
    with col_btn2:
        if st.button("🚪 말자취 AI 대기실", use_container_width=True):
            st.session_state['page'] = "lobby"
            st.rerun()
    render_admin_approval_panel(supabase)
    st.stop()
