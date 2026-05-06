import logging

import streamlit as st

from db import (
    debate_ip_column_available,
    ensure_db_login,
    fetch_topic_data,
    init_db,
    submit_opinion,
)
from config import APP_CSS, MAX_STUDENT_NAME_LEN
from utils import get_client_ip, get_kst_now_str, log_audit
from validators import normalize_user_text, validate_opinion_content, validate_student_name
from pages.home import render_home_page
from pages.lobby import render_lobby_page
from pages.admin import render_admin_page
from components.sidebar import render_sidebar
from components.chat_board import render_chat_board
from components.teacher_dashboard import render_teacher_dashboard

logger = logging.getLogger("talk_trace_ai")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

supabase = init_db()
ensure_db_login(supabase)

st.set_page_config(page_title="말자취(Talk-Trace) AI", layout="wide")
st.markdown(APP_CSS, unsafe_allow_html=True)

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

if st.session_state['page'] != "home":
    col_home_btn, _ = st.columns([1, 7])
    with col_home_btn:
        if st.button("🏠 홈", use_container_width=True):
            st.session_state['page'] = "home"
            st.session_state['joined'] = False
            st.session_state['teacher_auth'] = False
            st.rerun()

if st.session_state['page'] == "home":
    render_home_page()

sidebar_ctx = render_sidebar(supabase)
user_role = sidebar_ctx['user_role']
room_name = sidebar_ctx['room_name']
teacher_auth = sidebar_ctx['teacher_auth']
admin_auth = sidebar_ctx['admin_auth']
student_name = sidebar_ctx['student_name']
student_number = sidebar_ctx['student_number']

if st.session_state['page'] == "admin_approval":
    render_admin_page(supabase, user_role, teacher_auth, admin_auth)

if not st.session_state['joined']:
    render_lobby_page(supabase, user_role, teacher_auth, room_name, student_number)

# === Joined room view ===
topic_data = fetch_topic_data(supabase, room_name)
current_topic = topic_data.get('title', "자유 주제로 대화해 봅시다.")
current_mode = topic_data.get('mode', "⚔️ 찬반 토론")
act_type = "토론" if "토론" in current_mode else "토의"

st.title(f"🎙️ 말자취(Talk-Trace) AI [{room_name}]")
st.info(f"**현재 주제:** {current_topic} ({current_mode})")

st.subheader("🗣️ 내 의견 작성")
col_input, col_stt = st.columns([4, 1])
with col_input:
    user_input = st.text_area(
        "의견을 입력하세요",
        key=f"input_{st.session_state['reset_key']}",
        height=80,
        label_visibility="collapsed",
    )
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
        """,
        height=120,
    )

if st.button("의견 제출", use_container_width=True, type="primary"):
    input_ok, safe_input, input_error_code, input_error_message = validate_opinion_content(user_input, max_len=700)
    student_ok, safe_student_name, student_error_code, student_error_message = validate_student_name(student_name, max_len=MAX_STUDENT_NAME_LEN)
    student_number_ok, safe_student_number, _, student_number_error_message = validate_student_name(student_number, max_len=20)
    if not student_number_ok and user_role == "학생":
        st.error(f"❌ {student_number_error_message}")
        st.stop()
    if user_role == "학생" and (not safe_student_name or safe_student_name == "익명"):
        safe_student_name = safe_student_number or "학번미입력"
    if input_ok and safe_input:
        now = get_kst_now_str()
        author_role_for_submit = "교사" if user_role == "교사" else "학생"
        client_ip = get_client_ip()
        insert_payload = {
            "room_name": room_name, "timestamp": now, "student_name": safe_student_name,
            "content": safe_input, "sentiment": sentiment, "author_role": author_role_for_submit,
        }
        if debate_ip_column_available() and client_ip:
            insert_payload["ip_address"] = client_ip
        try:
            res = submit_opinion(supabase, insert_payload)
            if res is None:
                st.stop()
            log_audit(
                "opinion_submitted",
                room_name=room_name, actor_name=safe_student_name,
                role=author_role_for_submit, sentiment=sentiment,
                client_ip=client_ip if client_ip else "N/A",
            )
            st.session_state['reset_key'] += 1
            st.rerun()
        except Exception as e:
            st.error(f"저장 실패: {e}")
    else:
        st.warning(f"{input_error_message} ({input_error_code})")

st.divider()

render_chat_board(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type)

if user_role == "교사" and teacher_auth:
    render_teacher_dashboard(supabase, room_name, user_role, student_name, current_topic, current_mode, act_type)
