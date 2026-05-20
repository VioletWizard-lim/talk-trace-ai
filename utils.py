import io
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


_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def _get_pil_font(size: int):
    from PIL import ImageFont
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _strip_non_renderable(text: str) -> str:
    """이미지 렌더링 시 깨질 수 있는 이모지/심볼 제거."""
    result = []
    for ch in (text or ""):
        code = ord(ch)
        if code > 0xFFFF or 0xD800 <= code <= 0xDFFF:
            continue
        result.append(ch)
    return "".join(result)


def _wrap_to_width(draw, text: str, font, max_width: int) -> list:
    lines = []
    for para in _strip_non_renderable(text).split("\n"):
        if not para.strip():
            lines.append("")
            continue
        words = para.split()
        line: list = []
        for word in words:
            test = " ".join(line + [word])
            try:
                w = draw.textbbox((0, 0), test, font=font)[2]
            except Exception:
                w = len(test) * (font.size // 2 if hasattr(font, "size") else 9)
            if w <= max_width:
                line.append(word)
            else:
                if line:
                    lines.append(" ".join(line))
                    line = [word]
                else:
                    lines.append(word)
        if line:
            lines.append(" ".join(line))
    return lines or [""]


def create_analysis_image(
    student_name: str,
    topic: str,
    pre_opinion: str,
    post_opinion: str,
    ai_analysis: str,
) -> bytes:
    """AI 배움 분석 결과를 PNG 이미지 bytes로 반환합니다."""
    from PIL import Image, ImageDraw

    W, PAD = 800, 40
    CONTENT_W = W - PAD * 2

    C_BG        = (255, 255, 255)
    C_HDR_BG    = (25,  80, 160)
    C_HDR_FG    = (255, 255, 255)
    C_HDR_SUB   = (170, 200, 240)
    C_ACCENT    = (25,  80, 160)
    C_TEXT      = (30,  30,  30)
    C_MUTED     = (110, 110, 110)
    C_DIVIDER   = (220, 220, 220)
    C_FTR_BG    = (245, 245, 248)

    f_title = _get_pil_font(22)
    f_label = _get_pil_font(15)
    f_body  = _get_pil_font(17)
    f_small = _get_pil_font(13)

    LH_BODY    = 27   # body line height px
    LH_LABEL   = 22
    SEC_GAP    = 16
    HEADER_H   = 74
    FOOTER_H   = 38
    DIV_H      = 20

    # ── measure total height with dummy canvas ──────────────────────────
    dummy = Image.new("RGB", (W, 10))
    d = ImageDraw.Draw(dummy)

    def section_h(text):
        return LH_LABEL + 10 + len(_wrap_to_width(d, text, f_body, CONTENT_W)) * LH_BODY + SEC_GAP

    total_h = (
        HEADER_H + 18
        + LH_LABEL + 14      # info line
        + DIV_H
        + section_h(pre_opinion)
        + section_h(post_opinion)
        + DIV_H
        + section_h(ai_analysis)
        + FOOTER_H
    )

    # ── render ──────────────────────────────────────────────────────────
    img  = Image.new("RGB", (W, total_h), C_BG)
    draw = ImageDraw.Draw(img)

    # Header
    draw.rectangle([0, 0, W, HEADER_H], fill=C_HDR_BG)
    draw.text((PAD, 14), "말자취 Talk-Trace AI", font=f_small, fill=C_HDR_SUB)
    draw.text((PAD, 34), "AI 배움 분석 결과", font=f_title, fill=C_HDR_FG)

    y = HEADER_H + 18

    # Student / topic info line
    info = f"학생: {_strip_non_renderable(student_name)}    |    주제: {_strip_non_renderable(topic)}"
    draw.text((PAD, y), info, font=f_label, fill=C_MUTED)
    y += LH_LABEL + 14

    def divider():
        nonlocal y
        draw.line([PAD, y, W - PAD, y], fill=C_DIVIDER, width=1)
        y += DIV_H

    def section(label, text):
        nonlocal y
        draw.text((PAD, y), label, font=f_label, fill=C_ACCENT)
        y += LH_LABEL + 10
        for line in _wrap_to_width(draw, text, f_body, CONTENT_W):
            draw.text((PAD, y), line, font=f_body, fill=C_TEXT)
            y += LH_BODY
        y += SEC_GAP

    divider()
    section("토론 전 생각", pre_opinion or "(없음)")
    section("토론 후 생각", post_opinion or "(없음)")
    divider()
    section("AI 배움 분석", ai_analysis or "(분석 없음)")

    # Footer
    draw.rectangle([0, total_h - FOOTER_H, W, total_h], fill=C_FTR_BG)
    now_str = datetime.now(tz=KST).strftime("%Y-%m-%d %H:%M")
    draw.text((PAD, total_h - FOOTER_H + 13), f"생성: {now_str}", font=f_small, fill=C_MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def compact_ai_report_output(text):
    raw_lines = [str(line).strip() for line in str(text or "").splitlines()]
    cleaned = [line for line in raw_lines if line and not line.startswith("#")]
    if not cleaned:
        return ""
    normalized_text = " ".join(cleaned)
    normalized_text = re.sub(r"\s*(핵심요약 [123]:|베스트 학생:|선정 이유:)", r"\n\1", normalized_text)
    normalized_lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
    return "\n".join(normalized_lines[:5])
