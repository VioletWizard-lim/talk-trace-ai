import logging
import time

import streamlit as st

from db import (
    debate_ip_column_available,
    ensure_db_login,
    fetch_debate_status,
    fetch_live_messages,
    fetch_opinion_change,
    fetch_pending_teacher_accounts,
    fetch_topic_data,
    init_db,
    opinion_changes_available,
    submit_opinion,
    topic_entry_code_column_available,
    update_room_entry_code,
    update_topic,
    using_service_role_key,
)
from config import APP_CSS, MAX_ENTRY_CODE_LEN, MAX_STUDENT_NAME_LEN
from utils import anonymize_ip, get_client_ip, get_kst_now_str, log_audit
from validators import validate_entry_code, validate_opinion_content, validate_student_name
from views.home import render_home_page
from views.lobby import render_lobby_page
from components.admin_panel import render_admin_page
from components.sidebar import render_sidebar

logger = logging.getLogger("talk_trace_ai")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

supabase = init_db()
if not using_service_role_key():
    ensure_db_login(supabase)

st.set_page_config(page_title="말자취(Talk-Trace) AI", layout="wide")
st.markdown(APP_CSS, unsafe_allow_html=True)

if 'reset_key' not in st.session_state: st.session_state['reset_key'] = 0
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
if '_last_debate_status' not in st.session_state: st.session_state['_last_debate_status'] = None

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

# plotly / google.generativeai 임포트는 홈 화면에서 불필요 — st.stop() 이후에 로드
from components.chat_board import render_chat_board
from components.teacher_dashboard import render_teacher_dashboard
from components.opinion_change import render_pre_opinion_form, render_post_opinion_section

sidebar_ctx = render_sidebar(supabase)
user_role = sidebar_ctx['user_role']
room_name = sidebar_ctx['room_name']
teacher_auth = sidebar_ctx['teacher_auth']
admin_auth = sidebar_ctx['admin_auth']
student_name = sidebar_ctx['student_name']
student_number = sidebar_ctx['student_number']

# admin 첫 접속 시 pending 여부에 따라 첫 화면 결정 (최초 1회)
if admin_auth and not st.session_state.get('_admin_redirected'):
    _pending = fetch_pending_teacher_accounts(supabase)
    st.session_state['page'] = "admin_approval" if _pending else "lobby"
    st.session_state['joined'] = False
    st.session_state['_admin_redirected'] = True
    st.rerun()

if st.session_state['page'] == "admin_approval":
    render_admin_page(supabase, user_role, teacher_auth, admin_auth)

if not st.session_state['joined']:
    render_lobby_page(supabase, user_role, teacher_auth, room_name, student_number)

# === Joined room view ===
topic_data = fetch_topic_data(supabase, room_name)
current_topic = topic_data.get('title', "자유 주제로 대화해 봅시다.")
current_mode = topic_data.get('mode', "⚔️ 찬반 토론")
act_type = "토론" if "토론" in current_mode else "토의"

if admin_auth:
    col_title, col_btn1, col_btn2 = st.columns([4, 1, 1])
    with col_title:
        st.title(f"🎙️ 말자취(Talk-Trace) AI [{room_name}]")
    with col_btn1:
        if st.button("📝 ID 요청 수락", use_container_width=True):
            st.session_state['page'] = "admin_approval"
            st.rerun()
    with col_btn2:
        if st.button("🚪 말자취 AI 대기실", use_container_width=True):
            st.session_state['page'] = "lobby"
            st.rerun()
else:
    st.title(f"🎙️ 말자취(Talk-Trace) AI [{room_name}]")
st.info(f"**현재 주제:** {current_topic} ({current_mode})")

if user_role == "교사" and teacher_auth:
    with st.expander("✏️ 주제 수정", expanded=False):
        _edit_title = st.text_input("새 주제", value=current_topic, max_chars=120, key="edit_topic_title")
        _edit_mode = st.radio(
            "진행 방식", ["⚔️ 찬반 토론", "💡 자유 토의"],
            index=0 if "토론" in current_mode else 1,
            horizontal=True, key="edit_topic_mode",
        )
        if st.button("✅ 주제 저장", type="primary", use_container_width=True, key="edit_topic_save"):
            if not _edit_title.strip():
                st.warning("주제를 입력해 주세요.")
            else:
                if update_topic(supabase, room_name, _edit_title.strip(), _edit_mode) is not None:
                    st.toast("✅ 주제가 수정되었습니다.", icon="✏️")
                    st.rerun()

if user_role == "교사" and teacher_auth and topic_entry_code_column_available():
    with st.expander("🔒 방 암호 변경", expanded=False):
        _new_pw = st.text_input("새 암호 (비워두면 공개방으로 변경)", type="password", key="change_room_pw")
        _new_pw_confirm = st.text_input("새 암호 확인", type="password", key="change_room_pw_confirm")
        if st.button("✅ 암호 저장", type="primary", use_container_width=True, key="change_room_pw_save"):
            if _new_pw != _new_pw_confirm:
                st.error("❌ 암호가 일치하지 않습니다.")
            else:
                entry_ok, safe_pw, _, entry_error_message = validate_entry_code(_new_pw, max_len=MAX_ENTRY_CODE_LEN)
                if not entry_ok:
                    st.error(f"❌ {entry_error_message}")
                elif update_room_entry_code(supabase, room_name, safe_pw) is not None:
                    st.toast("✅ 방 암호가 변경되었습니다.", icon="🔒")
                    st.rerun()

@st.fragment(run_every=5)
def _poll_debate_status(room_name):
    """학생 화면에서 5초마다 토론 상태를 확인하고 변경 시 전체 rerun."""
    current = fetch_debate_status(supabase, room_name)
    if current != st.session_state.get("_last_debate_status"):
        st.session_state["_last_debate_status"] = current
        st.rerun(scope="app")


@st.fragment
def _render_opinion_input(supabase, room_name, user_role, student_name, student_number, current_mode):
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

    _elapsed = time.time() - st.session_state.get('last_submit_ts', 0)
    _submit_cooldown = _elapsed < 3
    _submit_disabled = _submit_cooldown or st.session_state.get('is_working', False)
    if st.button("의견 제출", use_container_width=True, type="primary", disabled=_submit_disabled):
        if st.session_state.get('is_working', False):
            st.stop()
        st.session_state['is_working'] = True
        input_ok, safe_input, input_error_code, input_error_message = validate_opinion_content(user_input, max_len=700)
        student_ok, safe_student_name, student_error_code, student_error_message = validate_student_name(student_name, max_len=MAX_STUDENT_NAME_LEN)
        student_number_ok, safe_student_number, _, student_number_error_message = validate_student_name(student_number, max_len=20)
        if not student_number_ok and user_role == "학생":
            st.session_state['is_working'] = False
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
                anonymized_ip = anonymize_ip(client_ip)
                if anonymized_ip:
                    insert_payload["ip_address"] = anonymized_ip
            try:
                res = submit_opinion(supabase, insert_payload)
                if res is None:
                    st.session_state['is_working'] = False
                    st.stop()
                st.session_state['last_submit_ts'] = time.time()
                st.session_state['is_working'] = False
                fetch_live_messages.clear()
                log_audit(
                    "opinion_submitted",
                    room_name=room_name, actor_name=safe_student_name,
                    role=author_role_for_submit, sentiment=sentiment,
                    client_ip=client_ip if client_ip else "N/A",
                )
                st.session_state['reset_key'] += 1
                st.rerun(scope="app")
            except Exception as e:
                st.session_state['is_working'] = False
                st.error(f"저장 실패: {e}")
        else:
            st.session_state['is_working'] = False
            st.warning(f"{input_error_message}")
    if _submit_cooldown:
        st.caption("⏳ 제출 성공 후 3초간 의견을 제출할 수 없습니다.")
        time.sleep(0.5)
        st.rerun()

if user_role == "학생" and opinion_changes_available():
    _poll_debate_status(room_name)
    debate_status = fetch_debate_status(supabase, room_name)
    # 학생에게 토론 진행 상태를 항상 명시적으로 표시
    if debate_status == "ended":
        st.warning(f"🔴 **{act_type} 종료** — 아래에서 {act_type} 후 생각 변화를 기록해주세요.")
    else:
        st.success(f"🟢 **{act_type} 진행 중** — 자유롭게 의견을 나눠보세요.")
    row = fetch_opinion_change(supabase, room_name, student_name)
    has_pre_opinion = bool((row or {}).get("pre_opinion"))
    if debate_status == "ended":
        if has_pre_opinion:
            render_post_opinion_section(supabase, room_name, student_name, act_type, current_topic)
        else:
            st.warning(f"{'토론' if act_type == '토론' else '토의'}이 종료되었습니다. 토론 전 생각을 미리 기록하지 않아 참여할 수 없습니다.")
    else:
        if not has_pre_opinion:
            render_pre_opinion_form(supabase, room_name, student_name, current_topic, act_type)
            st.caption("💡 위에서 토론 전 생각을 제출하면 의견 작성이 활성화됩니다.")
        else:
            _render_opinion_input(supabase, room_name, user_role, student_name, student_number, current_mode)
else:
    _render_opinion_input(supabase, room_name, user_role, student_name, student_number, current_mode)

st.divider()

render_chat_board(supabase, room_name, user_role, teacher_auth, student_name, current_mode, act_type)

if user_role == "교사" and teacher_auth:
    render_teacher_dashboard(supabase, room_name, user_role, student_name, current_topic, current_mode, act_type)
