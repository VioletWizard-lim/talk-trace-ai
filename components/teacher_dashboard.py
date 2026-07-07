import logging

import pandas as pd
import plotly.express as px
import streamlit as st

from db import ai_feedback_available, delete_opinion_change, destroy_room_data, fetch_all_opinion_changes, fetch_debate_status, fetch_live_messages, opinion_changes_available, session_control_available, set_debate_status, stance_available
from utils import create_analysis_image
from components.opinion_change import _render_image_download, _STANCE_OPTIONS, render_feedback_card
from wordcloud import build_word_frequencies, build_circular_wordcloud_html
from validators import with_fallback_author_role
from utils import log_audit
from config import DASHBOARD_FETCH_LIMIT, ROOM_DESTROY_ENABLED, UI_FONT_FAMILY
from components.teacher_hint import render_hint_section
from components.teacher_summary import render_summary_section
from components.depth_analysis import render_depth_analysis_section

logger = logging.getLogger("talk_trace_ai")


def _s(val, default=""):
    return default if (val is None or (isinstance(val, float) and pd.isna(val))) else str(val)


@st.fragment(run_every=20)
def _render_oc_section(supabase, room_name, act_type, current_topic, df_all):
    if not opinion_changes_available():
        return
    df_oc = fetch_all_opinion_changes(supabase, room_name)
    if df_oc.empty:
        return

    st.divider()
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
    if not student_ip and not df_all.empty and "ip_address" in df_all.columns:
        student_msgs = df_all[df_all["student_name"] == selected]
        if not student_msgs.empty:
            ip_val = _s(student_msgs.iloc[0].get("ip_address"))
            student_ip = ip_val.replace(".0.0.", ".X.X.") if ip_val else ""
    if student_ip:
        st.caption(f"🌐 IP: `{student_ip}`")

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
        st.caption("🤖 AI 배움 분석")
        st.markdown(ai.replace("\n", "\n\n"))
        _render_image_download(
            selected, current_topic, pre, post, ai,
            session_key=f"img_teacher_{room_name}_{selected}",
            btn_key="dl_analysis_teacher",
            ai_feedback=ai_feedback,
        )
    else:
        st.caption("AI 분석이 아직 없습니다.")

    if stance_available():
        st.divider()
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
                conclusions = df_oc["discussion_conclusion"].dropna()
                if not conclusions.empty:
                    st.subheader("☁️ 결론 워드클라우드")
                    freq = build_word_frequencies(conclusions)
                    if freq:
                        wc_col, _ = st.columns([1, 1])
                        with wc_col:
                            st.markdown(build_circular_wordcloud_html(freq), unsafe_allow_html=True)
                else:
                    st.info("아직 제출된 결론이 없습니다.")


@st.fragment
def _render_debate_control(supabase, room_name):
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
                st.rerun(scope="app")


@st.fragment(run_every=10)
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


def render_teacher_dashboard(supabase, room_name, user_role, student_name, current_topic, current_mode, act_type):
    st.divider()
    col_dash_title, col_dash_refresh = st.columns([8, 2])
    with col_dash_title:
        st.header("👨‍🏫 교사 관리 대시보드")
    with col_dash_refresh:
        if st.button("🔄 대시보드 수동 새로고침", use_container_width=True):
            fetch_live_messages.clear()
            st.rerun()

    # ── 1. 토론 진행 제어 (스크롤 없이 즉시 접근) ──
    if session_control_available():
        st.subheader("🎛️ 토론 진행 제어")
        _render_debate_control(supabase, room_name)
        st.divider()

    df_all = with_fallback_author_role(fetch_live_messages(supabase, room_name, DASHBOARD_FETCH_LIMIT))

    # ── 2. 수업 종료 및 전체 요약 리포트 (토론 종료 후에만 표시) ──
    _debate_status = fetch_debate_status(supabase, room_name) if session_control_available() else "ended"
    if _debate_status == "ended":
        render_summary_section(supabase, room_name, act_type, current_topic, df_all)
    elif session_control_available():
        st.info(f"💡 위의 **{act_type} 종료** 버튼을 누르면 수업 종료 및 전체 {act_type} 요약 리포트가 활성화됩니다.")

    # ── 3. AI 토의 촉진 ──
    st.divider()
    render_hint_section(supabase, room_name, user_role, student_name, current_topic, act_type, df_all)

    # ── 4. 학생 참여도 현황 (10초마다 자동 갱신) ──
    st.divider()
    _render_participation_section(supabase, room_name, act_type)

    _render_oc_section(supabase, room_name, act_type, current_topic, df_all)
    render_depth_analysis_section(supabase, room_name, act_type)

    st.divider()
    st.subheader("🚨 위험 구역 (방 폭파)")
    with st.expander("이 방 전체 삭제하기 (클릭 시 펼쳐짐)", expanded=False):
        if not ROOM_DESTROY_ENABLED:
            st.warning("운영 안전 모드로 방 폭파 기능이 비활성화되어 있습니다.")
        else:
            st.error(f"🚨 경고: '{room_name}' 방의 모든 {act_type} 기록이 완전히 삭제됩니다.")
            _confirm_text = st.text_input("삭제를 진행하려면 아래에 **확인했습니다** 를 입력하세요", key=f"destroy_confirm_{room_name}")
            if st.button(f"네, '{room_name}' 방의 모든 데이터를 영구 삭제합니다", type="primary", use_container_width=True, disabled=_confirm_text != "확인했습니다"):
                try:
                    if destroy_room_data(supabase, room_name) is None:
                        st.stop()
                    log_audit("room_destroyed", room_name=room_name, actor_name=student_name, role=user_role)
                    st.success("성공적으로 파괴되었습니다.")
                    st.rerun()
                except Exception as e:
                    st.error(f"삭제 중 오류 발생: {e}")
