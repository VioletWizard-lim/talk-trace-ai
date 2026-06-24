import io
import os
import re
import textwrap

import pandas as pd
import streamlit as st

from env import get_secret
from services.ai import generate_ai_response, build_summary_prompt
from utils import compact_ai_report_output, get_kst_now
from config import AI_MODEL_NAME, DASHBOARD_FETCH_LIMIT

_NANUM_FONT_PATH = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
_NANUM_BOLD_FONT_PATH = "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"


# ── PDF 생성 ──────────────────────────────────────────────────────────────────

def _get_pdf_font():
    """reportlab에 Nanum 한글 폰트를 등록하고 폰트명을 반환합니다."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if os.path.exists(_NANUM_FONT_PATH):
        try:
            pdfmetrics.registerFont(TTFont("Nanum", _NANUM_FONT_PATH))
            if os.path.exists(_NANUM_BOLD_FONT_PATH):
                pdfmetrics.registerFont(TTFont("NanumBold", _NANUM_BOLD_FONT_PATH))
            else:
                pdfmetrics.registerFont(TTFont("NanumBold", _NANUM_FONT_PATH))
            return "Nanum", "NanumBold"
        except Exception:
            pass
    return "Helvetica", "Helvetica-Bold"


def _build_pdf(room_name: str, act_type: str, current_topic: str, report_text: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as rl_canvas

    font_name, font_bold = _get_pdf_font()
    buf = io.BytesIO()
    W, H = A4
    PAD = 18 * mm
    CONTENT_W = W - PAD * 2

    c = rl_canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"{room_name} {act_type} 요약 리포트")

    def draw_wrapped(text, x, y, font, size, max_w, line_h, color=(0.15, 0.15, 0.15)):
        c.setFont(font, size)
        c.setFillColorRGB(*color)
        for line in text.splitlines():
            words = line.split()
            cur_line = ""
            for word in words:
                test = (cur_line + " " + word).strip()
                if c.stringWidth(test, font, size) <= max_w:
                    cur_line = test
                else:
                    if cur_line:
                        c.drawString(x, y, cur_line)
                        y -= line_h
                    cur_line = word
            if cur_line:
                c.drawString(x, y, cur_line)
                y -= line_h
        return y

    y = H - PAD

    # Header bar
    c.setFillColorRGB(0.082, 0.314, 0.627)
    c.rect(0, H - 22 * mm, W, 22 * mm, fill=1, stroke=0)
    c.setFont(font_bold, 15)
    c.setFillColorRGB(1, 1, 1)
    c.drawString(PAD, H - 13 * mm, f"말자취 Talk-Trace AI  |  {act_type} 요약 리포트")
    y = H - 28 * mm

    # 방 정보
    c.setFont(font_name, 10)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    now_str = get_kst_now().strftime("%Y-%m-%d %H:%M")
    c.drawString(PAD, y, f"방: {room_name}    |    주제: {current_topic}    |    생성: {now_str}")
    y -= 6 * mm

    # 구분선
    c.setStrokeColorRGB(0.82, 0.82, 0.82)
    c.line(PAD, y, W - PAD, y)
    y -= 7 * mm

    # 섹션별 파싱 및 렌더링
    sections = _parse_report(report_text)
    section_styles = {
        "핵심요약": ("#1558a0", (0.082, 0.314, 0.627)),
        "베스트 학생": ("#166534", (0.086, 0.396, 0.204)),
        "선정 이유": ("#92400e", (0.573, 0.251, 0.055)),
    }

    for label, content in sections:
        if y < 40 * mm:
            c.showPage()
            y = H - PAD

        # 섹션 라벨 배경
        bg_rgb = section_styles.get(label, ("#374151", (0.216, 0.255, 0.318)))[1]
        c.setFillColorRGB(*bg_rgb)
        c.roundRect(PAD, y - 6.5 * mm, CONTENT_W, 8 * mm, 3, fill=1, stroke=0)
        c.setFont(font_bold, 11)
        c.setFillColorRGB(1, 1, 1)
        c.drawString(PAD + 3 * mm, y - 4 * mm, label)
        y -= 10 * mm

        # 본문
        y = draw_wrapped(content, PAD + 3 * mm, y, font_name, 11, CONTENT_W - 6 * mm, 6 * mm)
        y -= 5 * mm

    c.save()
    return buf.getvalue()


# ── 리포트 파싱 ────────────────────────────────────────────────────────────────

def _parse_report(text: str) -> list[tuple[str, str]]:
    """compact_ai_report_output 결과를 (라벨, 내용) 튜플 리스트로 파싱합니다."""
    patterns = [
        (r"핵심요약\s*[123]", "핵심요약"),
        (r"베스트\s*학생", "베스트 학생"),
        (r"선정\s*이유", "선정 이유"),
    ]
    sections = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        matched_label = None
        content = line
        for pattern, label in patterns:
            m = re.match(rf"^({pattern})\s*[:\-：]?\s*(.+)", line, re.IGNORECASE)
            if m:
                matched_label = label
                content = m.group(2).strip()
                break
        sections.append((matched_label or "", content))

    # 같은 라벨끼리 합치지 않고 순서대로 반환 (각 줄을 카드 하나로)
    result = []
    for label, content in sections:
        if label:
            result.append((label, content))
        elif result:
            result[-1] = (result[-1][0], result[-1][1] + "\n" + content)
        else:
            result.append(("", content))
    return result


# ── Excel 다운로드 ─────────────────────────────────────────────────────────────

def _excel_bytes(df_all: pd.DataFrame) -> bytes:
    EXCLUDE_COLS = {'user_id', 'ip_address', 'created_at'}
    export_df = df_all.drop(columns=[c for c in EXCLUDE_COLS if c in df_all.columns])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        export_df.to_excel(writer, index=False)
    return buf.getvalue()


# ── 메인 섹션 렌더링 ───────────────────────────────────────────────────────────

_CARD_CSS = """
<style>
.report-card {
    border-radius: 10px; padding: 14px 18px; margin: 8px 0;
    font-size: 16px; line-height: 1.75;
}
.rc-summary { background: #dbeafe; border-left: 5px solid #1558a0; }
.rc-best    { background: #dcfce7; border-left: 5px solid #166534; }
.rc-reason  { background: #fef9c3; border-left: 5px solid #d97706; }
.rc-label   { font-size: 12px; font-weight: 700; letter-spacing: .05em;
               text-transform: uppercase; opacity: .65; margin-bottom: 4px; }
.rc-content { font-size: 16px; }
</style>
"""

_LABEL_STYLE = {
    "핵심요약": "rc-summary",
    "베스트 학생": "rc-best",
    "선정 이유": "rc-reason",
}


def _render_report_cards(report_text: str):
    st.markdown(_CARD_CSS, unsafe_allow_html=True)
    sections = _parse_report(report_text)
    summary_idx = 0
    for label, content in sections:
        if label == "핵심요약":
            summary_idx += 1
            display_label = f"핵심요약 {summary_idx}"
        else:
            display_label = label or "기타"
        css_cls = _LABEL_STYLE.get(label, "rc-summary")
        st.markdown(
            f'<div class="report-card {css_cls}">'
            f'<div class="rc-label">{display_label}</div>'
            f'<div class="rc-content">{content}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


@st.fragment
def render_summary_section(room_name, act_type, current_topic, df_all):
    st.subheader(f"📝 수업 종료 및 전체 {act_type} 요약 리포트")

    col_gen, col_excel = st.columns([3, 1])
    with col_gen:
        if st.button(f"✨ {act_type} 요약 및 베스트 발언 추출", use_container_width=True, type="primary"):
            st.toast("👀 AI가 전체 기록을 꼼꼼히 읽고 있습니다...", icon="⏳")
            with st.spinner("✍️ 요약 리포트를 작성하고 있습니다..."):
                if not df_all.empty:
                    full_history = "\n".join([
                        f"[{row['student_name']} - {row['sentiment']}] {row['content']}"
                        for _, row in df_all.iterrows()
                    ])
                    prompt = build_summary_prompt(act_type, current_topic, full_history)
                    try:
                        res_text = generate_ai_response(
                            prompt, model_name=AI_MODEL_NAME, api_key=get_secret("GEMINI_API_KEY", ""),
                            log_message="AI 요약 리포트 생성 실패", room_name=room_name,
                        )
                    except Exception as e:
                        st.error(f"🚨 AI 호출 중 오류가 발생했습니다: {e}")
                        res_text = None
                    if res_text:
                        st.session_state['ai_report_text'] = compact_ai_report_output(res_text)
                        st.toast("✅ 리포트 작성 완료!", icon="🎉")
                    elif res_text is not None:
                        st.toast("🚨 AI 호출 오류가 발생했습니다.", icon="❌")
                else:
                    st.toast("🚨 분석할 데이터가 없습니다.", icon="⚠️")

    with col_excel:
        if not df_all.empty:
            if len(df_all) >= DASHBOARD_FETCH_LIMIT:
                st.caption(f"⚠️ 최근 {DASHBOARD_FETCH_LIMIT}개만 포함")
            st.download_button(
                "📥 활동 데이터 (Excel)",
                data=_excel_bytes(df_all),
                file_name=f"{room_name}_log_{get_kst_now().strftime('%Y%m%d_%H%M')}.xlsx",
                use_container_width=True,
            )

    report_text = st.session_state.get('ai_report_text', '')
    if report_text:
        st.markdown("---")
        _render_report_cards(report_text)

        # PDF 다운로드
        try:
            pdf_bytes = _build_pdf(room_name, act_type, current_topic, report_text)
            st.download_button(
                "📄 리포트 PDF 다운로드",
                data=pdf_bytes,
                file_name=f"{room_name}_{act_type}_리포트_{get_kst_now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.caption(f"PDF 생성 실패: {e}")
