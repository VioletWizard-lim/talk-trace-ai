import streamlit as st

from config import AI_MODEL_NAME, LIVE_BOARD_FETCH_LIMIT
from db import (
    fetch_debate_status,
    fetch_live_messages,
    fetch_opinion_change,
    opinion_changes_available,
    save_opinion_analysis,
    upsert_post_opinion,
    upsert_pre_opinion,
)
from env import get_secret
from services.ai import build_opinion_change_prompt, generate_ai_response


def render_pre_opinion_form(supabase, room_name, student_name, current_topic):
    """토론 전 생각 입력 폼. 제출 완료 시 전체 앱 재실행."""
    st.info(f"💬 **토론 전 내 생각 먼저 기록하기**\n\n'{current_topic}' 주제에 대한 나의 생각을 적어주세요. 제출 후 토론에 참여할 수 있습니다.")
    pre_input = st.text_area(
        "이 주제에 대한 내 생각은?",
        height=100,
        max_chars=500,
        placeholder="주제에 대한 나의 현재 생각, 입장, 이유를 자유롭게 써보세요.",
    )
    if st.button("✅ 생각 제출 후 토론 참여", use_container_width=True, type="primary"):
        if not pre_input.strip():
            st.warning("생각을 입력해 주세요.")
            return
        res = upsert_pre_opinion(supabase, room_name, student_name, pre_input.strip())
        if res is not None:
            st.toast("✅ 내 생각이 기록되었습니다. 이제 토론에 참여할 수 있습니다!", icon="🎉")
            st.rerun()
        else:
            st.error("저장에 실패했습니다. 다시 시도해 주세요.")


def render_post_opinion_section(supabase, room_name, student_name, act_type, current_topic):
    """토론 종료 후 생각 변화 입력 및 AI 분석 섹션."""
    if not opinion_changes_available():
        return

    row = fetch_opinion_change(supabase, room_name, student_name)
    pre_opinion = (row or {}).get("pre_opinion") or ""
    post_opinion = (row or {}).get("post_opinion") or ""
    ai_analysis = (row or {}).get("ai_analysis") or ""

    st.subheader("🔄 토론 후 생각 변화 기록")

    if pre_opinion:
        st.caption(f"📌 **토론 전 내 생각:** {pre_opinion}")
    else:
        st.caption("📌 토론 전 생각 기록 없음")

    if not post_opinion:
        st.info("토론이 종료되었습니다. 토론 후 생각이 어떻게 바뀌었는지 기록해 주세요.")
        post_input = st.text_area(
            "토론 후 생각 변화",
            height=100,
            max_chars=500,
            placeholder="생각이 바뀌었다면 어떻게, 왜 바뀌었는지 — 바뀌지 않았다면 그 이유를 써보세요.",
            label_visibility="collapsed",
        )
        if st.button("✅ 생각 변화 제출", use_container_width=True, type="primary"):
            if not post_input.strip():
                st.warning("생각을 입력해 주세요.")
                return
            res = upsert_post_opinion(supabase, room_name, student_name, post_input.strip())
            if res is not None:
                _trigger_analysis(supabase, room_name, student_name, act_type, current_topic, pre_opinion, post_input.strip())
                st.rerun()
            else:
                st.error("저장에 실패했습니다. 다시 시도해 주세요.")
    else:
        st.success(f"✅ **토론 후 내 생각:** {post_opinion}")
        st.divider()
        if ai_analysis:
            st.info("🤖 **AI 배움 분석**")
            st.markdown(ai_analysis.replace("\n", "\n\n"))
        else:
            if st.button("🤖 AI 배움 분석 받기", use_container_width=True):
                _trigger_analysis(supabase, room_name, student_name, act_type, current_topic, pre_opinion, post_opinion)
                st.rerun()


def _trigger_analysis(supabase, room_name, student_name, act_type, current_topic, pre_opinion, post_opinion):
    df_all = fetch_live_messages(supabase, room_name, LIVE_BOARD_FETCH_LIMIT)
    if not df_all.empty:
        student_df = df_all[df_all["student_name"] == student_name]
        debate_history = "\n".join(
            f"- [{row['sentiment']}] {row['content']}" for _, row in student_df.iterrows()
        )
    else:
        debate_history = "(토론 발언 기록 없음)"

    with st.spinner("🤖 AI가 배움의 변화를 분석하고 있습니다..."):
        prompt = build_opinion_change_prompt(
            act_type, current_topic, student_name, pre_opinion, post_opinion, debate_history
        )
        res_text = generate_ai_response(
            prompt,
            model_name=AI_MODEL_NAME,
            api_key=get_secret("GEMINI_API_KEY", ""),
            log_message="AI 생각 변화 분석 실패",
            room_name=room_name,
            student=student_name,
        )
        if res_text:
            save_opinion_analysis(supabase, room_name, student_name, res_text)
            st.toast("✅ AI 분석 완료!", icon="🎉")
        else:
            st.toast("🚨 AI 분석에 실패했습니다.", icon="❌")
