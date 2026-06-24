import io
import os
import re

import pandas as pd
import streamlit as st

from env import get_secret
from services.ai import generate_ai_response, build_summary_prompt
from utils import compact_ai_report_output, get_kst_now
from config import AI_MODEL_NAME, DASHBOARD_FETCH_LIMIT
from db import (
    fetch_all_opinion_changes, fetch_opinions_for_depth,
    opinion_changes_available, stance_available, depth_level_available,
    topic_ai_report_available, save_ai_report, fetch_ai_report,
)

_NANUM_FONT_PATH = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
_NANUM_BOLD_FONT_PATH = "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"


# ── 데이터 수집 헬퍼 ──────────────────────────────────────────────────────────

def _build_stance_summary(df_oc: pd.DataFrame) -> str:
    """입장 변화 데이터를 텍스트 요약으로 변환합니다."""
    if df_oc.empty:
        return ""
    if "initial_stance" not in df_oc.columns or "final_stance" not in df_oc.columns:
        return ""
    both = df_oc[df_oc["initial_stance"].notna() & df_oc["final_stance"].notna()]
    if both.empty:
        return ""
    lines = []
    for _, r in both.iterrows():
        lines.append(f"- {r['student_name']}: {r['initial_stance']} → {r['final_stance']}")
    return "\n".join(lines)


def _build_depth_summary(depth_opinions: list) -> str:
    """발언 깊이 분석 결과를 텍스트 요약으로 변환합니다."""
    if not depth_opinions:
        return ""
    df = pd.DataFrame(depth_opinions)
    classified = df[df["depth_level"].notna()].copy()
    if classified.empty:
        return ""
    classified["depth_level"] = classified["depth_level"].astype(int)
    label_map = {1: "단순의견", 2: "근거제시", 3: "반박/심화질문", 4: "통합/종합"}
    student_avg = (
        classified.groupby("student_name")["depth_level"]
        .mean().round(2).sort_values(ascending=False)
    )
    dist = classified["depth_level"].map(label_map).value_counts().to_dict()
    dist_str = ", ".join(f"{k} {v}개" for k, v in dist.items())
    student_str = ", ".join(f"{name}({avg}점)" for name, avg in student_avg.items())
    return f"전체 분포: {dist_str}\n학생별 평균: {student_str}"


# ── PDF 생성 ──────────────────────────────────────────────────────────────────

def _get_pdf_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if os.path.exists(_NANUM_FONT_PATH):
        try:
            pdfmetrics.registerFont(TTFont("Nanum", _NANUM_FONT_PATH))
            bold_path = _NANUM_BOLD_FONT_PATH if os.path.exists(_NANUM_BOLD_FONT_PATH) else _NANUM_FONT_PATH
            pdfmetrics.registerFont(TTFont("NanumBold", bold_path))
            return "Nanum", "NanumBold"
        except Exception:
            pass
    return "Helvetica", "Helvetica-Bold"


def _build_pdf(
    room_name: str, act_type: str, current_topic: str, report_text: str,
    df_oc: pd.DataFrame, depth_opinions: list,
) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas

    font_name, font_bold = _get_pdf_font()
    buf = io.BytesIO()
    W, H = A4
    PAD = 18 * mm
    CONTENT_W = W - PAD * 2

    c = rl_canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"{room_name} {act_type} 요약 리포트")

    def new_page_if_needed(y, need=30 * mm):
        if y < need:
            c.showPage()
            return H - PAD
        return y

    def draw_section_header(y, title, bg_rgb, fg_rgb=(1, 1, 1)):
        c.setFillColorRGB(*bg_rgb)
        c.roundRect(PAD, y - 6 * mm, CONTENT_W, 8 * mm, 3, fill=1, stroke=0)
        c.setFont(font_bold, 11)
        c.setFillColorRGB(*fg_rgb)
        c.drawString(PAD + 3 * mm, y - 3.5 * mm, title)
        return y - 10 * mm

    def draw_wrapped(text, x, y, font, size, max_w, line_h=6 * mm, color=(0.15, 0.15, 0.15)):
        c.setFont(font, size)
        c.setFillColorRGB(*color)
        for para in text.splitlines():
            words = para.split()
            cur = ""
            for word in words:
                test = (cur + " " + word).strip()
                if c.stringWidth(test, font, size) <= max_w:
                    cur = test
                else:
                    if cur:
                        c.drawString(x, y, cur)
                        y -= line_h
                    cur = word
            if cur:
                c.drawString(x, y, cur)
                y -= line_h
        return y

    y = H - PAD

    # ── 헤더 바 ──
    c.setFillColorRGB(0.082, 0.314, 0.627)
    c.rect(0, H - 22 * mm, W, 22 * mm, fill=1, stroke=0)
    c.setFont(font_bold, 15)
    c.setFillColorRGB(1, 1, 1)
    c.drawString(PAD, H - 13 * mm, f"말자취 Talk-Trace AI  |  {act_type} 요약 리포트")
    y = H - 28 * mm

    c.setFont(font_name, 10)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(PAD, y, f"방: {room_name}    |    주제: {current_topic}    |    생성: {get_kst_now().strftime('%Y-%m-%d %H:%M')}")
    y -= 6 * mm
    c.setStrokeColorRGB(0.82, 0.82, 0.82)
    c.line(PAD, y, W - PAD, y)
    y -= 7 * mm

    # ── AI 요약 섹션 ──
    sections = _parse_report(report_text)
    section_styles = {
        "핵심요약": (0.082, 0.314, 0.627),
        "베스트 학생": (0.086, 0.396, 0.204),
        "선정 이유": (0.573, 0.251, 0.055),
    }
    summary_idx = 0
    for label, content in sections:
        y = new_page_if_needed(y)
        if label == "핵심요약":
            summary_idx += 1
            display_label = f"핵심요약 {summary_idx}"
        else:
            display_label = label or "기타"
        bg = section_styles.get(label, (0.216, 0.255, 0.318))
        y = draw_section_header(y, display_label, bg)
        y = draw_wrapped(content, PAD + 3 * mm, y, font_name, 11, CONTENT_W - 6 * mm)
        y -= 4 * mm

    # ── 입장 변화 섹션 ──
    if not df_oc.empty and "initial_stance" in df_oc.columns and "final_stance" in df_oc.columns:
        both = df_oc[df_oc["initial_stance"].notna() & df_oc["final_stance"].notna()]
        if not both.empty:
            y = new_page_if_needed(y)
            c.setStrokeColorRGB(0.82, 0.82, 0.82)
            c.line(PAD, y, W - PAD, y)
            y -= 6 * mm
            y = draw_section_header(y, "입장 변화 현황", (0.36, 0.25, 0.58))

            # 매트릭스 요약
            cats = {
                "🔵 찬성 → 🔵 유지": both[(both["initial_stance"] == "🔵 찬성") & (both["final_stance"] == "🔵 찬성")],
                "🔵 찬성 → 🔴 반대": both[(both["initial_stance"] == "🔵 찬성") & (both["final_stance"] == "🔴 반대")],
                "🔴 반대 → 🔵 찬성": both[(both["initial_stance"] == "🔴 반대") & (both["final_stance"] == "🔵 찬성")],
                "🔴 반대 → 🔴 유지": both[(both["initial_stance"] == "🔴 반대") & (both["final_stance"] == "🔴 반대")],
            }
            for cat_label, cat_df in cats.items():
                y = new_page_if_needed(y)
                names = ", ".join(cat_df["student_name"].tolist()) if not cat_df.empty else "없음"
                line = f"{cat_label}  {len(cat_df)}명  ({names})"
                y = draw_wrapped(line, PAD + 3 * mm, y, font_name, 10, CONTENT_W - 6 * mm, 5.5 * mm)
            y -= 4 * mm

    # ── 발언 깊이 섹션 ──
    if depth_opinions:
        df_d = pd.DataFrame(depth_opinions)
        classified = df_d[df_d["depth_level"].notna()].copy()
        if not classified.empty:
            classified["depth_level"] = classified["depth_level"].astype(int)
            label_map = {1: "단순의견", 2: "근거제시", 3: "반박/심화질문", 4: "통합/종합"}
            y = new_page_if_needed(y)
            c.setStrokeColorRGB(0.82, 0.82, 0.82)
            c.line(PAD, y, W - PAD, y)
            y -= 6 * mm
            y = draw_section_header(y, "발언 깊이 분석", (0.153, 0.392, 0.255))

            # 분포
            dist = classified["depth_level"].map(label_map).value_counts()
            dist_line = "  /  ".join(f"{k}: {v}개" for k, v in dist.items())
            y = draw_wrapped(f"전체 분포  {dist_line}", PAD + 3 * mm, y, font_name, 10, CONTENT_W - 6 * mm, 5.5 * mm)
            y -= 3 * mm

            # 학생별 평균
            student_avg = (
                classified.groupby("student_name")["depth_level"]
                .mean().round(2).sort_values(ascending=False)
            )
            for name, avg in student_avg.items():
                y = new_page_if_needed(y)
                line = f"  {name}: 평균 {avg}단계"
                y = draw_wrapped(line, PAD + 3 * mm, y, font_name, 10, CONTENT_W - 6 * mm, 5.5 * mm)
            y -= 4 * mm

    c.save()
    return buf.getvalue()


# ── 리포트 파싱 ────────────────────────────────────────────────────────────────

def _parse_report(text: str) -> list:
    patterns = [
        (r"핵심요약\s*[123]", "핵심요약"),
        (r"베스트\s*학생", "베스트 학생"),
        (r"선정\s*이유", "선정 이유"),
    ]
    result = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        matched_label, content = None, line
        for pattern, label in patterns:
            m = re.match(rf"^({pattern})\s*[:\-：]?\s*(.+)", line, re.IGNORECASE)
            if m:
                matched_label, content = label, m.group(2).strip()
                break
        if matched_label:
            result.append((matched_label, content))
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


# ── 카드 UI ───────────────────────────────────────────────────────────────────

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


# ── 메인 섹션 렌더링 ───────────────────────────────────────────────────────────

@st.fragment
def render_summary_section(supabase, room_name, act_type, current_topic, df_all):
    st.subheader(f"📝 수업 종료 및 전체 {act_type} 요약 리포트")

    # 새로고침 시 Supabase에서 리포트 불러오기
    _cache_key = f'ai_report_text_{room_name}'
    if not st.session_state.get(_cache_key) and topic_ai_report_available():
        saved = fetch_ai_report(supabase, room_name)
        if saved:
            st.session_state[_cache_key] = saved

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

                    # 입장 변화 데이터
                    stance_summary = ""
                    if act_type == "토론" and opinion_changes_available() and stance_available():
                        df_oc = fetch_all_opinion_changes(supabase, room_name)
                        stance_summary = _build_stance_summary(df_oc)

                    # 발언 깊이 데이터
                    depth_summary = ""
                    if depth_level_available():
                        depth_opinions = fetch_opinions_for_depth(supabase, room_name)
                        depth_summary = _build_depth_summary(depth_opinions)

                    prompt = build_summary_prompt(
                        act_type, current_topic, full_history,
                        stance_summary=stance_summary,
                        depth_summary=depth_summary,
                    )
                    try:
                        res_text = generate_ai_response(
                            prompt, model_name=AI_MODEL_NAME, api_key=get_secret("GEMINI_API_KEY", ""),
                            log_message="AI 요약 리포트 생성 실패", room_name=room_name,
                        )
                    except Exception as e:
                        st.error(f"🚨 AI 호출 중 오류가 발생했습니다: {e}")
                        res_text = None
                    if res_text:
                        report_text = compact_ai_report_output(res_text)
                        st.session_state[_cache_key] = report_text
                        if topic_ai_report_available():
                            save_ai_report(supabase, room_name, report_text)
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

    report_text = st.session_state.get(_cache_key, '')
    if report_text:
        st.markdown("---")
        _render_report_cards(report_text)

        # PDF (입장변화 + 깊이 포함)
        try:
            df_oc = fetch_all_opinion_changes(supabase, room_name) if opinion_changes_available() else pd.DataFrame()
            depth_opinions = fetch_opinions_for_depth(supabase, room_name) if depth_level_available() else []
            pdf_bytes = _build_pdf(room_name, act_type, current_topic, report_text, df_oc, depth_opinions)
            st.download_button(
                "📄 리포트 PDF 다운로드 (입장변화 · 발언깊이 포함)",
                data=pdf_bytes,
                file_name=f"{room_name}_{act_type}_리포트_{get_kst_now().strftime('%Y%m%d_%H%M')}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.caption(f"PDF 생성 실패: {e}")
