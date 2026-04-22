import re


# ══════════════════════════════════════════════
# [1] 에러 코드 상수
# ══════════════════════════════════════════════

class ValidationError:
    EMPTY         = "VALIDATION_EMPTY"
    TOO_LONG      = "VALIDATION_TOO_LONG"
    INVALID_CHARS = "VALIDATION_INVALID_CHARS"
    FORBIDDEN     = "VALIDATION_FORBIDDEN"


# ── 에러 코드 → 사용자 메시지 매핑 ──
VALIDATION_MESSAGES = {
    ValidationError.EMPTY:         "{field}을(를) 입력해 주세요.",
    ValidationError.TOO_LONG:      "{field}은(는) {max_len}자 이하여야 합니다.",
    ValidationError.INVALID_CHARS: "{field}에 허용되지 않은 문자가 포함되어 있습니다.",
    ValidationError.FORBIDDEN:     "{field}에 사용할 수 없는 단어가 포함되어 있습니다.",
}


# ══════════════════════════════════════════════
# [2] 텍스트 정규화 유틸리티
# ══════════════════════════════════════════════

def normalize_user_text(raw_text, max_len=500):
    """앞뒤 공백 제거 후 max_len까지 자릅니다."""
    text = (raw_text or "").strip()
    return text[:max_len] if text else ""


def normalize_room_name(raw_text, max_len=60):
    """방 이름 전용: 연속 공백을 단일 공백으로 압축합니다."""
    text = normalize_user_text(raw_text, max_len=max_len)
    return re.sub(r"\s+", " ", text).strip() if text else ""


# ══════════════════════════════════════════════
# [3] IP 마스킹
# ══════════════════════════════════════════════

def mask_ip_for_teacher(ip_text):
    """
    교사 화면에 표시할 IP를 마스킹합니다.
      IPv4 예: 1.XXX.XXX.4
      IPv6 예: 2001:db8:XXXX:XXXX:1
    """
    ip = str(ip_text or "").strip()
    if not ip:
        return ""

    ipv4_parts = ip.split(".")
    if len(ipv4_parts) == 4 and all(part.isdigit() for part in ipv4_parts):
        return f"{ipv4_parts[0]}.XXX.XXX.{ipv4_parts[3]}"

    if ":" in ip:
        ipv6_parts = ip.split(":")
        if len(ipv6_parts) >= 3:
            return f"{ipv6_parts[0]}:{ipv6_parts[1]}:XXXX:XXXX:{ipv6_parts[-1]}"

    return ip


# ══════════════════════════════════════════════
# [4] author_role fallback
# ══════════════════════════════════════════════

def with_fallback_author_role(df):
    """
    author_role 컬럼이 없거나 비어 있는 레거시 데이터를
    student_name 기반으로 역할을 추정해 채웁니다.
      - '교사' / '선생님' 포함 → '교사'
      - 그 외 → '학생'
    """
    if df.empty:
        return df

    fixed = df.copy()
    if "author_role" not in fixed.columns:
        fixed["author_role"] = "학생"
        return fixed

    fixed["author_role"] = fixed["author_role"].fillna("").astype(str).str.strip()
    teacher_name_hint = fixed["student_name"].fillna("").astype(str).str.contains(
        "교사|선생님", regex=True
    )
    fixed.loc[(fixed["author_role"] == "") & teacher_name_hint, "author_role"] = "교사"
    fixed.loc[fixed["author_role"] == "", "author_role"] = "학생"
    return fixed


# ══════════════════════════════════════════════
# [5] 허용 문자 패턴
# ══════════════════════════════════════════════

# 일반 텍스트 필드: 한글, 영문, 숫자, 기본 특수문자 허용
ALLOWED_TEXT_PATTERN = re.compile(
    r"^[0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ \_.,!?():;@#&/\-]*$"
)

# 입장 암호: 일반 텍스트보다 넓은 특수문자 허용
ALLOWED_ENTRY_CODE_PATTERN = re.compile(
    r"^[0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ \_!@#$%^&*()+=.?/:;\-]*$"
)

# 교사 ID/PW: 영문·숫자·일부 특수문자만 허용 (공백 불허)
ALLOWED_CREDENTIAL_PATTERN = re.compile(
    r"^[0-9A-Za-z\_.@\-]+$"
)


# ══════════════════════════════════════════════
# [6] 금지어 검사
# ══════════════════════════════════════════════

def _contains_forbidden_word(text, forbidden_words=None):
    """forbidden_words 중 하나라도 포함되면 True를 반환합니다."""
    words = forbidden_words or []
    lowered = str(text or "").lower()
    return any(str(word).lower() in lowered for word in words)


# ══════════════════════════════════════════════
# [7] 공통 검증 함수
# ══════════════════════════════════════════════

def _validate_text_field(
    raw_text,
    *,
    field_name,
    max_len,
    allow_empty=False,
    forbidden_words=None,
    allowed_pattern=ALLOWED_TEXT_PATTERN,
):
    """
    텍스트 필드 공통 검증 로직.

    Returns
    -------
    (ok: bool, safe_text: str, error_code: str | None, error_message: str | None)
    """
    normalized = normalize_user_text(raw_text, max_len=max_len)

    if not normalized:
        if allow_empty:
            return True, "", None, None
        return (
            False, "",
            ValidationError.EMPTY,
            VALIDATION_MESSAGES[ValidationError.EMPTY].format(field=field_name),
        )

    if len(normalized) > max_len:
        return (
            False, "",
            ValidationError.TOO_LONG,
            VALIDATION_MESSAGES[ValidationError.TOO_LONG].format(
                field=field_name, max_len=max_len
            ),
        )

    if allowed_pattern and not allowed_pattern.match(normalized):
        return (
            False, "",
            ValidationError.INVALID_CHARS,
            VALIDATION_MESSAGES[ValidationError.INVALID_CHARS].format(field=field_name),
        )

    if _contains_forbidden_word(normalized, forbidden_words=forbidden_words):
        return (
            False, "",
            ValidationError.FORBIDDEN,
            VALIDATION_MESSAGES[ValidationError.FORBIDDEN].format(field=field_name),
        )

    return True, normalized, None, None


# ══════════════════════════════════════════════
# [8] 필드별 검증 함수
# ══════════════════════════════════════════════

def validate_room_name(raw_text, max_len=60):
    """
    방 이름 검증.
    - 연속 공백 압축 후 검사
    - '관리자', '운영자' 금지
    """
    collapsed = normalize_room_name(raw_text, max_len=max_len)
    return _validate_text_field(
        collapsed,
        field_name="방 이름",
        max_len=max_len,
        allow_empty=False,
        forbidden_words=["관리자", "운영자"],
    )


def validate_student_name(raw_text, max_len=30):
    """
    학생 이름/학번 검증.
    - '관리자', '운영자', 'admin' 금지
    """
    return _validate_text_field(
        raw_text,
        field_name="학생 이름/학번",
        max_len=max_len,
        allow_empty=False,
        forbidden_words=["관리자", "운영자", "admin"],
    )


def validate_opinion_content(raw_text, max_len=700):
    """
    의견 내용 검증.
    - 최대 700자
    - 허용 문자 패턴 적용
    """
    return _validate_text_field(
        raw_text,
        field_name="의견 내용",
        max_len=max_len,
        allow_empty=False,
    )


def validate_entry_code(raw_text, max_len=60):
    """
    방 입장 암호 검증.
    - 비어 있어도 허용 (공개방)
    - 일반 텍스트보다 넓은 특수문자 허용
    """
    return _validate_text_field(
        raw_text,
        field_name="입장 암호",
        max_len=max_len,
        allow_empty=True,
        allowed_pattern=ALLOWED_ENTRY_CODE_PATTERN,
    )


def validate_teacher_credential(raw_text, *, field_name, max_len=60):
    """
    교사 ID / PW 검증.
    - 공백 불허
    - 영문, 숫자, _.@- 만 허용
    """
    return _validate_text_field(
        raw_text,
        field_name=field_name,
        max_len=max_len,
        allow_empty=False,
        forbidden_words=[" "],
        allowed_pattern=ALLOWED_CREDENTIAL_PATTERN,
    )
