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
    for key in ["x-forwarded-for", "x-real-ip", "cf-connecting-ip", "fly-client-ip",
                "X-Forwarded-For", "X-Real-Ip", "CF-Connecting-IP", "True-Client-Ip",
                "true-client-ip"]:
        raw_ip = headers.get(key)
        if raw_ip:
            return str(raw_ip).split(",")[0].strip()
    try:
        all_keys = list(headers.keys()) if headers else []
        logger.info("get_client_ip: IP 헤더 없음. 수신된 헤더 키: %s", all_keys)
    except Exception:
        pass
    return ""


def anonymize_ip(raw_ip: str) -> str | None:
    """IP를 익명화하여 반환합니다. 저장 불가 시 None 반환.

    IPv4: 첫 번째·마지막 옥텟 유지, 중간 0으로 대체 (예: 165.0.0.41)
    IPv6: 앞 4그룹·마지막 그룹 유지, 중간 :: 처리 (예: 2406:5900:117c:424b::4444)
          → 같은 Wi-Fi라도 기기별 구분 가능
    """
    ip = str(raw_ip or "").strip()
    if not ip:
        return None
    if ":" in ip:  # IPv6
        groups = [g for g in ip.split(":") if g]  # 빈 그룹 제거
        if len(groups) >= 5:
            return ":".join(groups[:4]) + "::" + groups[-1]
        if len(groups) >= 4:
            return ":".join(groups[:4]) + "::"
        return None
    parts = ip.split(".")  # IPv4
    if len(parts) == 4:
        return f"{parts[0]}.0.0.{parts[3]}"
    return None


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
_FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]

_AI_SUBSECTION_LABELS = ("배움의 변화:", "성장한 점:", "한 줄 요약:")


def _get_pil_font(size: int):
    from PIL import ImageFont
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _get_pil_font_bold(size: int):
    from PIL import ImageFont
    for path in _FONT_BOLD_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return _get_pil_font(size)


_EMOJI_TEXT_SUBS = [
    # AI 피드백 카드 레이블
    ("✅", "[완료]"),
    ("🌱", "[성장]"),
    # 섹션 마커
    ("📌", ">>"),
    ("🔄", ">>"),
    ("🤖", "[AI]"),
    ("👨‍🏫", "[교사]"),
    # 기타 자주 쓰이는 이모지
    ("💡", "[아이디어]"),
    ("➕", "[보충]"),
    ("❓", "[질문]"),
    ("🔵", "[찬성]"),
    ("🔴", "[반대]"),
    ("👍", "[좋아요]"),
    ("🎉", ""),
    ("⚠️", "[주의]"),
]


def _strip_non_renderable(text: str) -> str:
    """이미지 렌더링 시 깨질 수 있는 이모지/심볼을 텍스트로 대체하거나 제거."""
    # 1단계: 알려진 이모지를 텍스트 레이블로 치환
    for emoji, replacement in _EMOJI_TEXT_SUBS:
        text = (text or "").replace(emoji, replacement)
    # 2단계: 나머지 렌더링 불가 문자 제거
    result = []
    for ch in (text or ""):
        code = ord(ch)
        # 4바이트 유니코드 (이모지 대부분)
        if code > 0xFFFF or 0xD800 <= code <= 0xDFFF:
            continue
        # BMP 내 이모지/기호 블록
        if 0x2190 <= code <= 0x27FF:  # 화살표, 기술기호, 딩뱃(✅ 등)
            continue
        if 0x2B00 <= code <= 0x2BFF:  # 기타 기호·화살표
            continue
        if 0xFE00 <= code <= 0xFEFF:  # 변형 선택자 등
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
    ai_feedback: str = "",
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

    f_title    = _get_pil_font(22)
    f_label    = _get_pil_font(15)
    f_sublabel = _get_pil_font_bold(16)
    f_body     = _get_pil_font(17)
    f_small    = _get_pil_font(13)

    LH_BODY    = 27   # body line height px
    LH_LABEL   = 22
    LH_SUBLBL  = 24
    SEC_GAP    = 16
    SUBSEC_GAP = 14   # extra gap between AI subsections
    HEADER_H   = 74
    FOOTER_H   = 38
    DIV_H      = 20

    def _ai_paragraphs(text):
        """AI 분석 텍스트를 (is_label, label_str, body_str) 튜플 리스트로 파싱."""
        result = []
        for para in _strip_non_renderable(text or "").split("\n"):
            para = para.strip()
            if not para:
                continue
            matched = next((lbl for lbl in _AI_SUBSECTION_LABELS if para.startswith(lbl)), None)
            if matched:
                result.append((True, matched, para[len(matched):].strip()))
            else:
                result.append((False, "", para))
        return result or [(False, "", "(분석 없음)")]

    # ── measure total height with dummy canvas ──────────────────────────
    dummy = Image.new("RGB", (W, 10))
    d = ImageDraw.Draw(dummy)

    def section_h(text):
        return LH_LABEL + 10 + len(_wrap_to_width(d, text, f_body, CONTENT_W)) * LH_BODY + SEC_GAP

    def ai_section_h(text):
        h = LH_LABEL + 10  # "AI 배움 분석" 헤더
        paras = _ai_paragraphs(text)
        for i, (is_lbl, lbl, body) in enumerate(paras):
            if is_lbl and i > 0:
                h += SUBSEC_GAP
            if is_lbl:
                h += LH_SUBLBL + 6
            h += len(_wrap_to_width(d, body if is_lbl else lbl + body, f_body, CONTENT_W)) * LH_BODY
        return h + SEC_GAP

    total_h = (
        HEADER_H + 18
        + LH_LABEL + 14      # info line
        + DIV_H
        + section_h(pre_opinion)
        + section_h(post_opinion)
        + DIV_H
        + ai_section_h(ai_analysis)
        + (DIV_H + section_h(ai_feedback) if ai_feedback else 0)
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

    def ai_section(text):
        nonlocal y
        draw.text((PAD, y), "AI 배움 분석", font=f_label, fill=C_ACCENT)
        y += LH_LABEL + 10
        for i, (is_lbl, lbl, body) in enumerate(_ai_paragraphs(text)):
            if is_lbl and i > 0:
                y += SUBSEC_GAP
            if is_lbl:
                # 소제목: 굵은 강조색
                draw.text((PAD, y), lbl, font=f_sublabel, fill=C_ACCENT)
                y += LH_SUBLBL + 6
                for line in _wrap_to_width(draw, body, f_body, CONTENT_W):
                    draw.text((PAD + 8, y), line, font=f_body, fill=C_TEXT)
                    y += LH_BODY
            else:
                full = (lbl + body).strip()
                for line in _wrap_to_width(draw, full, f_body, CONTENT_W):
                    draw.text((PAD, y), line, font=f_body, fill=C_TEXT)
                    y += LH_BODY
        y += SEC_GAP

    divider()
    section("토론 전 생각", pre_opinion or "(없음)")
    section("토론 후 생각", post_opinion or "(없음)")
    divider()
    ai_section(ai_analysis)
    if ai_feedback:
        divider()
        section("AI 피드백 카드 (잘한 점 / 발전할 점)", ai_feedback)

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
