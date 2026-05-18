import logging
import re
from datetime import datetime, timedelta, timezone

import streamlit as st

logger = logging.getLogger("talk_trace_ai")

DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
DISPLAY_DATETIME_FMT = "%Y-%m-%d %p %I:%M:%S"
KST = timezone(timedelta(hours=9))


def get_kst_now():
    return datetime.now(tz=KST)


def get_kst_now_str():
    return get_kst_now().strftime(DATETIME_FMT)


def format_kst_datetime(value):
    if value is None:
        return "-"
    kst_tz = timezone(timedelta(hours=9))
    parsed_dt = None
    should_assume_utc = False
    if isinstance(value, datetime):
        parsed_dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return "-"
        if "T" in raw and "+" not in raw and "Z" not in raw:
            should_assume_utc = True
        iso_candidate = raw.replace("Z", "+00:00")
        try:
            parsed_dt = datetime.fromisoformat(iso_candidate)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", DATETIME_FMT):
                try:
                    parsed_dt = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
    if parsed_dt is None:
        return str(value)
    if parsed_dt.tzinfo is not None:
        parsed_dt = parsed_dt.astimezone(kst_tz)
    elif should_assume_utc:
        parsed_dt = parsed_dt.replace(tzinfo=timezone.utc).astimezone(kst_tz)
    return parsed_dt.strftime(DISPLAY_DATETIME_FMT)


def get_client_ip():
    try:
        headers = st.context.headers
    except Exception:
        return ""
    if not headers:
        return ""
    for key in ["x-forwarded-for", "x-real-ip", "cf-connecting-ip", "fly-client-ip"]:
        raw_ip = headers.get(key)
        if raw_ip:
            return str(raw_ip).split(",")[0].strip()
    return ""


def log_audit(event, room_name="", actor_name="", role="", **extra):
    logger.info(
        "AUDIT event=%s room=%s actor=%s role=%s extra=%s",
        event, room_name, actor_name, role, extra,
    )


def to_bool_flag(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "t", "1", "yes", "y", "on"}


def compact_ai_report_output(text):
    raw_lines = [str(line).strip() for line in str(text or "").splitlines()]
    cleaned = [line for line in raw_lines if line and not line.startswith("#")]
    if not cleaned:
        return ""
    normalized_text = " ".join(cleaned)
    normalized_text = re.sub(r"\s*(핵심요약 [123]:|베스트 학생:|선정 이유:)", r"\n\1", normalized_text)
    normalized_lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
    return "\n".join(normalized_lines[:5])
