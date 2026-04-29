import streamlit as st
import pandas as pd
import io
import html
import math
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
import logging
import plotly.express as px

from db import (
    approve_teacher_account,
    create_teacher_hint,
    debate_ip_column_available,
    delete_opinion_message,
    delete_student_record,
    destroy_room_data,
    ensure_db_login,
    fetch_student_records,
    fetch_live_messages,
    fetch_pending_teacher_accounts,
    fetch_room_entry_code,
    fetch_room_names,
    fetch_room_names_by_owner,
    fetch_teacher_account,
    fetch_topic_data,
    init_db,
    request_teacher_account,
    save_student_record,
    submit_opinion,
    topic_owner_column_available,
    topic_entry_code_column_available,
    using_service_role_key,
    upsert_topic_room,
)
from services.ai import generate_ai_response
from validators import (
    mask_ip_for_teacher,
    normalize_room_name,
    normalize_user_text,
    validate_entry_code,
    validate_opinion_content,
    validate_room_name,
    validate_student_name,
    validate_teacher_credential,
    with_fallback_author_role,
)

# ==========================================
# [0] 로깅 설정
# ==========================================
logger = logging.getLogger("talk_trace_ai")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

# ==========================================
# [1] 앱 설정 및 데이터베이스 연결
# ==========================================
DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
DISPLAY_DATETIME_FMT = "%Y-%m-%d %p %I:%M:%S"
AI_MODEL_NAME = "gemini-2.5-flash"
LIVE_BOARD_FETCH_LIMIT = 300
DASHBOARD_FETCH_LIMIT = 2000
RECORDS_FETCH_LIMIT = 500
LIVE_REFRESH_INTERVAL = "5s"
def _get_secret(key: str, default=None):
    """환경변수(HF) → st.secrets(Streamlit Cloud) 순서로 읽습니다."""
    env_val = os.environ.get(key, "").strip()
    if env_val:
        return env_val
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default

import os
AI_HINT_ENABLED = _get_secret("AI_HINT_ENABLED", True)
ROOM_DESTROY_ENABLED = _get_secret("ROOM_DESTROY_ENABLED", True)
AUTO_JOIN_ON_REFRESH = _get_secret("AUTO_JOIN_ON_REFRESH", False)
MAX_ROOM_NAME_LEN = 60
MAX_STUDENT_NAME_LEN = 30
MAX_TOPIC_LEN = 120
MAX_ENTRY_CODE_LEN = 60
UI_FONT_FAMILY = "sans-serif"

supabase = init_db()
ensure_db_login(supabase)

def get_kst_now():
    return datetime.utcnow() + timedelta(hours=9)

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
    logger.info("AUDIT event=%s room=%s actor=%s role=%s extra=%s", event, room_name, actor_name, role, extra)

def build_word_frequencies(text_series):
    tokens = []
    stopwords = {
        "그리고", "하지만", "그래서", "정말", "제가", "저는", "너무", "이번", "지금",
        "그냥", "대한", "대한해", "같은", "합니다", "입니다", "있는", "없는", "수업",
        "토론", "토의", "의견", "생각", "내용", "때문", "하면", "하면요", "입니다요", "있다", "않으면", "많은"
    }
    particle_suffixes = [
        "에게서", "으로는", "이라고", "라면", "처럼", "까지는", "으로도", "에서", "에게", "으로", "로써",
        "로서", "보다", "까지", "부터", "만큼", "이나", "라도", "이며", "이고", "에서", "으로", "이라",
        "라고", "와", "과", "을", "를", "이", "가", "은", "는", "에", "도", "만", "로", "랑", "나"
    ]
    def normalize_token(token):
        cleaned = re.sub(r"^[^\w가-힣]+|[^\w가-힣]+$", "", token)
        if len(cleaned) < 2:
            return ""
        normalized = cleaned
        for suffix in particle_suffixes:
            if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
                normalized = normalized[: -len(suffix)]
                break
        return normalized
    for content in text_series.fillna("").astype(str):
        for token in content.replace("\n", " ").split():
            cleaned = normalize_token(token)
            if len(cleaned) < 2:
                continue
            if cleaned in stopwords:
                continue
            tokens.append(cleaned)
    return Counter(tokens)

def build_circular_wordcloud_html(frequencies, max_words=75, width=760, height=520):
    if not frequencies:
        return ""
    sorted_words = sorted(frequencies.items(), key=lambda item: (-item[1], item[0]))[:max_words]
    max_count = sorted_words[0][1]
    min_count = sorted_words[-1][1]
    palette = ["#00695C", "#0077B6", "#0B3D91", "#1F8EFA", "#A3CFE2"]
    cx, cy = width / 2, height / 2
    placed_rects = []
    svg_text_nodes = []
    def estimate_text_units(word):
        units = 0.0
        for ch in word:
            code = ord(ch)
            if 0xAC00 <= code <= 0xD7A3: units += 1.0
            elif 0x3130 <= code <= 0x318F: units += 0.95
            elif 0x4E00 <= code <= 0x9FFF: units += 1.0
            elif ch.isascii() and (ch.isalpha() or ch.isdigit()): units += 0.62
            else: units += 0.75
        return max(units, 1.0)
    def overlaps(rect):
        x, y, w, h = rect
        padding = 2
        for ox, oy, ow, oh in placed_rects:
            if not (x + w + padding < ox or ox + ow + padding < x or y + h + padding < oy or oy + oh + padding < y):
                return True
        return False
    def is_inside_canvas(x, y, w, h):
        margin = 10
        return x >= margin and y >= margin and (x + w) <= (width - margin) and (y + h) <= (height - margin)
    for index, (word, count) in enumerate(sorted_words):
        if max_count == min_count:
            font_size = 28
        else:
            ratio = (count - min_count) / (max_count - min_count)
            eased_ratio = ratio ** 0.85
            font_size = int(18 + eased_ratio * 86)
        font_size = min(font_size, 140)
        color = palette[index % len(palette)]
        text_units = estimate_text_units(word)
        text_width = max(32, font_size * (text_units + 0.62))
        text_height = max(24, font_size * 1.22)
        placed = False
        for step in range(1, 3200):
            angle = step * 0.4 + index * 0.18
            spiral_radius = 2 + step * 0.42
            x = cx + spiral_radius * math.cos(angle) - text_width / 2
            y = cy + spiral_radius * math.sin(angle) - text_height / 2
            rect = (x, y, text_width, text_height)
            if not is_inside_canvas(x, y, text_width, text_height): continue
            if overlaps(rect): continue
            placed_rects.append(rect)
            safe_word = html.escape(word)
            tx, ty = x + 1.5, y + text_height * 0.84
            svg_text_nodes.append(
                f"<text x='{tx:.1f}' y='{ty:.1f}' fill='{color}' font-size='{font_size}' "
                f"font-weight='800' letter-spacing='-0.01em'>{safe_word}</text>"
            )
            placed = True
            break
        if not placed:
            continue
    return (
        "<div style='padding:10px; border:1px solid #e9e9e9; border-radius:10px; background:#f3f5f7;'>"
        f"<svg viewBox='0 0 {width} {height}' style='width:100%; height:auto; display:block;' "
        "xmlns='http://www.w3.org/2000/svg'>"
        "<rect x='0' y='0' width='100%' height='100%' fill='#f3f5f7' />"
        + "".join(svg_text_nodes) +
        "</svg></div>"
    )

def render_admin_approval_panel():
    st.subheader("📝 교사 계정 승인")
    pending_accounts = fetch_pending_teacher_accounts(supabase)
    if not pending_accounts:
        st.info("승인 대기 중인 교사 계정이 없습니다.")
        return
    for pending in pending_accounts:
        acc_id = pending.get("id")
        pending_teacher_id = pending.get("teacher_id", "")
        requested_at = pending.get("requested_at", "") or "-"
        c_left, c_right = st.columns([3, 2])
        with c_left:
            st.write(f"ID: {pending_teacher_id}")
        with c_right:
            st.caption(f"신청 시각: {format_kst_datetime(requested_at)}")
            if st.button("승인", key=f"approve_{acc_id}"):
                res = approve_teacher_account(supabase, acc_id, get_kst_now_str())
                if res is not None:
                    st.success(f"{pending_teacher_id} 계정을 승인했습니다.")
                    st.rerun()

# ==========================================
# [2] 앱 기본 설정 및 세션/CSS
# ==========================================
st.set_page_config(page_title="말자취(Talk-Trace) AI", layout="wide")
st.markdown(
    """
    <style>
    .records-db-table-wrap { overflow-x: auto; border: 1px solid #e6e6e6; border-radius: 10px; background: #fff; }
    .records-db-table-wrap table { width: 100%; border-collapse: collapse; table-layout: fixed; }
    .records-db-table-wrap th, .records-db-table-wrap td { border-bottom: 1px solid #efefef; border-right: 1px solid #efefef; padding: 10px 12px; text-align: left; vertical-align: top; }
    .records-db-table-wrap th:last-child, .records-db-table-wrap td:last-child { border-right: none; }
    .records-db-table-wrap th { white-space: nowrap; font-weight: 700; }
    .records-db-table-wrap th:nth-child(1), .records-db-table-wrap td:nth-child(1) { width: 5%; white-space: nowrap; }
    .records-db-table-wrap th:nth-child(2), .records-db-table-wrap td:nth-child(2) { width: 15%; white-space: nowrap; }
    .records-db-table-wrap th:nth-child(3), .records-db-table-wrap td:nth-child(3) { width: 12%; white-space: nowrap; }
    .records-db-table-wrap th:nth-child(4), .records-db-table-wrap td:nth-child(4) { width: 68%; white-space: pre-wrap; word-break: break-word; }
    [data-testid="stDecoration"] { display: none !important; }
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stMainBlockContainer"],
    [data-testid="stAppViewBlockContainer"], [data-testid="stFragment"],
    [data-testid="stVerticalBlock"], [data-testid="stElementContainer"],
    [data-testid="stExpander"], details, summary,
    *[data-stale="true"], div[data-stale="true"] {
        opacity: 1 !important; transition: none !important; filter: none !important; -webkit-filter: none !important;
    }
    .stTextArea textarea, .stTextInput input, .stSelectbox, .stRadio label,
    .stMarkdown p, div[data-testid="stChatMessageContent"] { font-size: 18px !important; }
    .stAlert p { font-size: 20px !important; font-weight: bold; }
    </style>
    """,
    unsafe_allow_html=True
)

if 'reset_key' not in st.session_state: st.session_state['reset_key'] = 0
if 'ai_result_text' not in st.session_state: st.session_state['ai_result_text'] = ""
if 'ai_hint_text' not in st.session_state: st.session_state['ai_hint_text'] = ""
if 'ai_report_text' not in st.session_state: st.session_state['ai_report_text'] = ""
if 'page' not in st.session_state: st.session_state['page'] = "home"
if 'current_room' not in st.session_state: st.session_state['current_room'] = ""
if 'joined' not in st.session_state: st.session_state['joined'] = False
if 'teacher_auth' not in st.session_state: st.session_state['teacher_auth'] = False
if 'admin_auth' not in st.session_state: st.session_state['admin_auth'] = False
if 'teacher_id' not in st.session_state: st.session_state['teacher_id'] = ""
if 'is_working' not in st.session_state: st.session_state['is_working'] = False
if 'ai_hint_manual_mode' not in st.session_state: st.session_state['ai_hint_manual_mode'] = False

def set_working():
    st.session_state['is_working'] = True
    st.toast("요청을 받았습니다! 서버가 분석을 준비합니다... 🚀", icon="⏳")

def reset_joined_state():
    st.session_state['joined'] = False
    st.session_state['teacher_auth'] = False
    st.session_state['admin_auth'] = False
    st.session_state['teacher_id'] = ""

def redirect_from_admin_page_if_needed():
    if st.session_state.get('page') == "admin_approval" and not st.session_state.get('admin_auth', False):
        st.session_state['page'] = "lobby"

def to_bool_flag(value):
    if isinstance(value, bool): return value
    if value is None: return False
    return str(value).strip().lower() in {"true", "t", "1", "yes", "y", "on"}

def compact_ai_report_output(text):
    raw_lines = [str(line).strip() for line in str(text or "").splitlines()]
    cleaned = [line for line in raw_lines if line and not line.startswith("#")]
    if not cleaned: return ""
    report_labels = ("핵심요약 1:", "핵심요약 2:", "핵심요약 3:", "베스트 학생:", "선정 이유:")
    normalized_text = " ".join(cleaned)
    if report_labels[0] in normalized_text:
        for label in report_labels[1:]:
            normalized_text = normalized_text.replace(f" {label}", f"\n{label}")
            normalized_text = normalized_text.replace(label, f"\n{label}")
    normalized_lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
    return "\n".join(normalized_lines[:5])

# ==========================================
# [3] 홈/네비게이션
# ==========================================
if st.session_state['page'] != "home":
    col_home_btn, _ = st.columns([1, 7])
    with col_home_btn:
        if st.button("🏠 홈", use_container_width=True):
            st.session_state['page'] = "home"
            st.session_state['joined'] = False
            st.session_state['teacher_auth'] = False
            st.rerun()

if st.session_state['page'] == "home":
    st.title("🏠 말자취(Talk-Trace) AI 홈")
    st.markdown(
        """
        ### 사용 방법 (간단 안내)
        1. **대기실로 이동** 버튼을 눌러 시작합니다.
        2. 왼쪽 사이드바에서 **학생/교사 모드**를 선택합니다.
        3. 접속할 **토론/토의방**을 선택하고 입장합니다.
        4. 주제에 맞게 의견을 작성하고 제출하면 실시간 보드에 반영됩니다.
        ---
        - 교사 모드에서는 방 개설/관리 및 대시보드 기능을 사용할 수 있습니다.
        - 언제든 왼쪽 상단의 **🏠 홈** 버튼으로 이 화면으로 돌아올 수 있습니다.
        """
    )
    if st.button("🚀 대기실로 이동", type="primary", use_container_width=True):
        st.session_state['page'] = "lobby"
        st.rerun()
    st.stop()

# ==========================================
# [4] 사이드바
# ==========================================
with st.sidebar:
    st.header("👤 접속 권한")
    user_role = st.radio("모드 선택", ["학생", "교사"], on_change=reset_joined_state)
    st.divider()

    try:
        all_rooms = fetch_room_names(supabase)
    except Exception:
        all_rooms = []

    room_name = ""
    teacher_auth = False
    admin_auth = False
    student_number = ""
    teacher_id_for_scope = st.session_state.get("teacher_id", "")

    if user_role == "교사":
        auth_mode = st.radio("교사 계정", ["로그인", "ID/PW 신청"], horizontal=True)

        if auth_mode == "로그인":
            with st.form("teacher_login_form"):
                teacher_id_input = st.text_input("교사 ID", key="teacher_id_input")
                teacher_pw_input = st.text_input("교사 PW", type="password", key="teacher_pw_input")
                login_submitted = st.form_submit_button("교사 로그인", use_container_width=True)

            if login_submitted:
                id_ok, safe_teacher_id, id_error_code, id_error_message = validate_teacher_credential(teacher_id_input, field_name="교사 ID", max_len=60)
                pw_ok, safe_pw, pw_error_code, pw_error_message = validate_teacher_credential(teacher_pw_input, field_name="교사 PW", max_len=60)
                if not id_ok:
                    st.error(f"❌ {id_error_message} ({id_error_code})")
                    st.stop()
                if not pw_ok:
                    st.error(f"❌ {pw_error_message} ({pw_error_code})")
                    st.stop()
                account = fetch_teacher_account(supabase, safe_teacher_id)
                if isinstance(account, dict) and account.get("_query_failed"):
                    st.session_state['teacher_auth'] = False
                    st.session_state['admin_auth'] = False
                    st.session_state['teacher_id'] = ""
                    redirect_from_admin_page_if_needed()
                    st.error("🚨 교사 계정 조회에 실패했습니다. Supabase RLS 정책/권한 및 DB 연결 상태를 확인해 주세요.")
                elif not account:
                    st.session_state['teacher_auth'] = False
                    st.session_state['admin_auth'] = False
                    st.session_state['teacher_id'] = ""
                    redirect_from_admin_page_if_needed()
                    st.error("🚨 등록되지 않은 교사 ID입니다.")
                    if not using_service_role_key():
                        st.warning(
                            "⚠️ 현재 앱이 SERVICE ROLE KEY 없이 동작 중입니다. "
                            "teacher_accounts 테이블에 RLS 정책이 없으면 Data API 조회 결과가 0건으로 나와 "
                            "등록된 계정도 미등록으로 보일 수 있습니다."
                        )
                    try:
                        supabase_url = str(_get_secret("SUPABASE_URL", ""))
                        project_ref = supabase_url.split("//", 1)[-1].split(".", 1)[0] if supabase_url else ""
                        if project_ref:
                            st.caption(f"현재 앱 연결 DB 프로젝트: `{project_ref}`")
                    except Exception:
                        pass
                elif account.get("teacher_pw") != safe_pw:
                    st.session_state['teacher_auth'] = False
                    st.session_state['admin_auth'] = False
                    st.session_state['teacher_id'] = ""
                    redirect_from_admin_page_if_needed()
                    st.error("❌ 비밀번호가 일치하지 않습니다.")
                elif not account.get("is_approved"):
                    st.session_state['teacher_auth'] = False
                    st.session_state['admin_auth'] = False
                    st.session_state['teacher_id'] = ""
                    redirect_from_admin_page_if_needed()
                    st.warning("⏳ 최고관리자 승인 후 로그인할 수 있습니다.")
                else:
                    st.session_state['teacher_auth'] = True
                    st.session_state['admin_auth'] = to_bool_flag(account.get("is_admin", False))
                    st.session_state['teacher_id'] = safe_teacher_id
                    redirect_from_admin_page_if_needed()
                    if st.session_state['admin_auth']:
                        st.session_state['page'] = "admin_approval"
                        st.toast("✅ 관리자 계정 로그인 성공", icon="✅")
                        st.rerun()
                    else:
                        st.toast("✅ 교사 로그인 성공", icon="✅")
        else:
            req_teacher_id = st.text_input("신청할 교사 ID", key="req_teacher_id")
            req_teacher_pw = st.text_input("신청할 교사 PW", type="password", key="req_teacher_pw")
            if st.button("교사 계정 신청", type="primary", use_container_width=True):
                id_ok, safe_id, id_error_code, id_error_message = validate_teacher_credential(req_teacher_id, field_name="교사 ID", max_len=60)
                pw_ok, safe_pw, pw_error_code, pw_error_message = validate_teacher_credential(req_teacher_pw, field_name="교사 PW", max_len=60)
                if not id_ok:
                    st.error(f"❌ {id_error_message} ({id_error_code})")
                elif not pw_ok:
                    st.error(f"❌ {pw_error_message} ({pw_error_code})")
                elif fetch_teacher_account(supabase, safe_id):
                    st.warning("이미 존재하는 ID입니다. 다른 ID를 사용해 주세요.")
                else:
                    req_res = request_teacher_account(supabase, safe_id, safe_pw)
                    if req_res is not None:
                        st.success("신청 완료! 최고관리자 승인 후 로그인할 수 있습니다.")

        teacher_auth = st.session_state['teacher_auth']
        admin_auth = st.session_state['admin_auth']
        teacher_id_for_scope = st.session_state.get("teacher_id", "")

        if teacher_auth:
            st.caption(f"🔐 {teacher_id_for_scope} 로그인 중")
            if st.button("🚪 로그아웃", use_container_width=True):
                st.session_state['teacher_auth'] = False
                st.session_state['admin_auth'] = False
                st.session_state['teacher_id'] = ""
                st.session_state['joined'] = False
                st.session_state['page'] = "lobby"
                st.rerun()
            st.divider()

        if teacher_auth and admin_auth:
            st.caption("관리자 바로가기")
            if st.button("📝 ID 요청 수락", use_container_width=True):
                st.session_state['page'] = "admin_approval"
                st.rerun()
            if st.button("🚪 말자취(Talk-Trace) AI 대기실", use_container_width=True):
                st.session_state['page'] = "lobby"
                st.rerun()
            st.divider()

        if teacher_auth:
            if admin_auth:
                existing_rooms = all_rooms
            else:
                if topic_owner_column_available():
                    existing_rooms = fetch_room_names_by_owner(supabase, teacher_id_for_scope)
                else:
                    existing_rooms = []
                    st.warning("교사별 방 조회를 위해 topic.created_by_teacher_id(권장) 또는 topic.created_by 컬럼이 필요합니다.")

            room_opt = st.radio("방 관리", ["기존 방 선택", "새 방 만들기"])
            if room_opt == "기존 방 선택" and existing_rooms:
                room_name = st.selectbox("토론/토의방 목록", existing_rooms)
            else:
                new_room = st.text_input("새로 만들 방 이름 (예: 1학년 3반)")
                new_title = st.text_input("주제 직접 입력 (예: 인공지능 윤리)")
                new_mode = st.radio("진행 방식", ["⚔️ 찬반 토론", "💡 자유 토의"], horizontal=True)
                new_pw = st.text_input("🔒 학생 입장용 암호 (비워두면 공개방)")
                if st.button("새 방 개설하기", type="primary"):
                    room_ok, safe_new_room, room_error_code, room_error_message = validate_room_name(new_room, max_len=MAX_ROOM_NAME_LEN)
                    title_ok, safe_new_title, title_error_code, title_error_message = validate_opinion_content(new_title, max_len=MAX_TOPIC_LEN)
                    entry_ok, safe_new_pw, entry_error_code, entry_error_message = validate_entry_code(new_pw, max_len=MAX_ENTRY_CODE_LEN)
                    can_store_room_pw = topic_entry_code_column_available()
                    if not room_ok:
                        st.error(f"❌ {room_error_message} ({room_error_code})")
                    elif not title_ok:
                        st.error(f"❌ {title_error_message} ({title_error_code})")
                    elif not entry_ok:
                        st.error(f"❌ {entry_error_message} ({entry_error_code})")
                    elif safe_new_pw and not can_store_room_pw:
                        st.error("현재 DB 구조에서는 방 비밀번호 저장을 지원하지 않습니다.")
                    elif safe_new_room and safe_new_title:
                        res = upsert_topic_room(
                            supabase=supabase, room_name=safe_new_room, title=safe_new_title,
                            mode=new_mode, entry_code=safe_new_pw, created_by=teacher_id_for_scope,
                        )
                        if res is not None:
                            st.success(f"'{safe_new_room}' 방이 개설되었습니다! '기존 방 선택'을 눌러 입장하세요.")
                    room_name = ""
    else:
        st.session_state['teacher_auth'] = False
        st.session_state['admin_auth'] = False
        st.session_state['teacher_id'] = ""
        redirect_from_admin_page_if_needed()
        student_number = st.text_input("학번", key="student_number_input", placeholder="예: 1101")
        if all_rooms:
            room_name = st.selectbox("🏠 접속할 방 선택", all_rooms)
        else:
            st.warning("선생님이 아직 열어둔 방이 없습니다.")
            room_name = ""

    if user_role == "학생":
        student_name = normalize_user_text(student_number, max_len=20)
    else:
        student_name = "교사"

    if room_name and room_name != st.session_state['current_room']:
        prev_room = st.session_state['current_room']
        st.session_state['current_room'] = room_name
        st.session_state['ai_hint_text'] = ""
        st.session_state['ai_report_text'] = ""
        st.session_state['ai_result_text'] = ""
        if st.session_state['joined']:
            st.session_state['joined'] = False
            log_audit("room_switched_to_lobby", room_name=room_name, actor_name=student_name, role=user_role, previous_room=prev_room)
            st.rerun()

    if st.session_state['joined']:
        st.divider()
        if st.button("🚪 방 나가기 (대기실로)"):
            st.session_state['joined'] = False
            st.rerun()

if st.session_state['page'] == "admin_approval":
    if not (user_role == "교사" and teacher_auth and admin_auth):
        st.session_state['page'] = "lobby"
        st.toast("관리자 페이지에서 나와 대기실로 이동했습니다.", icon="ℹ️")
        st.rerun()
    st.title("🛠️ 관리자 ID 요청 수락 페이지")
    render_admin_approval_panel()
    st.stop()

# ==========================================
# [5] 대기실
# ==========================================
if not st.session_state['joined']:
    st.title("🚪 말자취(Talk-Trace) AI 대기실")
    if user_role == "교사" and not teacher_auth:
        st.warning("🚨 승인된 교사 계정으로 로그인해야 입장할 수 있습니다.")
    elif not room_name.strip():
        st.error("🚨 접속할 방을 먼저 선택해 주세요.")
    else:
        if user_role == "학생":
            student_pw = st.text_input("🔒 방 입장 암호 (공개방이면 비워두세요)", type="password")
            if st.button(f"🚀 '{room_name}' 입장하기", type="primary", use_container_width=True):
                real_pw = fetch_room_entry_code(supabase, room_name)
                if real_pw is None:
                    st.error("🚨 방 암호 정보를 확인할 수 없어 입장을 차단했습니다. 잠시 후 다시 시도해 주세요.")
                elif real_pw and student_pw != real_pw:
                    st.error("❌ 암호가 틀렸습니다.")
                elif not normalize_user_text(student_number, max_len=20):
                    st.error("❌ 학번을 입력해야 입장할 수 있습니다.")
                else:
                    st.session_state['joined'] = True
                    st.rerun()
        else:
            if AUTO_JOIN_ON_REFRESH and teacher_auth:
                st.session_state['joined'] = True; st.rerun()
            if st.button(f"🚀 '{room_name}' 관리자 권한으로 입장", type="primary", use_container_width=True):
                st.session_state['joined'] = True; st.rerun()
    st.stop()

# ==========================================
# [6] 메인 화면 (의견 입력부)
# ==========================================
topic_data = fetch_topic_data(supabase, room_name)
current_topic = topic_data.get('title', "자유 주제로 대화해 봅시다.")
current_mode = topic_data.get('mode', "⚔️ 찬반 토론")
act_type = "토론" if "토론" in current_mode else "토의"

st.title(f"🎙️ 말자취(Talk-Trace) AI [{room_name}]")
st.info(f"**현재 주제:** {current_topic} ({current_mode})")

st.subheader("🗣️ 내 의견 작성")
col_input, col_stt = st.columns([4, 1])
with col_input:
    user_input = st.text_area("의견을 입력하세요", key=f"input_{st.session_state['reset_key']}", height=80, label_visibility="collapsed")
    opts = ["🔵 찬성", "🔴 반대"] if current_mode == "⚔️ 찬반 토론" else ["💡 아이디어", "➕ 보충", "❓ 질문"]
    sentiment = st.radio("의견 성격", opts, horizontal=True)

with col_stt:
    st.components.v1.html(
        """
        <button id="stt-btn" style="width:100%; height:80px; font-weight:bold; border-radius:10px; background-color:#e8f0fe; border:1px solid #1a73e8; color:#1a73e8; cursor:pointer;">🎤 음성 입력 시작</button>
        <p id="status" style="font-size:11px; color:gray; text-align:center; margin-top:5px;">대기 중...</p>
        <script>
            const btn = document.getElementById('stt-btn');
            const status = document.getElementById('status');
            const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
            recognition.lang = 'ko-KR';
            let isRecognizing = false;
            btn.onclick = () => { if (!isRecognizing) recognition.start(); else recognition.stop(); };
            recognition.onstart = () => { isRecognizing = true; status.innerText = "듣는 중..."; btn.style.backgroundColor = "#ff4b4b"; btn.style.color = "white"; btn.innerHTML = "🛑 음성 입력 중지"; };
            recognition.onresult = (event) => {
                const text = event.results[0][0].transcript;
                const textArea = window.parent.document.querySelector('textarea[aria-label="의견을 입력하세요"]');
                if (textArea) {
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
                    nativeInputValueSetter.call(textArea, textArea.value + " " + text);
                    textArea.dispatchEvent(new Event('input', { bubbles: true }));
                    status.innerText = "입력 완료!";
                }
            };
            recognition.onend = () => { isRecognizing = false; setTimeout(() => { status.innerText = "대기 중..."; btn.style.backgroundColor = "#e8f0fe"; btn.style.color = "#1a73e8"; btn.innerHTML = "🎤 음성 입력 시작"; }, 1500); };
        </script>
        """, height=120
    )

if st.button("의견 제출", use_container_width=True, type="primary"):
    input_ok, safe_input, input_error_code, input_error_message = validate_opinion_content(user_input, max_len=700)
    student_ok, safe_student_name, student_error_code, student_error_message = validate_student_name(student_name, max_len=MAX_STUDENT_NAME_LEN)
    student_number_ok, safe_student_number, student_number_error_code, student_number_error_message = validate_student_name(student_number, max_len=20)
    if not student_number_ok and user_role == "학생":
        st.error(f"❌ {student_number_error_message} ({student_number_error_code})")
        st.stop()
    if user_role == "학생" and (not safe_student_name or safe_student_name == "익명"):
        safe_student_name = safe_student_number or "학번미입력"
    if input_ok and safe_input:
        now = get_kst_now_str()
        author_role_for_submit = "교사" if user_role == "교사" else "학생"
        client_ip = get_client_ip()
        insert_payload = {
            "room_name": room_name, "timestamp": now, "student_name": safe_student_name,
            "content": safe_input, "sentiment": sentiment, "author_role": author_role_for_submit
        }
        if debate_ip_column_available() and client_ip:
            insert_payload["ip_address"] = client_ip
        try:
            res = submit_opinion(supabase, insert_payload)
            if res is None: st.stop()
            log_audit("opinion_submitted", room_name=room_name, actor_name=safe_student_name, role=author_role_for_submit, sentiment=sentiment, client_ip=client_ip if client_ip else "N/A")
            st.session_state['reset_key'] += 1
            st.rerun()
        except Exception as e:
            st.error(f"저장 실패: {e}")
    else:
        st.warning(f"{input_error_message} ({input_error_code})")

st.divider()

# ==========================================
# [7] 실시간 업데이트 영역
# ==========================================
def live_chat_board_core():
    # ✅ Phase 2 핵심: fetch_live_messages 이중 호출 제거
    # 기존: limit=300, limit=2000 각각 2회 호출 → Supabase 요청 2배 낭비
    # 개선: DASHBOARD_FETCH_LIMIT(2000)으로 1회만 호출 후 보드/통계 모두 재사용
    all_df = with_fallback_author_role(
        fetch_live_messages(supabase, room_name, DASHBOARD_FETCH_LIMIT)
    )
    # 실시간 보드용: 최신 300건 슬라이싱 (id desc 정렬이므로 앞에서 자름)
    opinion_df = all_df.head(LIVE_BOARD_FETCH_LIMIT) if not all_df.empty else all_df
    # 통계용: 전체 2000건 사용
    stats_opinion_df = all_df

    with st.expander("📊 실시간 의견 통계 보기 (클릭하여 펼치기)"):
        if not stats_opinion_df.empty:
            left_col, right_col = st.columns(2)
            with left_col:
                st.caption("감정 분포 그래프")
                live_pie_fig = px.pie(stats_opinion_df, names="sentiment", hole=0.4, height=320)
                live_pie_fig.update_layout(font={"family": UI_FONT_FAMILY})
                st.plotly_chart(live_pie_fig, use_container_width=True, config={'displayModeBar': False, 'scrollZoom': False})
            with right_col:
                st.caption("누적 토의/토론 워드클라우드")
                frequencies = build_word_frequencies(stats_opinion_df["content"])
                if frequencies:
                    st.markdown(build_circular_wordcloud_html(frequencies), unsafe_allow_html=True)
                    top_words = ", ".join([f"{word}({count})" for word, count in frequencies.most_common(8)])
                    st.caption(f"상위 키워드: {top_words}")
                else:
                    st.info("워드클라우드를 만들 단어가 아직 부족합니다.")
        else:
            st.write("데이터 수집 중...")

    col_board_title, col_board_ref = st.columns([8, 2])
    with col_board_title:
        st.subheader(f"💬 실시간 {act_type} 보드")
    with col_board_ref:
        if user_role == "교사" and teacher_auth:
            st.button("🔄 실시간 보드 새로고침", use_container_width=True, key="refresh_chat_board")

    if not opinion_df.empty:
        teacher_df = opinion_df[opinion_df['student_name'].str.contains('선생님', na=False)]
        if not teacher_df.empty:
            st.success(f"👨‍🏫 **선생님의 생각 힌트!** ➡️ {teacher_df.iloc[0]['content']}")

        student_df = opinion_df[~opinion_df['student_name'].str.contains('선생님', na=False)]

        def delete_chat_msg(msg_id):
            try:
                if delete_opinion_message(supabase, msg_id) is None: return
                log_audit("chat_deleted", room_name=room_name, actor_name=student_name, role=user_role, message_id=msg_id)
                st.toast("의견이 즉시 삭제되었습니다.", icon="🗑️")
            except Exception as e:
                st.error(f"삭제 실패: {e}")

        def render_msg(row):
            formatted_timestamp = format_kst_datetime(row.get("timestamp", ""))
            if user_role == "교사" and teacher_auth:
                c_name, c_btn = st.columns([5, 1])
                with c_name:
                    st.markdown(f"**{row['student_name']}** <span style='color:gray; font-size:14px;'>{formatted_timestamp}</span>", unsafe_allow_html=True)
                    row_ip = str(row.get("ip_address", "")).strip() if hasattr(row, "get") else ""
                    if row_ip:
                        st.caption(f"IP: {mask_ip_for_teacher(row_ip)}")
                with c_btn:
                    st.button("❌", key=f"del_{row['id']}", help="강제 삭제", on_click=delete_chat_msg, args=(row['id'],))
                st.info(row['content'])
            else:
                st.markdown(f"**{row['student_name']}** <span style='color:gray; font-size:14px;'>{formatted_timestamp}</span>", unsafe_allow_html=True)
                st.info(row['content'])
            st.write("")

        if current_mode == "⚔️ 찬반 토론":
            col_pro, col_con = st.columns(2)
            with col_pro:
                st.markdown("### 🔵 찬성 측")
                with st.container(height=450):
                    for _, row in student_df[student_df['sentiment'] == '🔵 찬성'].iterrows(): render_msg(row)
            with col_con:
                st.markdown("### 🔴 반대 측")
                with st.container(height=450):
                    for _, row in student_df[student_df['sentiment'] == '🔴 반대'].iterrows(): render_msg(row)
        else:
            col_idea, col_plus, col_q = st.columns(3)
            with col_idea:
                st.markdown("### 💡 아이디어")
                with st.container(height=450):
                    for _, row in student_df[student_df['sentiment'] == '💡 아이디어'].iterrows(): render_msg(row)
            with col_plus:
                st.markdown("### ➕ 보충")
                with st.container(height=450):
                    for _, row in student_df[student_df['sentiment'] == '➕ 보충'].iterrows(): render_msg(row)
            with col_q:
                st.markdown("### ❓ 질문")
                with st.container(height=450):
                    for _, row in student_df[student_df['sentiment'] == '❓ 질문'].iterrows(): render_msg(row)
    else:
        st.info(f"아직 대화가 없습니다. 첫 {act_type} 의견을 남겨주세요!")

@st.fragment(run_every=LIVE_REFRESH_INTERVAL)
def live_chat_board_auto():
    live_chat_board_core()

def live_chat_board_manual():
    live_chat_board_core()

if st.session_state.get('is_working', False):
    live_chat_board_manual()
else:
    live_chat_board_auto()

# ==========================================
# [8] 교사 전용 대시보드
# ==========================================
if user_role == "교사" and teacher_auth:
    st.divider()
    col_dash_title, col_dash_refresh = st.columns([8, 2])
    with col_dash_title:
        st.header("👨‍🏫 교사 관리 대시보드")
    with col_dash_refresh:
        if st.button("🔄 대시보드 수동 새로고침", use_container_width=True):
            st.rerun()

    if admin_auth:
        render_admin_approval_panel()
        st.divider()

    df_all = with_fallback_author_role(fetch_live_messages(supabase, room_name, DASHBOARD_FETCH_LIMIT))

    st.subheader("📊 학생 참여도 현황")
    if not df_all.empty:
        student_only_df = df_all[(df_all['author_role'] == '학생') & ~df_all['student_name'].str.contains('익명|AI', na=False, regex=True)].copy()
        if not student_only_df.empty:
            counts = student_only_df['student_name'].astype(str).value_counts().reset_index()
            counts.columns = ['학생 이름', '참여 횟수']
            counts['학생 이름'] = counts['학생 이름'] + " "
            fig = px.bar(counts, x='학생 이름', y='참여 횟수', text='참여 횟수', color='학생 이름')
            fig.update_xaxes(type='category', title="")
            fig.update_layout(yaxis_title="의견 수", dragmode=False, showlegend=False, font={"family": UI_FONT_FAMILY})
            st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False})
        else: st.info("실명 참여 데이터가 없습니다.")
    else: st.info(f"{act_type} 데이터가 없습니다.")

    st.divider()

    @st.fragment
    def teacher_hint_section():
        st.subheader(f"💡 AI {act_type} 촉진 (Teacher-in-the-loop)")
        st.info("AI 제안을 수정 후 전송하세요.")

        def send_hint():
            val = st.session_state.get('hint_input_widget', '').strip()
            if val:
                now = get_kst_now_str()
                try:
                    res = create_teacher_hint(supabase, {
                        "room_name": room_name, "timestamp": now, "student_name": "👨‍🏫 선생님 (AI 보조)",
                        "content": val, "sentiment": "❓ 질문", "author_role": "교사"
                    })
                    if res is None: return
                    log_audit("teacher_hint_sent", room_name=room_name, actor_name=student_name, role=user_role)
                    st.session_state['hint_input_widget'] = ""
                except Exception as e:
                    st.error(f"힌트 전송 실패: {e}")

        if AI_HINT_ENABLED:
            if st.button("🪄 AI 힌트 초안 생성", use_container_width=True):
                st.toast("👀 AI가 대화 맥락을 읽고 있습니다...", icon="⏳")
                with st.spinner("✍️ 예리한 질문을 작성하고 있습니다..."):
                    context = "\n".join(df_all['content'].tail(5).tolist()) if not df_all.empty else "대화 없음"
                    prompt = f"당신은 고등학교 {act_type} 조력자입니다. '{current_topic}' 주제로 {act_type} 중입니다. 학생들의 균형을 맞추거나 더 깊은 생각을 유도할 수 있는 예리한 질문을 1문장만 제안하세요. 번호 매기기나 번잡한 서론 없이 질문 자체만 출력하세요.\n최근 대화: {context}"
                    res_text = generate_ai_response(
                        prompt, model_name=AI_MODEL_NAME, api_key=_get_secret("GEMINI_API_KEY", ""),
                        log_message="AI 힌트 생성 실패", room_name=room_name,
                    )
                    if res_text:
                        st.session_state['hint_input_widget'] = res_text.strip().split('\n')[0]
                        st.session_state['ai_hint_manual_mode'] = False
                        st.toast("✅ 힌트 작성 완료!", icon="🎉")
                    else:
                        st.session_state['ai_hint_manual_mode'] = True
                        st.toast("🚨 AI 호출 오류: 수동 모드로 전환되었습니다.", icon="❌")
        else:
            st.session_state['ai_hint_manual_mode'] = True

        col_edit_txt, col_edit_btn = st.columns([8, 2])
        with col_edit_txt:
            st.text_input("선생님의 검토 및 수정", key="hint_input_widget", label_visibility="collapsed", placeholder="여기에 AI 힌트가 나타납니다.")
        with col_edit_btn:
            st.button("🚀 학생 화면 전송", use_container_width=True, type="primary", on_click=send_hint)

    teacher_hint_section()
    st.divider()

    @st.fragment
    def teacher_summary_section():
        st.subheader(f"📝 수업 종료 및 전체 {act_type} 요약 리포트")
        if st.button(f"{act_type} 요약 및 베스트 발언 추출 🪄", use_container_width=True):
            st.toast("👀 AI가 전체 기록을 꼼꼼히 읽고 있습니다...", icon="⏳")
            with st.spinner("✍️ 요약 리포트를 작성하고 있습니다..."):
                if not df_all.empty:
                    full_history = "\n".join([f"[{row['student_name']} - {row['sentiment']}] {row['content']}" for _, row in df_all.iterrows()])
                    prompt = (
                        f"'{current_topic}' 주제의 고등학교 {act_type} 기록입니다.\n\n"
                        "[출력 형식 - 반드시 그대로]\n"
                        "핵심요약 1: ...\n핵심요약 2: ...\n핵심요약 3: ...\n베스트 학생: ...\n선정 이유: ...\n\n"
                        "[엄격한 규칙]\n"
                        "- 핵심요약 1,2,3과 베스트 학생, 선정이유를 줄바꿈을 하여 보기 편하게 합니다.\n"
                        "- 5~10줄로 출력합니다.\n- 제목/헤더(#,##,###), 소제목을 절대 쓰지 않습니다.\n"
                        "- 불필요한 서론/결론 없이 바로 결과만 출력합니다.\n\n"
                        f"기록:\n{full_history}"
                    )
                    res_text = generate_ai_response(
                        prompt, model_name=AI_MODEL_NAME, api_key=_get_secret("GEMINI_API_KEY", ""),
                        log_message="AI 요약 리포트 생성 실패", room_name=room_name,
                    )
                    if res_text:
                        st.session_state['ai_report_text'] = compact_ai_report_output(res_text)
                        st.toast("✅ 리포트 작성 완료!", icon="🎉")
                    else:
                        st.toast("🚨 AI 호출 오류가 발생했습니다.", icon="❌")
                else:
                    st.toast("🚨 분석할 데이터가 없습니다.", icon="⚠️")
        if st.session_state.get('ai_report_text'):
            st.info(f"📊 **AI 수업 {act_type} 요약 리포트**")
            report_html = html.escape(st.session_state['ai_report_text']).replace("\n", "<br>")
            st.markdown(f"<div style='line-height:1.8;'>{report_html}</div>", unsafe_allow_html=True)

    teacher_summary_section()
    st.divider()

    @st.fragment
    def teacher_record_section():
        def delete_selected_record():
            del_id = st.session_state.get('del_record_dropdown')
            if del_id:
                try:
                    if delete_student_record(supabase, del_id) is None: return
                    log_audit("record_deleted", room_name=room_name, actor_name=student_name, role=user_role, record_id=del_id)
                    st.toast("기록이 삭제되었습니다.", icon="🗑️")
                except Exception as e:
                    st.error(f"기록 삭제 실패: {e}")

        col3, col4 = st.columns([1, 1])
        with col3:
            st.subheader("📥 활동 데이터 다운로드")
            if not df_all.empty:
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer: df_all.to_excel(writer, index=False)
                st.download_button(f"{act_type} 전체 활동 로그 (Excel)", data=buffer.getvalue(), file_name=f"{room_name}_log_{get_kst_now().strftime('%Y%m%d_%H%M')}.xlsx")

        with col4:
            st.subheader("🤖 개인별 AI 세특 초안 생성")
            student_list = student_only_df['student_name'].unique() if not df_all.empty else []
            if len(student_list) > 0:
                selected_student = st.selectbox("학생을 선택하세요", student_list)
                if st.button(f"'{selected_student}' 세특 생성 🪄", use_container_width=True):
                    st.toast(f"👀 AI가 '{selected_student}' 학생의 활동을 분석합니다...", icon="⏳")
                    with st.spinner(f"✍️ '{selected_student}' 학생의 세특 초안 작성 중..."):
                        try:
                            student_data = df_all[df_all['student_name'] == selected_student]
                            debate_history = "\n".join([f"- [{row['sentiment']}] {row['content']}" for _, row in student_data.iterrows()])
                            prompt = f"당신은 정보 교사입니다. '{current_topic}' 주제 {act_type}에 참여한 '{selected_student}' 학생의 활동 기록입니다. 이를 바탕으로 생활기록부 교과세특 초안을 약 300자 내외로 작성하세요. 교육적 성장을 강조하세요.\n\n[활동 기록]\n{debate_history}"
                            res_text = generate_ai_response(
                                prompt, model_name=AI_MODEL_NAME, api_key=_get_secret("GEMINI_API_KEY", ""),
                                log_message="AI 세특 생성 실패", room_name=room_name, student=selected_student,
                            )
                            if res_text:
                                st.session_state['ai_result_text'] = res_text
                                now = get_kst_now_str()
                                save_res = save_student_record(supabase, {
                                    "room_name": room_name, "timestamp": now,
                                    "student_name": selected_student, "content": res_text
                                })
                                if save_res is None: raise RuntimeError("보관함 저장 실패")
                                st.toast("✅ 세특 생성 및 보관함 저장 완료!", icon="🎉")
                            else:
                                raise RuntimeError("AI 응답 비어있음")
                        except Exception as e:
                            logger.exception("세특 생성 후처리 실패")
                            st.toast("🚨 오류가 발생했습니다. 다시 시도해주세요.", icon="❌")
                if st.session_state.get('ai_result_text'):
                    st.success("🤖 **개인별 세특 초안** (보관함에 자동 저장되었습니다)")
                    st.text_area("내용 수정 후 복사하여 사용하세요", value=st.session_state['ai_result_text'], height=200, label_visibility="collapsed")
            else: st.info("실명 참여 학생이 없습니다.")

        st.divider()
        st.subheader("📂 저장된 세특 기록 보관함")
        records_df = fetch_student_records(supabase, room_name, RECORDS_FETCH_LIMIT)
        if not records_df.empty:
            records_display_df = records_df.rename(columns={"id": "No.", "content": "세특 내용"})
            records_html = records_display_df.to_html(index=False, escape=True)
            st.markdown(f"<div class='records-db-table-wrap'>{records_html}</div>", unsafe_allow_html=True)
            col_down, col_del = st.columns([1, 1])
            with col_down:
                buffer_records = io.BytesIO()
                with pd.ExcelWriter(buffer_records, engine='openpyxl') as writer:
                    records_df.drop(columns=['id']).to_excel(writer, index=False)
                st.download_button("📥 세특 보관함 다운로드 (Excel)", data=buffer_records.getvalue(), file_name=f"{room_name}_세특보관함.xlsx")
            with col_del:
                st.selectbox("🗑️ 삭제할 '고유 번호(No.)' 선택", records_df['id'].tolist(), key="del_record_dropdown")
                st.button("선택한 세특 기록 영구 삭제", type="primary", on_click=delete_selected_record)
        else: st.info("저장된 기록이 없습니다.")

    teacher_record_section()

    st.divider()
    st.subheader("🚨 위험 구역 (방 폭파)")
    with st.expander("이 방 전체 삭제하기 (클릭 시 펼쳐짐)", expanded=False):
        if not ROOM_DESTROY_ENABLED:
            st.warning("운영 안전 모드로 방 폭파 기능이 비활성화되어 있습니다.")
        else:
            st.error(f"🚨 경고: '{room_name}' 방의 모든 {act_type} 기록과 세특 보관함이 완전히 삭제됩니다.")
            if st.button(f"네, '{room_name}' 방의 모든 데이터를 영구 삭제합니다", type="primary", use_container_width=True):
                try:
                    if destroy_room_data(supabase, room_name) is None: st.stop()
                    log_audit("room_destroyed", room_name=room_name, actor_name=student_name, role=user_role)
                    st.success("성공적으로 파괴되었습니다.")
                    st.session_state['ai_result_text'] = ""
                    st.rerun()
                except Exception as e:
                    st.error(f"삭제 중 오류 발생: {e}")
