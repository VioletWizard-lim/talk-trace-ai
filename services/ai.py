import logging
import google.generativeai as genai

logger = logging.getLogger("talk_trace_ai")

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
        response_text = genai.GenerativeModel(model_name).generate_content(prompt).text

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
