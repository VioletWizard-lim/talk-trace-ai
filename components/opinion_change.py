import re
import pandas as pd
import streamlit as st

from config import AI_MODEL_NAME, LIVE_BOARD_FETCH_LIMIT
from utils import anonymize_ip, create_analysis_image, get_client_ip
from db import (
    ai_feedback_available,
    fetch_live_messages,
    fetch_opinion_change,
    opinion_changes_available,
    save_opinion_analysis,
    save_opinion_feedback,
    stance_available,
    upsert_post_opinion,
    upsert_pre_opinion,
)
from env import get_secret
from services.ai import build_feedback_prompt, build_opinion_change_prompt, generate_ai_response


_STANCE_OPTIONS = ["🔵 찬성", "🔴 반대"]


def render_feedback_card(ai_feedback: str) -> None:
    """잘한 점 / 발전할 점 피드백 카드를 렌더링합니다."""
    if not ai_feedback:
        return

    well_text = ""
    grow_text = ""

    # 1차: 정규식으로 섹션 파싱
    well_match = re.search(
        r'잘한\s*점\s*[^\n:：]*[:：]?\s*(.*?)(?=\n\s*\n?\s*[✅🌱]?\s*발전할\s*점|$)',
        ai_feedback, re.DOTALL
    )
    grow_match = re.search(
        r'발전할\s*점\s*[^\n:：]*[:：]?\s*(.*?)$',
        ai_feedback, re.DOTALL
    )

    if well_match:
        well_text = well_match.group(1).strip()
    if grow_match:
        grow_text = grow_match.group(1).strip()

    # 2차: 정규식 실패 시 줄 수 기준으로 절반씩 분할 시도
    if not well_text and not grow_text:
        lines = [l for l in ai_feedback.strip().splitlines() if l.strip()]
        if len(lines) >= 2:
            mid = len(lines) // 2
            well_text = "\n".join(lines[:mid])
            grow_text = "\n".join(lines[mid:])

    col_well, col_grow = st.columns(2)
    if well_text or grow_text:
        with col_well:
            st.success(f"**✅ 잘한 점**\n\n{well_text}" if well_text else "**✅ 잘한 점**\n\n(내용 없음)")
        with col_grow:
            st.warning(f"**🌱 발전할 점**\n\n{grow_text}" if grow_text else "**🌱 발전할 점**\n\n(내용 없음)")
    else:
        # 최종 fallback: 레이블과 함께 전체 내용 표시
        st.markdown("**🌟 AI 피드백**")
        st.markdown(ai_feedback)


@st.fragment
def render_pre_opinion_form(supabase, room_name, student_name, current_topic, act_type="토론"):
    """토론 전 생각 입력 폼. 제출 완료 시 전체 앱 재실행."""
    st.info(f"💬 **{'토론' if act_type == '토론' else '토의'} 전 내 생각 먼저 기록하기**\n\n'{current_topic}' 주제에 대한 나의 생각을 적어주세요. 제출 후 {'토론' if act_type == '토론' else '토의'}에 참여할 수 있습니다.")
    st.caption("📝 이 영역은 토론 전 본인의 생각을 적는 공간입니다. 솔직하게 현재 생각을 기록해 주세요.")

    initial_stance = None
    if act_type == "토론" and stance_available():
        initial_stance = st.radio(
            "📌 토론 전 나의 초기 입장",
            _STANCE_OPTIONS,
            horizontal=True,
            key="pre_stance_radio",
        )

    pre_input = st.text_area(
        "이 주제에 대한 내 생각은?",
        height=100,
        max_chars=500,
        placeholder="주제에 대한 나의 현재 생각, 입장, 이유를 자유롭게 써보세요.",
    )
    st.caption('⚠️ 제출 후에는 수정이 불가능합니다. 확인하려면 아래에 **"제출"** 을 입력하세요.')
    confirm_text = st.text_input(
        "확인 입력",
        placeholder='제출',
        label_visibility="collapsed",
        key="pre_opinion_confirm_text",
    )
    confirmed = confirm_text.strip() == "제출"
    if st.button("✅ 생각 제출 후 토론 참여", use_container_width=True, type="primary", disabled=not confirmed):
        if not pre_input.strip():
            st.warning("생각을 입력해 주세요.")
            return
        raw_ip = get_client_ip()
        anon_ip = anonymize_ip(raw_ip)
        res = upsert_pre_opinion(supabase, room_name, student_name, pre_input.strip(), initial_stance=initial_stance, ip_address=anon_ip)
        if res is not None:
            st.toast("✅ 내 생각이 기록되었습니다. 이제 토론에 참여할 수 있습니다!", icon="🎉")
            st.rerun(scope="app")
        else:
            st.error("저장에 실패했습니다. 다시 시도해 주세요.")


@st.fragment
def render_post_opinion_section(supabase, room_name, student_name, act_type, current_topic):
    """토론 종료 후 생각 변화 입력 및 AI 분석 섹션."""
    if not opinion_changes_available():
        return

    row = fetch_opinion_change(supabase, room_name, student_name)
    pre_opinion  = (row or {}).get("pre_opinion")  or ""
    post_opinion = (row or {}).get("post_opinion") or ""
    ai_analysis  = (row or {}).get("ai_analysis")  or ""

    st.subheader("🔄 토론 후 생각 변화 기록")

    if pre_opinion:
        st.caption(f"📌 **토론 전 내 생각:** {pre_opinion}")
    else:
        st.caption("📌 토론 전 생각 기록 없음")

    if not post_opinion:
        end_label = "토론" if act_type == "토론" else "토의"
        end_subj  = "토론이" if act_type == "토론" else "토의가"
        st.info(f"{end_subj} 종료되었습니다. {end_label} 후 생각이 어떻게 바뀌었는지 기록해 주세요.")

        final_stance = None
        discussion_conclusion = None

        if act_type == "토론" and stance_available():
            initial_stance_val = (row or {}).get("initial_stance") or ""
            if initial_stance_val:
                st.caption(f"📌 **토론 전 나의 입장:** {initial_stance_val}")
            final_stance = st.radio(
                "🗳️ 토론 후 최종 입장",
                _STANCE_OPTIONS,
                horizontal=True,
                key="post_stance_radio",
            )

        if act_type == "토의" and stance_available():
            discussion_conclusion = st.text_input(
                "💡 가장 중요한 결론은?",
                max_chars=200,
                placeholder="이번 토의에서 얻은 가장 중요한 결론을 한 줄로 써보세요.",
            )

        post_input = st.text_area(
            "토론 후 생각 변화",
            height=100,
            max_chars=500,
            placeholder="생각이 바뀌었다면 어떻게, 왜 바뀌었는지 — 바뀌지 않았다면 그 이유를 써보세요.",
            label_visibility="collapsed",
        )
        st.caption('⚠️ 제출 후에는 수정이 불가능합니다. 확인하려면 아래에 **"제출"** 을 입력하세요.')
        post_confirm_text = st.text_input(
            "확인 입력",
            placeholder='제출',
            label_visibility="collapsed",
            key="post_opinion_confirm_text",
        )
        post_confirmed = post_confirm_text.strip() == "제출"
        if st.button("✅ 생각 변화 제출", use_container_width=True, type="primary", disabled=not post_confirmed):
            if not post_input.strip():
                st.warning("생각을 입력해 주세요.")
                return
            res = upsert_post_opinion(
                supabase, room_name, student_name, post_input.strip(),
                final_stance=final_stance,
                discussion_conclusion=discussion_conclusion.strip() if discussion_conclusion else None,
            )
            if res is not None:
                # 제출 즉시 저장 확인 후 rerun — AI 분석은 다음 렌더에서 실행
                st.session_state['_run_analysis_now'] = True
                st.toast("✅ 제출 완료! AI가 분석 중입니다...", icon="🎉")
                st.rerun(scope="app")
            else:
                st.error("저장에 실패했습니다. 다시 시도해 주세요.")
    else:
        # 직전 제출로 인한 AI 분석 자동 실행 (제출과 분리하여 UX 지연 제거)
        if st.session_state.pop('_run_analysis_now', False) and not (row or {}).get("ai_analysis"):
            _trigger_analysis(supabase, room_name, student_name, act_type, current_topic, pre_opinion, post_opinion)
            st.rerun()

        final_stance_val = (row or {}).get("final_stance") or ""
        discussion_conclusion_val = (row or {}).get("discussion_conclusion") or ""
        ai_feedback = (row or {}).get("ai_feedback") or ""
        if act_type == "토론" and final_stance_val:
            st.success(f"✅ **최종 입장:** {final_stance_val}")
        if act_type == "토의" and discussion_conclusion_val:
            st.success(f"✅ **나의 결론:** {discussion_conclusion_val}")
        st.success(f"✅ **토론 후 내 생각:** {post_opinion}")
        st.divider()

        # AI 피드백 카드
        if ai_feedback and ai_feedback_available():
            st.markdown("### 🌟 나의 AI 피드백 카드")
            render_feedback_card(ai_feedback)
            st.divider()
        elif ai_feedback_available():
            if st.button("🌟 AI 피드백 카드 받기", use_container_width=True):
                if _trigger_feedback_only(supabase, room_name, student_name, act_type, current_topic):
                    st.rerun()

        if ai_analysis:
            st.info("🤖 **AI 배움 분석**")
            st.markdown(ai_analysis.replace("\n", "\n\n"))
            _render_image_download(
                student_name, current_topic, pre_opinion, post_opinion, ai_analysis,
                session_key=f"img_{room_name}_{student_name}",
                btn_key="dl_analysis_student",
                ai_feedback=ai_feedback,
            )
        else:
            if st.button("🤖 AI 배움 분석 받기", use_container_width=True):
                _trigger_analysis(supabase, room_name, student_name, act_type, current_topic, pre_opinion, post_opinion)
                st.rerun()


def _render_image_download(student_name, topic, pre_opinion, post_opinion, ai_analysis,
                           session_key, btn_key, ai_feedback=""):
    """이미지를 base64 데이터 URI 링크로 렌더링 — rerun 없이 즉시 다운로드."""
    import base64
    cache_key = f"{session_key}_{len(ai_analysis)}_{len(ai_feedback)}_b64"
    if cache_key not in st.session_state:
        try:
            img_bytes = create_analysis_image(
                student_name, topic, pre_opinion, post_opinion, ai_analysis, ai_feedback
            )
            st.session_state[cache_key] = base64.b64encode(img_bytes).decode()
        except Exception:
            st.session_state[cache_key] = None

    b64 = st.session_state.get(cache_key)
    if b64:
        filename = f"배움분석_{student_name}.png"
        st.markdown(
            f'<a href="data:image/png;base64,{b64}" download="{filename}" '
            f'style="display:block;width:100%;padding:0.45rem 0.9rem;'
            f'background:#1558a0;color:#fff;border-radius:0.5rem;'
            f'text-align:center;text-decoration:none;font-size:1rem;font-weight:600;">'
            f'🖼️ 분석 결과 이미지로 저장</a>',
            unsafe_allow_html=True,
        )


_FEEDBACK_FALLBACK = "발언 기록이 부족하여 분석이 어렵습니다."


def _get_debate_history(supabase, room_name, student_name):
    """학생 발언 기록을 문자열로 반환. 없으면 None."""
    df_all = fetch_live_messages(supabase, room_name, LIVE_BOARD_FETCH_LIMIT)
    if df_all.empty:
        return None
    student_df = df_all[df_all["student_name"] == student_name]
    if student_df.empty:
        return None
    return "\n".join(f"- [{row['sentiment']}] {row['content']}" for _, row in student_df.iterrows())


def _trigger_feedback_only(supabase, room_name, student_name, act_type, current_topic) -> bool:
    """피드백 카드만 단독 생성. 성공 시 True, 실패 시 False 반환."""
    if not ai_feedback_available():
        return False
    debate_history = _get_debate_history(supabase, room_name, student_name)
    if not debate_history:
        st.warning("⚠️ 토론 발언 기록이 없어 피드백을 생성할 수 없습니다. 토론에서 의견을 먼저 제출해 주세요.")
        return False
    api_key = get_secret("GEMINI_API_KEY", "")
    with st.spinner("🤖 AI가 피드백을 작성하고 있습니다..."):
        feedback_text = generate_ai_response(
            build_feedback_prompt(act_type, current_topic, student_name, debate_history),
            model_name=AI_MODEL_NAME,
            api_key=api_key,
            log_message="AI 피드백 카드 생성 실패",
            room_name=room_name,
            student=student_name,
        )
    if feedback_text and _FEEDBACK_FALLBACK not in feedback_text:
        save_opinion_feedback(supabase, room_name, student_name, feedback_text)
        st.toast("✅ 피드백 카드 생성 완료!", icon="🌟")
        return True
    else:
        st.warning("⚠️ 발언 기록이 부족하여 피드백을 생성할 수 없습니다.")
        return False


def _trigger_analysis(supabase, room_name, student_name, act_type, current_topic, pre_opinion, post_opinion):
    debate_history = _get_debate_history(supabase, room_name, student_name)
    has_speeches = debate_history is not None
    if not has_speeches:
        debate_history = "(토론 발언 기록 없음)"

    api_key = get_secret("GEMINI_API_KEY", "")

    with st.spinner("🤖 AI가 배움의 변화를 분석하고 있습니다..."):
        # 배움 분석
        prompt = build_opinion_change_prompt(
            act_type, current_topic, student_name, pre_opinion, post_opinion, debate_history
        )
        res_text = generate_ai_response(
            prompt,
            model_name=AI_MODEL_NAME,
            api_key=api_key,
            log_message="AI 생각 변화 분석 실패",
            room_name=room_name,
            student=student_name,
        )
        if res_text:
            save_opinion_analysis(supabase, room_name, student_name, res_text)
            cache_key = f"img_{room_name}_{student_name}_bytes"
            st.session_state.pop(cache_key, None)

        # AI 피드백 카드 (발언이 있을 때만 생성)
        if ai_feedback_available() and has_speeches:
            feedback_prompt = build_feedback_prompt(act_type, current_topic, student_name, debate_history)
            feedback_text = generate_ai_response(
                feedback_prompt,
                model_name=AI_MODEL_NAME,
                api_key=api_key,
                log_message="AI 피드백 카드 생성 실패",
                room_name=room_name,
                student=student_name,
            )
            # fallback 메시지는 저장하지 않음
            if feedback_text and _FEEDBACK_FALLBACK not in feedback_text:
                save_opinion_feedback(supabase, room_name, student_name, feedback_text)

        if res_text:
            st.toast("✅ AI 분석 완료!", icon="🎉")
        else:
            st.toast("🚨 AI 분석에 실패했습니다.", icon="❌")
