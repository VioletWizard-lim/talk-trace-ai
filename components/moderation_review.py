"""AI 유해 발언 2차 검수 컴포넌트 — 교사 대시보드 전용.

1차 방어선(moderation.py의 즉시 키워드 차단)을 통과했지만 맥락상 문제될 수 있는
발언(인신공격, 혐오 표현, 따돌림 암시 등)을 토론/토의 종료 시 AI로 배치 검수해
교사에게 검토용으로 플래그만 남긴다. 제출 경로에는 영향을 주지 않는다.
"""
import logging

import streamlit as st

from db import (
    fetch_flaggable_content, fetch_flagged_source_keys, create_content_flag,
    fetch_unreviewed_flags_for_room, mark_flag_reviewed, content_flags_available,
    delete_opinion_message, delete_comment, fetch_live_messages, fetch_comments_for_room,
)
from env import get_secret
from config import AI_MODEL_NAME, AI_MODEL_NAME_PRO
from services.ai import build_moderation_flag_prompt, generate_ai_response, parse_moderation_flags

logger = logging.getLogger("talk_trace_ai")

_BATCH_SIZE = 30


def _scan_in_batches(items: list, api_key: str) -> dict:
    """items: list of (key, content). Returns {key: reason} for flagged items only."""
    all_results = {}
    for i in range(0, len(items), _BATCH_SIZE):
        batch = items[i: i + _BATCH_SIZE]
        prompt = build_moderation_flag_prompt(batch)
        response = generate_ai_response(
            prompt=prompt, model_name=AI_MODEL_NAME_PRO, api_key=api_key,
            log_message="moderation_flag_batch (Pro)", fallback="",
        )
        if not response:
            response = generate_ai_response(
                prompt=prompt, model_name=AI_MODEL_NAME, api_key=api_key,
                log_message="moderation_flag_batch (Flash 재시도)", fallback="",
            )
        if response:
            batch_keys = {k for k, _ in batch}
            all_results.update(parse_moderation_flags(response, batch_keys))
        # AI 실패 시 해당 배치는 조용히 건너뜀 (플래그 누락 < 제출 흐름 방해 방지 우선)
    return all_results


def auto_flag_room_content(supabase, room_name: str) -> bool:
    """토론/토의 종료 시 자동으로 호출되는 유해 발언 2차 검수.

    이미 플래그된 항목은 다시 검사하지 않는다. 문제 없다고 판단된 항목은
    별도 기록을 남기지 않으므로, 재실행 시 그 항목들은 다시 검사 대상이 된다.
    """
    if not content_flags_available():
        return False
    api_key = get_secret("GEMINI_API_KEY", "")
    if not api_key:
        return False

    all_items = fetch_flaggable_content(supabase, room_name)
    if not all_items:
        return False

    already_flagged = fetch_flagged_source_keys(supabase, room_name)
    to_scan = [
        (f"{it['source_table']}:{it['source_id']}", it["content"])
        for it in all_items
        if (it["source_table"], it["source_id"]) not in already_flagged and it["content"]
    ]
    if not to_scan:
        return True

    flagged = _scan_in_batches(to_scan, api_key)
    if not flagged:
        return True

    by_key = {f"{it['source_table']}:{it['source_id']}": it for it in all_items}
    ok = True
    for key, reason in flagged.items():
        item = by_key.get(key)
        if not item:
            continue
        res = create_content_flag(
            supabase, room_name, item["source_table"], item["source_id"],
            item["student_name"], item["content"], reason,
        )
        if res is None:
            ok = False
    return ok


def render_moderation_review_section(supabase, room_name: str) -> None:
    """교사 대시보드 삭제 보관소 탭에 삽입되는 AI 유해 발언 검수 섹션."""
    if not content_flags_available():
        return

    flags = fetch_unreviewed_flags_for_room(supabase, room_name)
    st.subheader("🚩 AI 유해 발언 검수")
    st.caption("키워드 필터를 통과했지만 AI가 맥락상 문제될 수 있다고 판단한 발언·답글입니다.")

    if not flags:
        st.info("검토가 필요한 발언이 없습니다.")
        return

    for flag in flags:
        flag_id = flag["id"]
        source_table = flag["source_table"]
        source_id = flag["source_id"]
        with st.container(border=True):
            st.markdown(f"**{flag.get('student_name', '')}** — {flag.get('content', '')}")
            st.caption(f"⚠️ AI 판단 사유: {flag.get('reason', '')}")

            col_ok, col_del = st.columns(2)
            with col_ok:
                if st.button("✅ 문제 없음", key=f"flag_ok_{flag_id}", use_container_width=True):
                    if mark_flag_reviewed(supabase, flag_id, reviewed_by="교사") is not None:
                        fetch_unreviewed_flags_for_room.clear()
                        st.toast("검토 완료로 표시했습니다.", icon="✅")
                        st.rerun(scope="app")
            with col_del:
                if st.button("🗑️ 발언 삭제", key=f"flag_del_{flag_id}", use_container_width=True):
                    if source_table == "debate":
                        res = delete_opinion_message(supabase, source_id, deleted_by="교사")
                        fetch_live_messages.clear()
                    else:
                        res = delete_comment(supabase, source_id, deleted_by="교사")
                        fetch_comments_for_room.clear()
                    if res is not None:
                        mark_flag_reviewed(supabase, flag_id, reviewed_by="교사")
                        fetch_unreviewed_flags_for_room.clear()
                        st.toast("발언을 삭제하고 검토 완료로 표시했습니다.", icon="🗑️")
                        st.rerun(scope="app")
