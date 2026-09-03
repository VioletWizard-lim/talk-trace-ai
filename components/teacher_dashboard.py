import logging

import pandas as pd
import plotly.express as px
import streamlit as st

from db import ai_feedback_available, clear_session_attempts, comments_available, content_flags_available, debate_soft_delete_available, delete_opinion_change, destroy_room_data, fetch_all_opinion_changes, fetch_comments_for_room, fetch_debate_status, fetch_deleted_comments, fetch_deleted_messages, fetch_live_messages, fetch_session_attempts_by_room, fetch_unreviewed_flags_for_room, opinion_changes_available, permanently_delete_comment, permanently_delete_message, restore_comment, restore_opinion_message, room_soft_destroy_available, session_control_available, session_attempts_available, set_debate_status, stance_available
from utils import create_analysis_image
from components.opinion_change import _render_image_download, _build_student_depth_summary, _STANCE_OPTIONS, render_feedback_card
from wordcloud import build_word_frequencies, build_circular_wordcloud_html
from validators import with_fallback_author_role
from utils import log_audit, dashboard_busy_key, dashboard_pending_action_key
from config import DASHBOARD_FETCH_LIMIT, ROOM_DESTROY_ENABLED, UI_FONT_FAMILY
from components.teacher_hint import render_hint_section
from components.teacher_summary import render_summary_section, auto_generate_summary_report, auto_build_pdf_cache, run_manual_summary_generation
from components.depth_analysis import render_depth_analysis_section, auto_classify_all_opinions, run_manual_depth_generation
from components.moderation_review import render_moderation_review_section, auto_flag_room_content, maybe_auto_flag_periodically

logger = logging.getLogger("talk_trace_ai")


def _s(val, default=""):
    return default if (val is None or (isinstance(val, float) and pd.isna(val))) else str(val)


def _render_learning_analysis_section(supabase, room_name, act_type, current_topic, df_all):
    if not opinion_changes_available():
        return
    df_oc = fetch_all_opinion_changes(supabase, room_name)
    if df_oc.empty:
        return

    st.subheader("🔍 학생별 배움 분석")
    students = df_oc["student_name"].tolist()

    col_select, col_del_btn = st.columns([6, 1])
    with col_select:
        selected = st.selectbox("학생 선택", students, key="oc_student_select")
    with col_del_btn:
        st.write("")
        if st.button("🗑️ 삭제", key=f"del_btn_{selected}", use_container_width=True, help="이 학생의 배움 분석 기록을 삭제합니다."):
            st.session_state[f"confirm_del_{selected}"] = True

    if st.session_state.get(f"confirm_del_{selected}"):
        st.warning(f"**'{selected}'** 학생의 배움 분석 기록을 완전히 삭제합니다. 되돌릴 수 없습니다.")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("✅ 삭제 확인", type="primary", use_container_width=True, key=f"confirm_yes_{selected}"):
                delete_opinion_change(supabase, room_name, selected)
                st.session_state.pop(f"confirm_del_{selected}", None)
                st.toast(f"'{selected}' 학생 기록이 삭제되었습니다.", icon="🗑️")
                st.rerun()
        with col_no:
            if st.button("❌ 취소", use_container_width=True, key=f"confirm_no_{selected}"):
                st.session_state.pop(f"confirm_del_{selected}", None)
                st.rerun()

    row = df_oc[df_oc["student_name"] == selected].iloc[0]
    pre         = _s(row.get("pre_opinion"),  "(없음)")
    post        = _s(row.get("post_opinion"), "(없음)")
    ai          = _s(row.get("ai_analysis"),  "")
    ai_feedback = _s(row.get("ai_feedback"),  "")

    ip_raw = _s(row.get("ip_address"))
    student_ip = ip_raw.replace(".0.0.", ".X.X.") if ip_raw else ""
    session_uuid = _s(row.get("session_id"))
    if (not student_ip or not session_uuid) and not df_all.empty:
        student_msgs = df_all[df_all["student_name"] == selected]
        if not student_msgs.empty:
            if not student_ip and "ip_address" in df_all.columns:
                ip_val = _s(student_msgs.iloc[0].get("ip_address"))
                student_ip = ip_val.replace(".0.0.", ".X.X.") if ip_val else ""
            if not session_uuid and "session_id" in df_all.columns:
                session_uuid = _s(student_msgs.iloc[0].get("session_id"))
    id_parts = []
    if student_ip:
        id_parts.append(f"🌐 IP: `{student_ip}`")
    if session_uuid:
        # 같은 IP(NAT)라도 기기를 구분할 수 있도록 세션 UUID 앞 8자리만 표시
        id_parts.append(f"🔑 세션: `{session_uuid[:8]}`")
    if id_parts:
        st.caption(" · ".join(id_parts))

    if stance_available() and act_type == "토론":
        init_s = _s(row.get("initial_stance"))
        final_s = _s(row.get("final_stance"))
        if init_s or final_s:
            col_is, col_fs = st.columns(2)
            with col_is:
                st.caption("📌 토론 전 입장")
                st.info(init_s or "(미입력)")
            with col_fs:
                st.caption("🗳️ 토론 후 최종 입장")
                st.info(final_s or "(미입력)")

    col_pre, col_post = st.columns(2)
    with col_pre:
        st.caption("📌 토론 전 생각")
        st.info(pre)
    with col_post:
        st.caption("🔄 토론 후 생각")
        st.info(post)
    if ai_feedback and ai_feedback_available():
        st.caption("🌟 AI 피드백 카드")
        render_feedback_card(ai_feedback)

    if ai:
        depth_summary = _build_student_depth_summary(supabase, room_name, selected)
        if depth_summary:
            st.caption(f"📈 발언 깊이: {depth_summary}")
        st.caption("🤖 AI 배움 분석")
        st.markdown(ai.replace("\n", "\n\n"))
        _render_image_download(
            selected, current_topic, pre, post, ai,
            session_key=f"img_teacher_{room_name}_{selected}",
            btn_key="dl_analysis_teacher",
            depth_summary=depth_summary,
            ai_feedback=ai_feedback,
        )
    else:
        st.caption("AI 분석이 아직 없습니다.")


def _render_stance_section(supabase, room_name, act_type, current_topic, df_all):
    if not opinion_changes_available():
        return
    df_oc = fetch_all_opinion_changes(supabase, room_name)
    if df_oc.empty:
        return

    if stance_available():
        if act_type == "토론":
            st.subheader("📊 입장 변화 현황")
            col_d1, col_d2 = st.columns(2)
            for col, col_name, label in [
                (col_d1, "initial_stance", "토론 전 초기 입장"),
                (col_d2, "final_stance",   "토론 후 최종 입장"),
            ]:
                if col_name in df_oc.columns:
                    counts = (
                        df_oc[col_name]
                        .dropna()
                        .value_counts()
                        .reindex(_STANCE_OPTIONS, fill_value=0)
                        .reset_index()
                    )
                    counts.columns = ["입장", "인원"]
                    with col:
                        st.caption(label)
                        if counts["인원"].sum() > 0:
                            fig = px.pie(
                                counts, names="입장", values="인원",
                                hole=0.45,
                                color="입장",
                                color_discrete_map={
                                    "🔵 찬성": "#1558a0",
                                    "🔴 반대": "#d62728",
                                },
                            )
                            fig.update_layout(
                                margin=dict(t=10, b=10, l=10, r=10),
                                font={"family": UI_FONT_FAMILY},
                                showlegend=True,
                                legend=dict(orientation="h"),
                            )
                            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key=f"stance_chart_{col_name}_{room_name}")
                            # 입장별 학생 이름 목록
                            c_pro, c_con = st.columns(2)
                            with c_pro:
                                pros = df_oc[df_oc[col_name] == "🔵 찬성"]["student_name"].tolist()
                                st.markdown(f"**🔵 찬성 ({len(pros)}명)**")
                                st.write(", ".join(pros) if pros else "없음")
                            with c_con:
                                cons = df_oc[df_oc[col_name] == "🔴 반대"]["student_name"].tolist()
                                st.markdown(f"**🔴 반대 ({len(cons)}명)**")
                                st.write(", ".join(cons) if cons else "없음")
                        else:
                            st.info("아직 입력된 입장이 없습니다.")

            # 입장 변화 매트릭스 카드
            if "initial_stance" in df_oc.columns and "final_stance" in df_oc.columns:
                both_df = df_oc[df_oc["initial_stance"].notna() & df_oc["final_stance"].notna()]
                pro_keep_df  = both_df[(both_df["initial_stance"] == "🔵 찬성") & (both_df["final_stance"] == "🔵 찬성")]
                pro_to_con_df = both_df[(both_df["initial_stance"] == "🔵 찬성") & (both_df["final_stance"] == "🔴 반대")]
                con_to_pro_df = both_df[(both_df["initial_stance"] == "🔴 반대") & (both_df["final_stance"] == "🔵 찬성")]
                con_keep_df  = both_df[(both_df["initial_stance"] == "🔴 반대") & (both_df["final_stance"] == "🔴 반대")]

                st.markdown("**🔄 입장 변화 매트릭스**")
                st.caption("행: 토론 전 입장 / 열: 토론 후 입장")

                card_css = """
                <style>
                .matrix-card {
                    border-radius: 12px; padding: 14px 16px; margin: 4px 0;
                    font-size: 15px; line-height: 1.7;
                }
                .card-keep-pro  { background: #dbeafe; border-left: 5px solid #1558a0; }
                .card-keep-con  { background: #fee2e2; border-left: 5px solid #d62728; }
                .card-pro-to-con { background: #fef9c3; border-left: 5px solid #d97706; }
                .card-con-to-pro { background: #dcfce7; border-left: 5px solid #16a34a; }
                .card-count { font-size: 28px; font-weight: 800; }
                .card-names { color: #555; font-size: 13px; margin-top: 4px; }
                </style>
                """
                st.markdown(card_css, unsafe_allow_html=True)

                col_tl, col_tr = st.columns(2)
                col_bl, col_br = st.columns(2)

                def _names(df):
                    names = df["student_name"].tolist()
                    return ", ".join(names) if names else "없음"

                with col_tl:
                    st.markdown(
                        f'<div class="matrix-card card-keep-pro">'
                        f'🔵 찬성 → 🔵 찬성 유지<br>'
                        f'<span class="card-count">{len(pro_keep_df)}명</span><br>'
                        f'<span class="card-names">{_names(pro_keep_df)}</span>'
                        f'</div>', unsafe_allow_html=True
                    )
                with col_tr:
                    st.markdown(
                        f'<div class="matrix-card card-pro-to-con">'
                        f'🔵 찬성 → 🔴 반대 전환<br>'
                        f'<span class="card-count">{len(pro_to_con_df)}명</span><br>'
                        f'<span class="card-names">{_names(pro_to_con_df)}</span>'
                        f'</div>', unsafe_allow_html=True
                    )
                with col_bl:
                    st.markdown(
                        f'<div class="matrix-card card-con-to-pro">'
                        f'🔴 반대 → 🔵 찬성 전환<br>'
                        f'<span class="card-count">{len(con_to_pro_df)}명</span><br>'
                        f'<span class="card-names">{_names(con_to_pro_df)}</span>'
                        f'</div>', unsafe_allow_html=True
                    )
                with col_br:
                    st.markdown(
                        f'<div class="matrix-card card-keep-con">'
                        f'🔴 반대 → 🔴 반대 유지<br>'
                        f'<span class="card-count">{len(con_keep_df)}명</span><br>'
                        f'<span class="card-names">{_names(con_keep_df)}</span>'
                        f'</div>', unsafe_allow_html=True
                    )

        elif act_type == "토의":
            if "discussion_conclusion" in df_oc.columns:
                conclusion_rows = df_oc[df_oc["discussion_conclusion"].notna() & (df_oc["discussion_conclusion"].astype(str).str.strip() != "")]
                conclusions = conclusion_rows["discussion_conclusion"]
                if not conclusions.empty:
                    st.subheader("☁️ 결론 워드클라우드")
                    freq = build_word_frequencies(conclusions)
                    if freq:
                        wc_col, _ = st.columns([1, 1])
                        with wc_col:
                            st.markdown(build_circular_wordcloud_html(freq), unsafe_allow_html=True)
                    _submitted_names = conclusion_rows["student_name"].tolist()
                    st.caption(f"✅ 제출한 학생 ({len(_submitted_names)}명): {', '.join(_submitted_names)}")
                else:
                    st.info("아직 제출된 결론이 없습니다.")


def _render_debate_control(supabase, room_name, act_type, current_topic):
    """토론 진행 제어 — fragment로 분리해 무거운 대시보드 렌더링과 독립적으로 즉시 반응."""
    debate_status = fetch_debate_status(supabase, room_name)
    if debate_status == "ended":
        st.warning("🔴 **토론이 종료된 상태입니다.** 학생들은 '토론 후 생각 변화'를 작성 중입니다.")
        if st.button("▶️ 토론 재개", use_container_width=True):
            if set_debate_status(supabase, room_name, "active") is not None:
                fetch_debate_status.clear()
                st.toast("✅ 토론이 재개되었습니다.", icon="▶️")
                st.rerun(scope="app")
    else:
        st.success("🟢 **토론 진행 중입니다.**")
        if st.button("⏹️ 토론 종료 (학생 입력 마감)", use_container_width=True, type="primary"):
            if set_debate_status(supabase, room_name, "ended") is not None:
                fetch_debate_status.clear()
                st.toast("⏹️ 토론이 종료되었습니다. 학생들에게 생각 변화 입력창이 표시됩니다.", icon="✅")
                # 자동 생성(발언 깊이/요약 리포트)은 무거운 작업이라 바로 여기서
                # 실행하지 않고, 플래그만 세운 뒤 rerun한다. 그래야 탭 라디오가
                # "생성 중(비활성)" 상태로 먼저 화면에 반영된 다음에 무거운 작업이
                # 시작되어, 그 사이 다른 탭을 눌러 생성이 꼬이는 걸 막을 수 있다.
                st.session_state[dashboard_busy_key(room_name)] = True
                st.session_state[dashboard_pending_action_key(room_name)] = "auto_end"
                st.rerun(scope="app")

        if content_flags_available():
            if st.button("🚩 지금 유해 발언 검수 실행", use_container_width=True):
                with st.spinner("🤖 AI가 발언·답글을 검수하고 있습니다..."):
                    auto_flag_room_content(supabase, room_name)
                fetch_unreviewed_flags_for_room.clear()
                st.toast("검수를 완료했습니다. '삭제 보관소' 탭에서 확인하세요.", icon="🚩")
                st.rerun(scope="app")


def _render_presence_reset_section(supabase, room_name):
    st.markdown("**🔓 학번 접속 제한 해제**")
    st.caption(
        "학생이 학번을 여러 번 바꿔 입력해 입장이 막혔거나, 다른 기기 접속 경고가 "
        "잘못 뜨는 경우 해당 학번만 접속 기록을 초기화할 수 있습니다."
    )

    rows = fetch_session_attempts_by_room(supabase, room_name)
    by_session = {}
    for row in rows:
        by_session.setdefault(row["session_id"], set()).add(row["student_name"])
    flagged_numbers = sorted({num for nums in by_session.values() if len(nums) >= 3 for num in nums})
    if flagged_numbers:
        st.warning(
            f"⚠️ 같은 브라우저에서 여러 학번을 사용해 입장 제한에 걸릴 수 있는 학번: "
            f"**{', '.join(flagged_numbers)}**"
        )

    target_number = st.text_input(
        "초기화할 학번",
        key=f"presence_reset_number_{room_name}",
        placeholder="예: 10101",
    )
    if st.button("🧹 이 학번 접속 기록 초기화", key=f"presence_reset_btn_{room_name}", disabled=not target_number.strip()):
        clear_session_attempts(supabase, room_name, target_number.strip())
        st.toast(f"✅ '{target_number.strip()}' 학번의 접속 기록을 초기화했습니다.", icon="🧹")


def _render_participation_section(supabase, room_name, act_type):
    col_ptitle, col_pref = st.columns([7, 2])
    with col_ptitle:
        st.subheader("📊 학생 참여도 현황")
    with col_pref:
        if st.button("🔄 새로고침", key="refresh_participation", use_container_width=True):
            fetch_live_messages.clear()
            st.rerun()
    df = with_fallback_author_role(fetch_live_messages(supabase, room_name, DASHBOARD_FETCH_LIMIT))
    student_df = (
        df[
            (df['author_role'] == '학생') &
            ~df['student_name'].str.contains('익명|AI', na=False, regex=True)
        ].copy()
        if not df.empty else df
    )
    if not df.empty:
        if not student_df.empty:
            counts = student_df['student_name'].astype(str).value_counts().reset_index()
            counts.columns = ['학생 이름', '참여 횟수']
            counts['학생 이름'] = counts['학생 이름'] + " "
            fig = px.bar(counts, x='학생 이름', y='참여 횟수', text='참여 횟수', color='학생 이름')
            fig.update_xaxes(type='category', title="")
            fig.update_layout(yaxis_title="의견 수", dragmode=False, showlegend=False, font={"family": UI_FONT_FAMILY})
            st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False})
        else:
            st.info("실명 참여 데이터가 없습니다.")
    else:
        st.info(f"{act_type} 데이터가 없습니다.")


def _render_archive_section(supabase, room_name):
    render_moderation_review_section(supabase, room_name)
    st.divider()

    st.subheader("🗑️ 삭제 보관소")
    st.caption("실시간 보드에서 삭제된 발언이 여기 보관됩니다. 복구하거나 완전히 삭제할 수 있습니다.")

    deleted_df = fetch_deleted_messages(supabase, room_name)
    if deleted_df.empty:
        st.info("삭제된 발언이 없습니다.")
    else:
        _render_deleted_messages(supabase, deleted_df)

    if comments_available():
        st.divider()
        st.subheader("🗑️ 삭제된 답글 보관소")
        deleted_comments = fetch_deleted_comments(supabase, room_name)
        if not deleted_comments:
            st.info("삭제된 답글이 없습니다.")
        else:
            _render_deleted_comments(supabase, deleted_comments)


def _render_deleted_messages(supabase, deleted_df):
    for _, row in deleted_df.iterrows():
        msg_id = row["id"]
        deleted_at = _s(row.get("deleted_at"))
        deleted_by = _s(row.get("deleted_by"))
        meta_bits = [b for b in [f"삭제 시각: {deleted_at}" if deleted_at else "", f"삭제한 사람: {deleted_by}" if deleted_by else ""] if b]

        with st.container(border=True):
            st.markdown(f"**{row.get('student_name', '')}** — {row.get('content', '')}")
            if meta_bits:
                st.caption(" · ".join(meta_bits))

            col_restore, col_purge = st.columns(2)
            with col_restore:
                if st.button("↩️ 복구", key=f"archive_restore_{msg_id}", use_container_width=True):
                    if restore_opinion_message(supabase, msg_id) is not None:
                        fetch_live_messages.clear()
                        st.toast("발언을 복구했습니다.", icon="↩️")
                        st.rerun(scope="app")
            with col_purge:
                if st.button("❌ 완전 삭제", key=f"archive_purge_{msg_id}", use_container_width=True):
                    st.session_state[f"confirm_purge_{msg_id}"] = True

            if st.session_state.get(f"confirm_purge_{msg_id}"):
                st.warning("⚠️ 완전히 삭제하면 되돌릴 수 없습니다. 정말 삭제하시겠습니까?")
                col_yes, col_no = st.columns(2)
                with col_yes:
                    if st.button("✅ 완전 삭제 확인", key=f"confirm_purge_yes_{msg_id}", type="primary", use_container_width=True):
                        if permanently_delete_message(supabase, msg_id) is not None:
                            st.session_state.pop(f"confirm_purge_{msg_id}", None)
                            st.toast("완전히 삭제했습니다.", icon="🗑️")
                            st.rerun(scope="app")
                with col_no:
                    if st.button("취소", key=f"confirm_purge_no_{msg_id}", use_container_width=True):
                        st.session_state.pop(f"confirm_purge_{msg_id}", None)
                        st.rerun()


def _render_deleted_comments(supabase, deleted_comments):
    for c in deleted_comments:
        c_id = c["id"]
        deleted_at = _s(c.get("deleted_at"))
        deleted_by = _s(c.get("deleted_by"))
        meta_bits = [b for b in [f"삭제 시각: {deleted_at}" if deleted_at else "", f"삭제한 사람: {deleted_by}" if deleted_by else ""] if b]

        with st.container(border=True):
            st.markdown(f"`{c.get('comment_type', '')}` **{c.get('student_name', '')}** — {c.get('content', '')}")
            if meta_bits:
                st.caption(" · ".join(meta_bits))

            col_restore, col_purge = st.columns(2)
            with col_restore:
                if st.button("↩️ 복구", key=f"carchive_restore_{c_id}", use_container_width=True):
                    if restore_comment(supabase, c_id) is not None:
                        fetch_comments_for_room.clear()
                        st.toast("답글을 복구했습니다.", icon="↩️")
                        st.rerun(scope="app")
            with col_purge:
                if st.button("❌ 완전 삭제", key=f"carchive_purge_{c_id}", use_container_width=True):
                    st.session_state[f"confirm_cpurge_{c_id}"] = True

            if st.session_state.get(f"confirm_cpurge_{c_id}"):
                st.warning("⚠️ 완전히 삭제하면 되돌릴 수 없습니다. 정말 삭제하시겠습니까?")
                col_yes, col_no = st.columns(2)
                with col_yes:
                    if st.button("✅ 완전 삭제 확인", key=f"confirm_cpurge_yes_{c_id}", type="primary", use_container_width=True):
                        if permanently_delete_comment(supabase, c_id) is not None:
                            st.session_state.pop(f"confirm_cpurge_{c_id}", None)
                            st.toast("완전히 삭제했습니다.", icon="🗑️")
                            st.rerun(scope="app")
                with col_no:
                    if st.button("취소", key=f"confirm_cpurge_no_{c_id}", use_container_width=True):
                        st.session_state.pop(f"confirm_cpurge_{c_id}", None)
                        st.rerun()


_TAB_CONTROL = "🎛️ 토론 제어"
_TAB_PARTICIPATION = "📊 참여도"
_TAB_LEARNING = "🔍 배움 분석"
_TAB_STANCE = "📊 입장 변화"
_TAB_DEPTH = "📈 발언 깊이"
_TAB_SUMMARY = "📝 요약 리포트"
_TAB_ARCHIVE = "🗑️ 삭제 보관소"
_DASHBOARD_TAB_KEY = "teacher_dashboard_active_tab"
_DASHBOARD_TAB_CSS = f"""
    <style>
    div[class*="st-key-{_DASHBOARD_TAB_KEY}"] div[role="radiogroup"] {{
        gap: 4px;
        border-bottom: 2px solid #eee;
        padding-bottom: 4px;
    }}
    div[class*="st-key-{_DASHBOARD_TAB_KEY}"] label {{
        background: #f0f2f6;
        border-radius: 8px 8px 0 0;
        padding: 8px 14px !important;
        margin: 0 !important;
        transition: background 0.15s, color 0.15s;
    }}
    div[class*="st-key-{_DASHBOARD_TAB_KEY}"] label > div:first-child {{
        display: none !important;
    }}
    div[class*="st-key-{_DASHBOARD_TAB_KEY}"] label:has(input:checked) {{
        background: #ff4b4b;
    }}
    div[class*="st-key-{_DASHBOARD_TAB_KEY}"] label:has(input:checked) p {{
        color: white !important;
        font-weight: 700;
    }}
    </style>
"""


def render_teacher_dashboard(supabase, room_name, user_role, student_name, current_topic, current_mode, act_type):
    st.divider()
    col_dash_title, col_dash_refresh = st.columns([8, 2])
    with col_dash_title:
        st.header("👨‍🏫 교사 관리 대시보드")
    with col_dash_refresh:
        if st.button("🔄 대시보드 수동 새로고침", use_container_width=True):
            fetch_live_messages.clear()
            st.rerun()

    _render_dashboard_tabs(supabase, room_name, user_role, student_name, current_topic, act_type)


@st.fragment(run_every=10)
def _render_dashboard_tabs(supabase, room_name, user_role, student_name, current_topic, act_type):
    """탭 선택 + 내용 렌더링을 fragment로 분리해, 탭 전환이 앱 전체가 아니라
    이 부분만 다시 그리도록 함. 이렇게 하면 탭을 눌렀을 때 이전 탭 내용이
    잠깐 그대로 남아있다가 뒤늦게 바뀌는 지연/잔상 없이 즉시 전환된다."""
    df_all = with_fallback_author_role(fetch_live_messages(supabase, room_name, DASHBOARD_FETCH_LIMIT))
    _debate_status = fetch_debate_status(supabase, room_name) if session_control_available() else "ended"
    maybe_auto_flag_periodically(supabase, room_name, _debate_status)

    # 요약 리포트는 토론/토의 종료 전에는 탭 자체를 숨김
    tabs = [_TAB_CONTROL, _TAB_PARTICIPATION, _TAB_LEARNING, _TAB_STANCE, _TAB_DEPTH]
    if _debate_status == "ended":
        tabs.append(_TAB_SUMMARY)
    # 삭제 보관소는 DB에 소프트 삭제 컬럼이 마련된 경우에만 노출
    if debate_soft_delete_available():
        tabs.append(_TAB_ARCHIVE)

    # 탭 선택 상태를 session_state에 저장해, 다른 곳에서 발생하는 전체 rerun
    # 이후에도 선택된 탭이 첫 번째 탭으로 초기화되지 않고 유지되도록 함
    # (st.tabs는 이 방식의 상태 유지를 지원하지 않아 st.radio를 탭처럼 사용).
    if st.session_state.get(_DASHBOARD_TAB_KEY) not in tabs:
        st.session_state[_DASHBOARD_TAB_KEY] = tabs[0]
    st.markdown(_DASHBOARD_TAB_CSS, unsafe_allow_html=True)
    _is_busy = st.session_state.get(dashboard_busy_key(room_name), False)
    if _is_busy:
        st.caption("⏳ 자동 분석/리포트 생성이 끝날 때까지 탭 이동이 잠시 제한됩니다.")
    active_tab = st.radio(
        "대시보드 메뉴",
        tabs,
        key=_DASHBOARD_TAB_KEY,
        horizontal=True,
        label_visibility="collapsed",
        disabled=_is_busy,
    )
    st.divider()

    # 탭 전환을 막아야 하는 무거운 작업(자동/수동 생성)을 여기서 일괄 처리.
    # 버튼 클릭 시 바로 실행하지 않고 이 지점에서 실행하는 이유: 탭 라디오가
    # "생성 중(비활성)" 상태로 먼저 화면에 반영된 다음에 작업이 시작되도록 해서,
    # 그 사이 다른 탭을 눌러 생성이 꼬이는 걸 막기 위함.
    _pending_action = st.session_state.get(dashboard_pending_action_key(room_name))
    if _pending_action:
        st.session_state[dashboard_pending_action_key(room_name)] = None
        if _pending_action == "auto_end":
            with st.spinner("🤖 발언 깊이 분석과 요약 리포트를 자동으로 준비하고 있습니다..."):
                fetch_live_messages.clear()
                fresh_df_all = with_fallback_author_role(fetch_live_messages(supabase, room_name, DASHBOARD_FETCH_LIMIT))
                auto_classify_all_opinions(supabase, room_name)
                auto_flag_room_content(supabase, room_name)
                if auto_generate_summary_report(supabase, room_name, act_type, current_topic, fresh_df_all):
                    auto_build_pdf_cache(supabase, room_name, act_type, current_topic)
        elif _pending_action == "manual_summary":
            run_manual_summary_generation(supabase, room_name, act_type, current_topic, df_all)
        elif _pending_action == "manual_depth":
            run_manual_depth_generation(supabase, room_name)
        st.session_state[dashboard_busy_key(room_name)] = False
        st.rerun(scope="app")

    # 탭마다 고유한 key를 부여해, 탭 전환 시 이전 탭의 남은 요소가 완전히
    # 정리되기 전에 새 탭 내용이 그 아래 잠깐 겹쳐 보이는 문제를 방지.
    # (같은 컨테이너를 재사용하면 Streamlit이 이전 내용을 부분적으로만
    # 교체하다 늦게 지우는 경우가 있어, 탭별로 컨테이너 자체를 새로 만듦)
    with st.container(key=f"dashboard_tab_content_{active_tab}"):
        _render_tab_content(
            active_tab, supabase, room_name, user_role, student_name,
            current_topic, act_type, df_all, _debate_status,
        )


def _render_tab_content(active_tab, supabase, room_name, user_role, student_name, current_topic, act_type, df_all, _debate_status):
    if active_tab == _TAB_CONTROL:
        if session_control_available():
            st.subheader("🎛️ 토론 진행 제어")
            if session_attempts_available():
                col_control, col_presence = st.columns(2)
                with col_control:
                    _render_debate_control(supabase, room_name, act_type, current_topic)
                with col_presence:
                    _render_presence_reset_section(supabase, room_name)
            else:
                _render_debate_control(supabase, room_name, act_type, current_topic)
            st.divider()
        render_hint_section(supabase, room_name, user_role, student_name, current_topic, act_type, df_all)
        st.divider()
        st.subheader("🚨 위험 구역 (토론/토의방 삭제)")
        with st.expander("이 방 전체 삭제하기 (클릭 시 펼쳐짐)", expanded=False):
            if not ROOM_DESTROY_ENABLED:
                st.warning("운영 안전 모드로 방 삭제 기능이 비활성화되어 있습니다.")
            elif room_soft_destroy_available():
                st.warning(
                    f"⚠️ '{room_name}' 방을 숨김 처리하고, 모든 {act_type} 발언을 삭제 보관소로 이동합니다. "
                    "완전히 사라지는 게 아니라 '방 공개/숨김 관리'와 '삭제 보관소'에서 되돌릴 수 있습니다."
                )
                _confirm_text = st.text_input("삭제를 진행하려면 아래에 **확인했습니다** 를 입력하세요", key=f"destroy_confirm_{room_name}")
                if st.button(f"네, '{room_name}' 방을 삭제합니다", type="primary", use_container_width=True, disabled=_confirm_text != "확인했습니다"):
                    try:
                        if destroy_room_data(supabase, room_name, deleted_by=student_name) is None:
                            st.stop()
                        log_audit("room_destroyed", room_name=room_name, actor_name=student_name, role=user_role)
                        st.success("삭제되었습니다. (숨김 처리 + 발언 보관소 이동 — 되돌릴 수 있습니다)")
                        st.rerun()
                    except Exception as e:
                        st.error(f"삭제 중 오류 발생: {e}")
            else:
                st.error(f"🚨 경고: '{room_name}' 방의 모든 {act_type} 기록이 완전히 삭제됩니다. 되돌릴 수 없습니다.")
                _confirm_text = st.text_input("삭제를 진행하려면 아래에 **확인했습니다** 를 입력하세요", key=f"destroy_confirm_{room_name}")
                if st.button(f"네, '{room_name}' 방의 모든 데이터를 영구 삭제합니다", type="primary", use_container_width=True, disabled=_confirm_text != "확인했습니다"):
                    try:
                        if destroy_room_data(supabase, room_name) is None:
                            st.stop()
                        log_audit("room_destroyed", room_name=room_name, actor_name=student_name, role=user_role)
                        st.success("성공적으로 삭제되었습니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"삭제 중 오류 발생: {e}")

    elif active_tab == _TAB_PARTICIPATION:
        _render_participation_section(supabase, room_name, act_type)

    elif active_tab == _TAB_LEARNING:
        _render_learning_analysis_section(supabase, room_name, act_type, current_topic, df_all)

    elif active_tab == _TAB_STANCE:
        _render_stance_section(supabase, room_name, act_type, current_topic, df_all)

    elif active_tab == _TAB_DEPTH:
        render_depth_analysis_section(supabase, room_name, act_type, _debate_status == "ended")

    elif active_tab == _TAB_SUMMARY:
        render_summary_section(supabase, room_name, act_type, current_topic, df_all)

    elif active_tab == _TAB_ARCHIVE:
        _render_archive_section(supabase, room_name)
