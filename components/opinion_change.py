import streamlit as st

from config import AI_MODEL_NAME, LIVE_BOARD_FETCH_LIMIT
from utils import create_analysis_image
from db import (
    fetch_live_messages,
    fetch_opinion_change,
    opinion_changes_available,
    save_opinion_analysis,
    stance_available,
    upsert_post_opinion,
    upsert_pre_opinion,
)
from env import get_secret
from services.ai import build_opinion_change_prompt, generate_ai_response


_STANCE_OPTIONS = ["🔵 찬성", "🔴 반대", "⚪ 중립"]


def render_pre_opinion_form(supabase, room_name, student_name, current_topic, act_type="토론"):
    """토론 전 생각 입력 폼. 제출 완료 시 전체 앱 재실행."""
    st.info(f"💬 **{'토론' if act_type == '토론' else '토의'} 전 내 생각 먼저 기록하기**\n\n'{current_topic}' 주제에 대한 나의 생각을 적어주세요. 제출 후 {'토론' if act_type == '토론' else '토의'}에 참여할 수 있습니다.")

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
    confirmed = st.checkbox("⚠️ 제출 후에는 수정이 불가능합니다. 확인했습니다.")
    if st.button("✅ 생각 제출 후 토론 참여", use_container_width=True, type="primary", disabled=not confirmed):
        if not pre_input.strip():
            st.warning("생각을 입력해 주세요.")
            return
        res = upsert_pre_opinion(supabase, room_name, student_name, pre_input.strip(), initial_stance=initial_stance)
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
        st.info(f"{end_label}이 종료되었습니다. {end_label} 후 생각이 어떻게 바뀌었는지 기록해 주세요.")

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
        post_confirmed = st.checkbox("⚠️ 제출 후에는 수정이 불가능합니다. 확인했습니다.", key="post_confirm")
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
                _trigger_analysis(supabase, room_name, student_name, act_type, current_topic, pre_opinion, post_input.strip())
                st.rerun()
            else:
                st.error("저장에 실패했습니다. 다시 시도해 주세요.")
    else:
        final_stance_val = (row or {}).get("final_stance") or ""
        discussion_conclusion_val = (row or {}).get("discussion_conclusion") or ""
        if act_type == "토론" and final_stance_val:
            st.success(f"✅ **최종 입장:** {final_stance_val}")
        if act_type == "토의" and discussion_conclusion_val:
            st.success(f"✅ **나의 결론:** {discussion_conclusion_val}")
        st.success(f"✅ **토론 후 내 생각:** {post_opinion}")
        st.divider()
        if ai_analysis:
            st.info("🤖 **AI 배움 분석**")
            st.markdown(ai_analysis.replace("\n", "\n\n"))
            _render_image_download(
                student_name, current_topic, pre_opinion, post_opinion, ai_analysis,
                session_key=f"img_{room_name}_{student_name}",
                btn_key="dl_analysis_student",
            )
        else:
            if st.button("🤖 AI 배움 분석 받기", use_container_width=True):
                _trigger_analysis(supabase, room_name, student_name, act_type, current_topic, pre_opinion, post_opinion)
                st.rerun()


def _render_image_download(student_name, topic, pre_opinion, post_opinion, ai_analysis,
                           session_key, btn_key):
    """이미지를 base64 데이터 URI 링크로 렌더링 — rerun 없이 즉시 다운로드."""
    import base64
    cache_key = f"{session_key}_{len(ai_analysis)}_b64"
    if cache_key not in st.session_state:
        try:
            img_bytes = create_analysis_image(
                student_name, topic, pre_opinion, post_opinion, ai_analysis
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
            # 캐시 초기화 — 새 분석 결과로 이미지 재생성
            cache_key = f"img_{room_name}_{student_name}_bytes"
            st.session_state.pop(cache_key, None)
            st.toast("✅ AI 분석 완료!", icon="🎉")
        else:
            st.toast("🚨 AI 분석에 실패했습니다.", icon="❌")
