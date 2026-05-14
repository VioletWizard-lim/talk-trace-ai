import logging
import google.generativeai as genai

logger = logging.getLogger("talk_trace_ai")


# ── 프롬프트 빌더 ──

def build_hint_prompt(act_type, current_topic, context):
    return (
        f"당신은 고등학교 {act_type} 조력자입니다. "
        f"'{current_topic}' 주제로 {act_type} 중입니다. "
        "학생들의 균형을 맞추거나 더 깊은 생각을 유도할 수 있는 "
        "예리한 질문을 1문장만 제안하세요. "
        "번호 매기기나 번잡한 서론 없이 질문 자체만 출력하세요."
        f"\n최근 대화: {context}"
    )


def build_summary_prompt(act_type, current_topic, full_history):
    return (
        f"'{current_topic}' 주제의 고등학교 {act_type} 기록입니다.\n\n"
        "[출력 형식 - 반드시 그대로]\n"
        "핵심요약 1: ...\n핵심요약 2: ...\n핵심요약 3: ...\n베스트 학생: ...\n선정 이유: ...\n\n"
        "[엄격한 규칙]\n"
        "- 핵심요약 1,2,3과 베스트 학생, 선정이유를 줄바꿈을 하여 보기 편하게 합니다.\n"
        "- 5~10줄로 출력합니다.\n- 제목/헤더(#,##,###), 소제목을 절대 쓰지 않습니다.\n"
        "- 불필요한 서론/결론 없이 바로 결과만 출력합니다.\n\n"
        f"기록:\n{full_history}"
    )


def build_record_prompt(act_type, current_topic, selected_student, debate_history):
    return (
        f"당신은 정보 교사입니다. "
        f"'{current_topic}' 주제 {act_type}에 참여한 "
        f"'{selected_student}' 학생의 활동 기록입니다. "
        "이를 바탕으로 생활기록부 교과세특 초안을 약 300자 내외로 작성하세요. "
        f"교육적 성장을 강조하세요.\n\n[활동 기록]\n{debate_history}"
    )

# ── API 키 초기화 상태 추적 (모듈 수준 1회만 실행) ──
_initialized_api_key: str | None = None


def _ensure_configured(api_key: str) -> None:
    """API 키가 바뀐 경우에만 genai.configure()를 재실행합니다."""
    global _initialized_api_key
    if _initialized_api_key != api_key:
        genai.configure(api_key=api_key)
        _initialized_api_key = api_key


def generate_ai_response(
    prompt: str,
    model_name: str,
    api_key: str,
    log_message: str,
    fallback: str = "AI 응답을 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.",
    **context,
) -> str | None:
    """
    Gemini AI 응답을 생성합니다.

    Parameters
    ----------
    prompt      : 모델에 전달할 프롬프트
    model_name  : 사용할 Gemini 모델명 (예: gemini-2.5-flash)
    api_key     : Gemini API 키
    log_message : 실패 시 로그에 남길 메시지
    fallback    : AI 응답이 공백이거나 실패 시 반환할 기본 문구
    context     : 로그에 포함할 추가 컨텍스트 (room_name 등)

    Returns
    -------
    str  : AI 응답 텍스트 또는 fallback 문구
    None : 치명적 오류로 fallback도 반환하기 어려운 경우 (현재는 항상 fallback 반환)
    """
    try:
        _ensure_configured(api_key)
        response = genai.GenerativeModel(model_name).generate_content(prompt)
        response_text = response.text if response else None

        # 응답이 공백이거나 None인 경우 fallback 반환
        if not response_text or not response_text.strip():
            logger.warning(
                "AI_EMPTY_RESPONSE %s — 빈 응답 수신, fallback 반환 (context=%s)", log_message, context
            )
            return fallback

        return response_text

    except Exception:
        logger.exception(
            "AI_CALL_FAILED %s (model=%s, context=%s)", log_message, model_name, context
        )
        return fallback
