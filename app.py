import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
import logging
import plotly.express as px

from db import (
    debate_ip_column_available,
    ensure_db_login,
    fetch_live_messages,
    fetch_room_entry_code,
    fetch_room_names,
    fetch_topic_data,
    init_db,
    submit_opinion,
    upsert_topic_room,
)
from services.ai import generate_ai_response
from validators import (
    mask_ip_for_teacher,
    normalize_room_name,
    normalize_user_text,
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
# [1] 앱 설정 및 데이터베이스 (Supabase REST API) 연결
# ==========================================
DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
AI_MODEL_NAME = "gemini-2.5-flash"
LIVE_BOARD_FETCH_LIMIT = 300
DASHBOARD_FETCH_LIMIT = 2000
RECORDS_FETCH_LIMIT = 500
LIVE_REFRESH_INTERVAL = "5s"
AI_HINT_ENABLED = st.secrets.get("AI_HINT_ENABLED", True)
ROOM_DESTROY_ENABLED = st.secrets.get("ROOM_DESTROY_ENABLED", True)
AUTO_JOIN_ON_REFRESH = st.secrets.get("AUTO_JOIN_ON_REFRESH", True)
MAX_ROOM_NAME_LEN = 60
MAX_ROOM_NAME_LEN = 60
MAX_STUDENT_NAME_LEN = 30
MAX_TOPIC_LEN = 120
MAX_ENTRY_CODE_LEN = 60

# 1. supabase 변수 생성 (딱 한 번만 실행)
supabase = init_db()

# 2. 자동 로그인 로직 (세션 체크 후 필요할 때만 로그인)
ensure_db_login(supabase)

# --- 기타 유틸리티 함수들 ---
def get_kst_now():
    return datetime.utcnow() + timedelta(hours=9)

def get_kst_now_str():
    return get_kst_now().strftime(DATETIME_FMT)

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

# ==========================================
# [2] 앱 기본 설정 및 세션/CSS 
# ==========================================
st.set_page_config(page_title="Talk-Trace AI", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;700&display=swap');

    /* 1) 텍스트 요소에만 바탕체 적용 (전역 상속 금지) */
    .stApp p,
    .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
    .stApp label, .stApp input, .stApp textarea, .stApp button,
    .stApp li, .stApp td, .stApp th,
    .stApp div[data-testid="stMarkdownContainer"] *:not([class*="material-icons"]):not([class*="material-symbols"]) {
        font-family: "Batang", "바탕", "BatangChe", "Noto Serif KR", serif !important;
    }

    /* 2) 아이콘/리거처 텍스트(예: keyboard_arrow_down) 강제 복원 */
    .material-icons,
    .material-icons-round,
    .material-icons-outlined,
    [class^="material-icons"],
    [class*=" material-icons"] {
        font-family: "Material Icons" !important;
        font-style: normal !important;
        font-weight: normal !important;
        letter-spacing: normal !important;
        text-transform: none !important;
        white-space: nowrap !important;
        direction: ltr !important;
        -webkit-font-smoothing: antialiased !important;
        font-feature-settings: "liga" !important;
    }

    .material-symbols-rounded,
    .material-symbols-outlined,
    [class^="material-symbols"],
    [class*=" material-symbols"] {
        font-family: "Material Symbols Rounded", "Material Symbols Outlined" !important;
        font-style: normal !important;
        font-weight: normal !important;
        letter-spacing: normal !important;
        text-transform: none !important;
        white-space: nowrap !important;
        direction: ltr !important;
        -webkit-font-smoothing: antialiased !important;
        font-feature-settings: "liga" !important;
        font-variation-settings: "FILL" 0, "wght" 400, "GRAD" 0, "opsz" 24 !important;
    }

    [data-baseweb="icon"],
    [data-testid="stSelectbox"] svg,
    [data-testid="stMultiSelect"] svg,
    [data-testid="stExpander"] summary svg {
        font-family: inherit !important;
    }

    /* 기존 스타일들 */
    [data-testid="stDecoration"] { display: none !important; }

    .stApp, [data-testid="stAppViewContainer"], [data-testid="stMainBlockContainer"],
    [data-testid="stAppViewBlockContainer"], [data-testid="stFragment"],
    [data-testid="stVerticalBlock"], [data-testid="stElementContainer"],
    [data-testid="stExpander"], details, summary,
    *[data-stale="true"], div[data-stale="true"] {
        opacity: 1 !important;
        transition: none !important;
        filter: none !important;
        -webkit-filter: none !important;
    }

    .stTextArea textarea, .stTextInput input, .stSelectbox, .stRadio label,
    .stMarkdown p, div[data-testid="stChatMessageContent"] {
        font-size: 18px !important;
    }

    .stAlert p { font-size: 20px !important; font-weight: bold; }
    </style>
    """,
    unsafe_allow_html=True
)

if 'reset_key' not in st.session_state: st.session_state['reset_key'] = 0
if 'ai_result_text' not in st.session_state: st.session_state['ai_result_text'] = ""
if 'ai_hint_text' not in st.session_state: st.session_state['ai_hint_text'] = ""
if 'ai_report_text' not in st.session_state: st.session_state['ai_report_text'] = ""
if 'current_room' not in st.session_state: st.session_state['current_room'] = ""
if 'joined' not in st.session_state: st.session_state['joined'] = False
if 'teacher_auth' not in st.session_state: st.session_state['teacher_auth'] = False
if 'is_working' not in st.session_state: st.session_state['is_working'] = False
if 'ai_hint_manual_mode' not in st.session_state: st.session_state['ai_hint_manual_mode'] = False

def set_working():
    st.session_state['is_working'] = True
    st.toast("요청을 받았습니다! 서버가 분석을 준비합니다... 🚀", icon="⏳")

def reset_joined_state():
    st.session_state['joined'] = False
    st.session_state['teacher_auth'] = False

# ==========================================
# [3] 사이드바 (방 관리 - 심플 모드)
# ==========================================
with st.sidebar:
    st.header("👤 접속 권한")
    user_role = st.radio("모드 선택", ["학생", "교사"], on_change=reset_joined_state)
    st.divider()

    try:        
        existing_rooms = fetch_room_names(supabase)
    except Exception:
        existing_rooms = []
        
    room_name = ""
    teacher_auth = False
    
    if user_role == "교사":
        pw = st.text_input("교사 인증 암호", type="password", key="teacher_pw_input")
        if pw == st.secrets["TEACHER_PW"]:
            st.session_state['teacher_auth'] = True
        elif pw:
            st.session_state['teacher_auth'] = False
            st.error("❌ 교사 인증 암호가 올바르지 않습니다.")
            
        teacher_auth = st.session_state['teacher_auth']
        if teacher_auth:
            st.success("인증 성공!")
            room_opt = st.radio("방 관리", ["기존 방 선택", "새 방 만들기"])
            
            if room_opt == "기존 방 선택" and existing_rooms:
                room_name = st.selectbox("토론/토의방 목록", existing_rooms)
            else:
                new_room = st.text_input("새로 만들 방 이름 (예: 1학년 3반)")
                new_title = st.text_input("주제 직접 입력 (예: 인공지능 윤리)")
                new_mode = st.radio("진행 방식", ["⚔️ 찬반 토론", "💡 자유 토의"], horizontal=True)
                new_pw = st.text_input("🔒 학생 입장용 암호 (비워두면 공개방)")

                if st.button("새 방 개설하기", type="primary"):
                    safe_new_room = normalize_room_name(new_room)
                    safe_new_title = normalize_user_text(new_title, max_len=MAX_TOPIC_LEN)
                    safe_new_pw = normalize_user_text(new_pw, max_len=MAX_ENTRY_CODE_LEN)
                    if safe_new_room and safe_new_title:
                        res = upsert_topic_room(
                            supabase=supabase,
                            room_name=safe_new_room,
                            title=safe_new_title,
                            mode=new_mode,
                            entry_code=safe_new_pw,
                        )
                        if res is not None:
                            st.success(f"'{safe_new_room}' 방이 개설되었습니다! '기존 방 선택'을 눌러 입장하세요.")
                    else:
                        st.error(
                            f"방 이름({MAX_ROOM_NAME_LEN}자 이하)과 주제({MAX_TOPIC_LEN}자 이하)를 모두 입력해주세요. "
                            f"입장 암호는 {MAX_ENTRY_CODE_LEN}자까지 저장됩니다."
                        )
                    room_name = ""
    else:
        st.session_state['teacher_auth'] = False
        if existing_rooms:
            room_name = st.selectbox("🏠 접속할 방 선택", existing_rooms)
        else:
            st.warning("선생님이 아직 열어둔 방이 없습니다.")
            room_name = ""
            
    student_name = st.text_input("내 이름", value="익명" if user_role == "학생" else "교사")
    
    if room_name and room_name != st.session_state['current_room']:
        st.session_state['current_room'] = room_name
        st.session_state['ai_hint_text'] = ""
        st.session_state['ai_report_text'] = ""
        st.session_state['ai_result_text'] = ""
    
    if st.session_state['joined']:
        st.divider()
        if st.button("🚪 방 나가기 (대기실로)"):
            st.session_state['joined'] = False
            st.rerun()

# ==========================================
# [4] 대기실
# ==========================================
if not st.session_state['joined']:
    st.title("🚪 Talk-Trace AI 대기실")
    if user_role == "교사" and not teacher_auth: st.warning("🚨 교사 인증 암호를 입력해야 입장할 수 있습니다.")
    elif not room_name.strip(): st.error("🚨 접속할 방을 먼저 선택해 주세요.")
    else:
        if user_role == "학생":
            real_pw = fetch_room_entry_code(supabase, room_name)
                
            if real_pw:
                student_pw = st.text_input("🔒 방 입장 암호 (선생님께 확인하세요)", type="password")
                if student_pw == real_pw:
                    if st.button(f"🚀 '{room_name}' 입장하기", type="primary", use_container_width=True):
                        st.session_state['joined'] = True; st.rerun()
                elif student_pw: st.error("❌ 암호가 틀렸습니다.")
            else:
                if AUTO_JOIN_ON_REFRESH:
                    st.session_state['joined'] = True; st.rerun()
                if st.button(f"🚀 '{room_name}' 입장하기", type="primary", use_container_width=True):
                    st.session_state['joined'] = True; st.rerun()
        else:
            if AUTO_JOIN_ON_REFRESH and teacher_auth:
                st.session_state['joined'] = True; st.rerun()
            if st.button(f"🚀 '{room_name}' 관리자 권한으로 입장", type="primary", use_container_width=True):
                st.session_state['joined'] = True; st.rerun()
    st.stop()

# ==========================================
# [5] 메인 화면 (의견 입력부)
# ==========================================
topic_data = fetch_topic_data(supabase, room_name)

current_topic = topic_data.get('title', "자유 주제로 대화해 봅시다.")
current_mode = topic_data.get('mode', "⚔️ 찬반 토론")
act_type = "토론" if "토론" in current_mode else "토의"

st.title(f"🎙️ Talk-Trace AI [{room_name}]")
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
    safe_input = normalize_user_text(user_input, max_len=700)
    safe_student_name = normalize_user_text(student_name, max_len=MAX_STUDENT_NAME_LEN) or "익명"
    if safe_input:
        now = get_kst_now_str()
        author_role_for_submit = "교사" if user_role == "교사" else "학생"
        client_ip = get_client_ip()
        insert_payload = {
            "room_name": room_name,
            "timestamp": now,
            "student_name": safe_student_name,
            "content": safe_input,
            "sentiment": sentiment,
            "author_role": author_role_for_submit
        }
        if debate_ip_column_available() and client_ip:
            insert_payload["ip_address"] = client_ip
        try:
            res = submit_opinion(supabase, insert_payload)
            if res is None:
                st.stop()
            log_audit("opinion_submitted", room_name=room_name, actor_name=safe_student_name, role=author_role_for_submit, sentiment=sentiment, client_ip=client_ip if client_ip else "N/A")
            st.session_state['reset_key'] += 1
            st.rerun()
        except Exception as e:
            st.error(f"저장 실패: {e}")
    else:
        st.warning("의견 내용을 입력해 주세요.")

st.divider()

# ==========================================
# [6] 실시간 업데이트 영역
# ==========================================
def live_chat_board_core():
    df = fetch_live_messages(supabase, room_name, LIVE_BOARD_FETCH_LIMIT)
    opinion_df = with_fallback_author_role(df) # 변수명 매칭 확인 (이전 코드에서 student_df 대신 opinion_df 혼용 부분 수정)
    
    with st.expander("📊 실시간 의견 통계 보기 (클릭하여 펼치기)"):
        if not opinion_df.empty:
            st.plotly_chart(px.pie(opinion_df, names="sentiment", hole=0.4, height=300), use_container_width=True, config={'displayModeBar': False, 'scrollZoom': False})
        else: st.write("데이터 수집 중...")

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
                supabase.table("debate").delete().eq("id", msg_id).execute()
                log_audit("chat_deleted", room_name=room_name, actor_name=student_name, role=user_role, message_id=msg_id)
                st.toast("의견이 즉시 삭제되었습니다.", icon="🗑️")
            except Exception as e:
                st.error(f"삭제 실패: {e}")

        def render_msg(row):
            if user_role == "교사" and teacher_auth:
                c_name, c_btn = st.columns([5, 1])
                with c_name: 
                    st.markdown(f"**{row['student_name']}** <span style='color:gray; font-size:14px;'>{row['timestamp'][11:]}</span>", unsafe_allow_html=True)
                    row_ip = str(row.get("ip_address", "")).strip() if hasattr(row, "get") else ""
                    if row_ip:
                        st.caption(f"IP: `{mask_ip_for_teacher(row_ip)}`")
                with c_btn:
                    st.button("❌", key=f"del_{row['id']}", help="강제 삭제", on_click=delete_chat_msg, args=(row['id'],))
                st.info(row['content']) 
            else:
                st.markdown(f"**{row['student_name']}** <span style='color:gray; font-size:14px;'>{row['timestamp'][11:]}</span>", unsafe_allow_html=True)
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
    else: st.info(f"아직 대화가 없습니다. 첫 {act_type} 의견을 남겨주세요!")

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
# [7] 교사 전용 대시보드
# ==========================================
if user_role == "교사" and teacher_auth:
    st.divider()
    
    col_dash_title, col_dash_refresh = st.columns([8, 2])
    with col_dash_title:
        st.header("👨‍🏫 교사 관리 대시보드")
    with col_dash_refresh:
        if st.button("🔄 대시보드 수동 새로고침", use_container_width=True):
            st.rerun()

    df_all = with_fallback_author_role(fetch_live_messages(supabase, room_name, DASHBOARD_FETCH_LIMIT))
    
    # --- 1. 통계 ---
    st.subheader("📊 학생 참여도 현황")
    if not df_all.empty:
        student_only_df = df_all[(df_all['author_role'] == '학생') & ~df_all['student_name'].str.contains('익명|AI', na=False, regex=True)].copy()
        if not student_only_df.empty:
            counts = student_only_df['student_name'].astype(str).value_counts().reset_index()
            counts.columns = ['학생 이름', '참여 횟수']
            counts['학생 이름'] = counts['학생 이름'] + " " 
            fig = px.bar(counts, x='학생 이름', y='참여 횟수', text='참여 횟수', color='학생 이름')
            fig.update_xaxes(type='category', title="") 
            fig.update_layout(yaxis_title="의견 수", dragmode=False, showlegend=False) 
            st.plotly_chart(fig, use_container_width=True, config={'scrollZoom': False, 'displayModeBar': False})
        else: st.info("실명 참여 데이터가 없습니다.")
    else: st.info(f"{act_type} 데이터가 없습니다.")
            
    st.divider()
    
    # --- 2. Teacher in the loop ---
    @st.fragment
    def teacher_hint_section():
        st.subheader(f"💡 AI {act_type} 촉진 (Teacher-in-the-loop)")
        st.info("AI 제안을 수정 후 전송하세요.")
        
        def send_hint():
            val = st.session_state.get('hint_input_widget', '').strip()
            if val:
                now = get_kst_now_str()
                try:
                    supabase.table("debate").insert({
                        "room_name": room_name, "timestamp": now, "student_name": "👨‍🏫 선생님 (AI 보조)", 
                        "content": val, "sentiment": "❓ 질문", "author_role": "교사"
                    }).execute()
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
                        prompt,
                        model_name=AI_MODEL_NAME,
                        api_key=st.secrets["GEMINI_API_KEY"],
                        log_message="AI 힌트 생성 실패",
                        room_name=room_name,
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

    # --- 3. 수업 종료 요약 리포트 ---
    @st.fragment
    def teacher_summary_section():
        st.subheader(f"📝 수업 종료 및 전체 {act_type} 요약 리포트")
        
        if st.button(f"{act_type} 요약 및 베스트 발언 추출 🪄", use_container_width=True):
            st.toast("👀 AI가 전체 기록을 꼼꼼히 읽고 있습니다...", icon="⏳")
            with st.spinner("✍️ 요약 리포트를 작성하고 있습니다..."):
                if not df_all.empty:
                    full_history = "\n".join([f"[{row['student_name']} - {row['sentiment']}] {row['content']}" for _, row in df_all.iterrows()])
                    prompt = f"'{current_topic}' 주제의 고등학교 {act_type} 기록입니다.\n\n[엄격한 규칙]\n1. {act_type}의 전체 맥락을 파악하고 핵심 내용을 딱 3줄로 요약하세요.\n2. 가장 논리적이고 창의적인 주장을 펼친 '학생 이름' 1명과 그 이유를 구체적으로 추출하세요.\n3. 보고서 형식으로 깔끔하게 출력하세요.\n\n기록:\n{full_history}"
                    res_text = generate_ai_response(
                        prompt,
                        model_name=AI_MODEL_NAME,
                        api_key=st.secrets["GEMINI_API_KEY"],
                        log_message="AI 요약 리포트 생성 실패",
                        room_name=room_name,
                    )
                    if res_text:
                        st.session_state['ai_report_text'] = res_text
                        st.toast("✅ 리포트 작성 완료!", icon="🎉")
                    else:
                        st.toast("🚨 AI 호출 오류가 발생했습니다.", icon="❌")
                else:
                    st.toast("🚨 분석할 데이터가 없습니다.", icon="⚠️")

        if st.session_state.get('ai_report_text'):
            st.info(f"📊 **AI 수업 {act_type} 요약 리포트**")
            st.markdown(st.session_state['ai_report_text'])
            
    teacher_summary_section()
    st.divider()

    # --- 4. 세특 생성 및 다운로드 ---
    @st.fragment
    def teacher_record_section():
        def delete_selected_record():
            del_id = st.session_state.get('del_record_dropdown')
            if del_id:
                try:
                    supabase.table("records").delete().eq("id", del_id).execute()
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
                                prompt,
                                model_name=AI_MODEL_NAME,
                                api_key=st.secrets["GEMINI_API_KEY"],
                                log_message="AI 세특 생성 실패",
                                room_name=room_name,
                                student=selected_student,
                            )
                            
                            if res_text:
                                st.session_state['ai_result_text'] = res_text
                                now = get_kst_now_str()
                                supabase.table("records").insert({
                                    "room_name": room_name, "timestamp": now, 
                                    "student_name": selected_student, "content": res_text
                                }).execute()
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
        
        try:
            records_res = supabase.table("records").select("id, timestamp, student_name, content").eq("room_name", room_name).order("id", desc=True).limit(RECORDS_FETCH_LIMIT).execute()
            records_df = pd.DataFrame(records_res.data)
        except Exception:
            records_df = pd.DataFrame()

        if not records_df.empty:
            st.dataframe(records_df, use_container_width=True, column_config={"id": "No.", "content": st.column_config.TextColumn("세특 내용", width="large")})
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
                    supabase.table("topic").delete().eq("room_name", room_name).execute()
                    supabase.table("debate").delete().eq("room_name", room_name).execute()
                    supabase.table("records").delete().eq("room_name", room_name).execute()
                    log_audit("room_destroyed", room_name=room_name, actor_name=student_name, role=user_role)
                    st.success("성공적으로 파괴되었습니다.")
                    st.session_state['ai_result_text'] = ""
                    st.rerun() 
                except Exception as e:
                    st.error(f"삭제 중 오류 발생: {e}")
