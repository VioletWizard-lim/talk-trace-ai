import re


def normalize_user_text(raw_text, max_len=500):
    text = (raw_text or "").strip()
    return text[:max_len] if text else ""


def normalize_room_name(raw_text, max_len=60):
    text = normalize_user_text(raw_text, max_len=max_len)
    return re.sub(r"\s+", " ", text).strip() if text else ""


def mask_ip_for_teacher(ip_text):
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


def with_fallback_author_role(df):
    if df.empty:
        return df

    fixed = df.copy()
    if "author_role" not in fixed.columns:
        fixed["author_role"] = "학생"
        return fixed

    fixed["author_role"] = fixed["author_role"].fillna("").astype(str).str.strip()
    teacher_name_hint = fixed["student_name"].fillna("").astype(str).str.contains("교사|선생님", regex=True)
    fixed.loc[(fixed["author_role"] == "") & teacher_name_hint, "author_role"] = "교사"
    fixed.loc[fixed["author_role"] == "", "author_role"] = "학생"
    return fixed



ALLOWED_TEXT_PATTERN = re.compile(r"^[0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ _.,!?():;@#&/\-]*$")


def _contains_forbidden_word(text, forbidden_words=None):
    words = forbidden_words or []
    lowered = str(text or "").lower()
    for word in words:
        if str(word).lower() in lowered:
            return True
    return False


def _validate_text_field(
    raw_text,
    *,
    field_name,
    max_len,
    allow_empty=False,
    forbidden_words=None,
    allowed_pattern=ALLOWED_TEXT_PATTERN,
):
    normalized = normalize_user_text(raw_text, max_len=max_len)
    if not normalized:
        if allow_empty:
            return True, "", None, None
        return False, "", "VALIDATION_EMPTY", f"{field_name}을(를) 입력해 주세요."

    if len(normalized) > max_len:
        return False, "", "VALIDATION_TOO_LONG", f"{field_name}은(는) {max_len}자 이하여야 합니다."

    if allowed_pattern and not allowed_pattern.match(normalized):
        return False, "", "VALIDATION_INVALID_CHARS", f"{field_name}에 허용되지 않은 문자가 포함되어 있습니다."

    if _contains_forbidden_word(normalized, forbidden_words=forbidden_words):
        return False, "", "VALIDATION_FORBIDDEN", f"{field_name}에 사용할 수 없는 단어가 포함되어 있습니다."

    return True, normalized, None, None


def validate_room_name(raw_text, max_len=60):
    collapsed = normalize_room_name(raw_text, max_len=max_len)
    return _validate_text_field(
        collapsed,
        field_name="방 이름",
        max_len=max_len,
        allow_empty=False,
        forbidden_words=["관리자", "운영자"],
    )


def validate_student_name(raw_text, max_len=30):
    return _validate_text_field(
        raw_text,
        field_name="학생 이름/학번",
        max_len=max_len,
        allow_empty=False,
        forbidden_words=["관리자", "운영자", "admin"],
    )


def validate_opinion_content(raw_text, max_len=700):
    return _validate_text_field(
        raw_text,
        field_name="의견 내용",
        max_len=max_len,
        allow_empty=False,
    )


def validate_entry_code(raw_text, max_len=60):
    return _validate_text_field(
        raw_text,
        field_name="입장 암호",
        max_len=max_len,
        allow_empty=True,
        allowed_pattern=re.compile(r"^[0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ _!@#$%^&*()+=.?/:;\-]*$"),
    )


def validate_teacher_credential(raw_text, *, field_name, max_len=60):
    return _validate_text_field(
        raw_text,
        field_name=field_name,
        max_len=max_len,
        allow_empty=False,
        forbidden_words=[" "],
        allowed_pattern=re.compile(r"^[0-9A-Za-z_.@\-]+$"),
    )
