import logging
import re

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


def build_summary_prompt(act_type, current_topic, full_history,
                         stance_summary: str = "", depth_summary: str = ""):
    extra = ""
    if stance_summary:
        extra += f"\n[입장 변화 데이터]\n{stance_summary}\n"
    if depth_summary:
        extra += f"\n[발언 깊이 분석 데이터]\n{depth_summary}\n"
    return (
        f"'{current_topic}' 주제의 고등학교 {act_type} 기록입니다.\n\n"
        "[출력 형식 - 반드시 그대로]\n"
        "핵심요약 1: ...\n핵심요약 2: ...\n핵심요약 3: ...\n베스트 학생: ...\n선정 이유: ...\n\n"
        "[엄격한 규칙]\n"
        "- 핵심요약 1,2,3과 베스트 학생, 선정이유를 줄바꿈을 하여 보기 편하게 합니다.\n"
        "- 핵심요약 1,2,3은 각각 2~3문장으로, 구체적인 발언 내용과 근거를 포함해 작성합니다.\n"
        "- 선정 이유도 2~3문장으로, 해당 학생의 구체적인 발언이나 근거를 들어 작성합니다.\n"
        "- 입장 변화 및 발언 깊이 데이터가 있으면 핵심요약에 자연스럽게 반영하세요.\n"
        "- 제목/헤더(#,##,###), 소제목을 절대 쓰지 않습니다.\n"
        "- 불필요한 서론/결론 없이 바로 결과만 출력합니다.\n\n"
        f"기록:\n{full_history}"
        f"{extra}"
    )


def build_opinion_change_prompt(act_type, current_topic, student_name, pre_opinion, post_opinion, debate_history):
    return (
        f"'{current_topic}' 주제로 진행된 고등학교 {act_type}에서 "
        f"'{student_name}' 학생의 생각 변화를 분석합니다.\n\n"
        f"[토론 전 생각]\n{pre_opinion}\n\n"
        f"[토론 후 생각]\n{post_opinion}\n\n"
        f"[토론 중 발언 기록]\n{debate_history}\n\n"
        "[출력 형식 - 반드시 그대로]\n"
        "배움의 변화: ...\n"
        "성장한 점: ...\n"
        "한 줄 요약: ...\n\n"
        "[규칙]\n"
        "- 3가지 항목을 줄바꿈으로 구분하여 출력합니다.\n"
        "- 각 항목은 2~3문장으로 작성합니다.\n"
        "- 제목/헤더(#,##), 불필요한 서론 없이 결과만 출력합니다.\n"
        "- 학생의 실제 발언을 근거로 구체적으로 분석합니다."
    )


def build_feedback_prompt(act_type: str, current_topic: str, student_name: str, debate_history: str) -> str:
    return (
        f"'{current_topic}' 주제의 고등학교 {act_type}에서 "
        f"'{student_name}' 학생의 발언을 분석해 개인 피드백을 작성하세요.\n\n"
        f"[발언 기록]\n{debate_history}\n\n"
        "[출력 형식 - 반드시 그대로]\n"
        "✅ 잘한 점: ...\n"
        "🌱 발전할 점: ...\n\n"
        "[규칙]\n"
        "- 학생의 실제 발언을 근거로 구체적으로 작성하세요.\n"
        "- 각 항목은 2~3문장으로 작성하세요.\n"
        "- 긍정적이고 격려하는 톤으로 작성하세요.\n"
        "- 제목/헤더(#,##), 불필요한 서론 없이 결과만 출력하세요.\n"
        "- 발언이 없거나 부족하면 '발언 기록이 부족하여 분석이 어렵습니다.'라고만 출력하세요."
    )


def build_depth_analysis_prompt(opinions: list) -> str:
    """
    opinions: list of (id, content) tuples
    Returns a prompt for batch depth classification.
    """
    opinion_lines = "\n".join([f"id={oid}: \"{content}\"" for oid, content in opinions])
    return (
        "다음 발언들을 발언 깊이 기준에 따라 1~4단계로 분류하세요.\n\n"
        "[발언 깊이 기준]\n"
        "1단계 - 단순의견: 이유나 근거 없이 주장만 제시 (예: '저는 찬성합니다', '반대해요')\n"
        "2단계 - 근거제시: 구체적 근거나 이유를 들어 주장을 뒷받침 (예: '왜냐하면 ~이기 때문입니다')\n"
        "3단계 - 반박/심화질문: 상대방 의견에 반박하거나 비판적 질문 제기 (예: '~라고 했는데, ~는 어떻게 설명하나요?')\n"
        "4단계 - 통합/종합: 여러 관점을 종합하거나 새로운 시각 제시 (예: '찬성과 반대 의견을 고려하면 ~')\n\n"
        "[출력 형식] 아래 형식만 사용하세요. 다른 텍스트는 절대 쓰지 마세요:\n"
        "id=숫자: 단계숫자\n\n"
        "[예시 출력]\n"
        "id=1: 2\n"
        "id=2: 1\n"
        "id=3: 3\n\n"
        "[분류할 발언 목록]\n"
        f"{opinion_lines}"
    )


def parse_depth_levels(response_text: str, opinion_ids: set) -> dict:
    """
    AI 응답을 파싱해서 {opinion_id: depth_level} dict를 반환합니다.
    파싱 실패한 항목은 depth_level=1 로 기본값 처리합니다.
    """
    result = {}
    for match in re.finditer(r"id\s*=\s*(\d+)\s*:\s*([1-4])", response_text, re.IGNORECASE):
        oid = int(match.group(1))
        depth = int(match.group(2))
        if oid in opinion_ids:
            result[oid] = depth
    # 파싱 실패 항목은 1단계로 기본값
    for oid in opinion_ids:
        if oid not in result:
            result[oid] = 1
    return result


def build_moderation_flag_prompt(items: list) -> str:
    """
    items: list of (key, content) tuples. key는 "표key" 형태의 임의 문자열 식별자.
    명백한 욕설(이미 별도 키워드 필터로 차단됨)이 아니라, 그 필터를 우회했거나
    맥락상 문제되는 발언(인신공격/혐오·차별 표현/따돌림/노골적 성적 표현/자해·폭력 암시 등)만
    골라내기 위한 2차(AI) 검수용 프롬프트.
    """
    lines = "\n".join([f"key={key}: \"{content}\"" for key, content in items])
    return (
        "다음은 고등학생 토론/토의 게시판의 발언·답글 목록입니다. "
        "이 중 교사가 반드시 확인해야 할 문제 발언만 골라내세요.\n\n"
        "[문제 발언 기준]\n"
        "- 특정인에 대한 인신공격, 모욕, 조롱\n"
        "- 혐오 표현이나 차별적 발언(성별, 외모, 지역, 장애 등)\n"
        "- 따돌림·괴롭힘을 암시하는 발언\n"
        "- 노골적인 성적 표현\n"
        "- 자해, 폭력을 암시하거나 위협하는 발언\n"
        "정상적인 토론 발언(단순 반박, 의견 차이, 강한 어조의 논쟁 등)은 문제 발언이 아닙니다.\n\n"
        "[출력 형식] 문제 발언이 있는 항목만, 아래 형식으로만 출력하세요. 다른 텍스트는 쓰지 마세요:\n"
        "key=식별자: 사유(10자 이내)\n\n"
        "문제 발언이 하나도 없으면 정확히 다음 한 줄만 출력하세요:\n"
        "NONE\n\n"
        "[검사할 목록]\n"
        f"{lines}"
    )


def parse_moderation_flags(response_text: str, keys: set) -> dict:
    """AI 응답을 파싱해 {key: 사유} dict를 반환합니다. 파싱 안 된 항목은 포함하지 않습니다."""
    result = {}
    if not response_text or response_text.strip().upper() == "NONE":
        return result
    for match in re.finditer(r"key\s*=\s*([^\s:]+)\s*:\s*(.+)", response_text):
        key, reason = match.group(1).strip(), match.group(2).strip()
        if key in keys:
            result[key] = reason[:50]
    return result


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
