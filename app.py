import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
import logging
import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool
import google.generativeai as genai
import plotly.express as px
import time
import re

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
# [1] 데이터베이스 연결 및 타임존 설정
# ==========================================
DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
AI_MODEL_NAME = "gemini-2.5-flash"
LIVE_BOARD_FETCH_LIMIT = 300
DASHBOARD_FETCH_LIMIT = 2000
RECORDS_FETCH_LIMIT = 500
LIVE_REFRESH_INTERVAL = "2s"
AI_HINT_ENABLED = st.secrets.get("AI_HINT_ENABLED", True)
ROOM_DESTROY_ENABLED = st.secrets.get("ROOM_DESTROY_ENABLED", True)
AUTO_JOIN_ON_REFRESH = st.secrets.get("AUTO_JOIN_ON_REFRESH", True)
MAX_ROOM_NAME_LEN = 60
MAX_STUDENT_NAME_LEN = 30
MAX_TOPIC_LEN = 120
DB_POOL_MIN_CONN = int(st.secrets.get("DB_POOL_MIN_CONN", 1))
DB_POOL_MAX_CONN = int(st.secrets.get("DB_POOL_MAX_CONN", 8))
DB_POOL = None

def get_kst_now():
    return datetime.utcnow() + timedelta(hours=9)

def get_kst_now_str():
    return get_kst_now().strftime(DATETIME_FMT)

def generate_ai_response(prompt, log_message, **context):
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        return genai.GenerativeModel(AI_MODEL_NAME).generate_content(prompt).text
    except Exception:
        logger.exception("%s (context=%s)", log_message, context)
        return None

def get_recent_debate_df(room_name, limit):
    return get_df_from_db(
        "SELECT * FROM debate WHERE room_name = %s ORDER BY id DESC LIMIT %s",
        (room_name, limit),
    )

def normalize_user_text(raw_text, max_len=500):
    text = (raw_text or "").strip()
    if not text:
        return ""
    return text[:max_len]

def normalize_room_name(raw_text):
    text = normalize_user_text(raw_text, max_len=MAX_ROOM_NAME_LEN)
    return re.sub(r"\s+", " ", text)

def validate_room_name(room):
    if not room:
        return False
    return re.fullmatch(r"[0-9A-Za-z가-힣 _\\-()]+", room) is not None

def normalize_topic_title(raw_text):
    return normalize_user_text(raw_text, max_len=MAX_TOPIC_LEN)

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

def log_audit(event, room_name="", actor_name="", role="", **extra):
    logger.info(
        "AUDIT event=%s room=%s actor=%s role=%s extra=%s",
        event,
        room_name,
        actor_name,
        role,
        extra,
    )

def init_db_pool():
    global DB_POOL
    if DB_POOL is None:
        DB_POOL = SimpleConnectionPool(
            DB_POOL_MIN_CONN,
            DB_POOL_MAX_CONN,
            st.secrets["SUPABASE_URL"],
        )

def get_db_conn():
    if DB_POOL is None:
        init_db_pool()
    return DB_POOL.getconn()

def release_db_conn(conn):
    if conn is not None and DB_POOL is not None:
        DB_POOL.putconn(conn)

def insert_ai_placeholder_atomic(room_name):
    conn = None
    try:
        conn = get_db_conn()
        with conn.cursor() as c:
            c.execute("SELECT pg_advisory_xact_lock(9999)")
            ten_secs_ago = (get_kst_now() - timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("SELECT 1 FROM debate WHERE room_name = %s AND student_name LIKE '%%AI%%' AND timestamp > %s", (room_name, ten_secs_ago))
            if c.fetchone(): return None
            now_str = get_kst_now_str()
            c.execute("INSERT INTO debate (room_name, timestamp, student_name, content, sentiment) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                      (room_name, now_str, "🤖 AI 조력자", "질문 생성 중...", "❓ 질문"))
            inserted_id = c.fetchone()[0]
            conn.commit() 
            return inserted_id
    except Exception:
        logger.exception("AI placeholder 생성 실패 (room_name=%s)", room_name)
        return None
    finally:
        release_db_conn(conn)

def get_df_from_db(query, params=()):
    conn = None
    try:
        conn = get_db_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute(query, params)
            data = c.fetchall()
            return pd.DataFrame(data, columns=[desc[0] for desc in c.description] if c.description else [])
    except Exception:
        logger.exception("DB 조회 실패 (query=%s, params=%s)", query, params)
        return pd.DataFrame()
    finally:
        release_db_conn(conn)

def execute_query(query, params=()):
    conn = None
    try:
        conn = get_db_conn()
        with conn.cursor() as c:
            c.execute(query, params)
        conn.commit()
    except Exception:
        logger.exception("DB 실행 실패 (query=%s, params=%s)", query, params)
        raise
    finally:
        release_db_conn(conn)

def init_db():
    conn = None
    try:
        init_db_pool()
        conn = get_db_conn()
        with conn.cursor() as c:
            c.execute('CREATE TABLE IF NOT EXISTS debate (id SERIAL PRIMARY KEY, room_name TEXT, timestamp TEXT, student_name TEXT, content TEXT, sentiment TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS records (id SERIAL PRIMARY KEY, room_name TEXT, timestamp TEXT, student_name TEXT, content TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS topic (room_name TEXT PRIMARY KEY, title TEXT, mode TEXT, entry_code TEXT DEFAULT \'\')')
            c.execute("ALTER TABLE debate ADD COLUMN IF NOT EXISTS author_role TEXT DEFAULT '학생'")
            c.execute('CREATE INDEX IF NOT EXISTS idx_debate_room_id ON debate (room_name, id DESC)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_records_room_id ON records (room_name, id DESC)')
        conn.commit()
    except Exception as e:
        logger.exception("DB 초기화 실패")
        st.error(f"🚨 DB 연결 실패: {e}")
    finally:
        release_db_conn(conn)

init_db()

# ==========================================
# [2] 앱 기본 설정 및 세션/CSS 
# ==========================================
st.set_page_config(page_title="Talk-Trace AI", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stStatusWidget"] { visibility: hidden !important; display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }
    
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stMainBlockContainer"],
    [data-testid="stAppViewBlockContainer"], [data-testid="stFragment"], 
    [data-testid="stVerticalBlock"], [data-testid="stElementContainer"], 
    [data-testid="stExpander"], details, summary,
    *[data-stale="true"], div[data-stale="true"] {
        opacity: 1 !important; transition: none !important; filter: none !important; -webkit-filter: none !important;
    }
    
    .stTextArea textarea, .stTextInput input, .stSelectbox, .stRadio label, .stMarkdown p, div[data-testid="stChatMessageContent"] { 
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

# 💡 [핵심 패치 1] AI가 일하고 있는지 체크하는 변수 생성!
if 'is_working' not in st.session_state: st.session_state['is_working'] = False
if 'ai_hint_manual_mode' not in st.session_state: st.session_state['ai_hint_manual_mode'] = False

def set_working():
    st.session_state['is_working'] = True
    # 💡 [핵심 패치 2] 버튼이 눌리는 즉시 우측 하단에 팝업을 띄워서, 먹통처럼 보이는 0.5초의 딜레이를 메꿉니다!
    st.toast("요청을 받았습니다! 서버가 분석을 준비합니다... 🚀", icon="⏳")

def reset_joined_state():
    st.session_state['joined'] = False

# ==========================================
# [3] 사이드바 (방 관리 - 심플 모드)
# ==========================================
with st.sidebar:
    st.header("👤 접속 권한")
    user_role = st.radio("모드 선택", ["학생", "교사"], on_change=reset_joined_state)
    st.divider()

    rooms_df = get_df_from_db("SELECT DISTINCT room_name FROM topic")
    existing_rooms = rooms_df['room_name'].tolist() if not rooms_df.empty else []
    
    room_name = ""
    teacher_auth = False
    
    if user_role == "교사":
        pw = st.text_input("교사 인증 암호", type="password")
        if pw == st.secrets["TEACHER_PW"]:
            teacher_auth = True; st.success("인증 성공!")
            room_opt = st.radio("방 관리", ["기존 방 선택", "새 방 만들기"])
            
            if room_opt == "기존 방 선택" and existing_rooms:
                room_name = st.selectbox("토론/토의방 목록", existing_rooms)
            else:
                new_room = st.text_input("새로 만들 방 이름 (예: 1학년 3반)")
                new_title = st.text_input("주제 직접 입력 (예: 인공지능 윤리)")
                new_mode = st.radio("진행 방식", ["⚔️ 찬반 토론", "💡 자유 토의"], horizontal=True)
                new_pw = st.text_input("🔒 학생 입장용 암호 (비워두면 공개방)")
                
                if st.button("새 방 개설하기", type="primary"):
                    safe_room_name = normalize_room_name(new_room)
                    safe_title = normalize_topic_title(new_title)
                    if not validate_room_name(safe_room_name):
                        st.error("방 이름은 한글/영문/숫자/공백/-/_/괄호만 사용할 수 있습니다.")
                        room_name = ""
                    elif safe_room_name and safe_title:
                        execute_query("INSERT INTO topic (room_name, title, mode, entry_code) VALUES (%s, %s, %s, %s) ON CONFLICT (room_name) DO NOTHING", 
                                      (safe_room_name, safe_title, new_mode, new_pw))
                        st.success(f"'{safe_room_name}' 방이 개설되었습니다! 위쪽에서 '기존 방 선택'을 눌러 입장하세요.")
                        log_audit("room_created", room_name=safe_room_name, actor_name="교사", role="교사", mode=new_mode)
                        room_name = safe_room_name
                    else:
                        st.error("방 이름과 주제를 모두 입력해주세요.")
                        room_name = ""
    else:
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
            topic_info = get_df_from_db("SELECT entry_code FROM topic WHERE room_name = %s", (room_name,))
            real_pw = topic_info.iloc[0]['entry_code'] if not topic_info.empty and topic_info.iloc[0]['entry_code'] else ""
            if real_pw:
                student_pw = st.text_input("🔒 방 입장 암호 (선생님께 확인하세요)", type="password")
                if student_pw == real_pw:
                    if st.button(f"🚀 '{room_name}' 입장하기", type="primary", use_container_width=True):
                        st.session_state['joined'] = True; st.rerun()
                elif student_pw: st.error("❌ 암호가 틀렸습니다.")
            else:
                if AUTO_JOIN_ON_REFRESH:
                    st.session_state['joined'] = True
                    st.rerun()
                if st.button(f"🚀 '{room_name}' 입장하기", type="primary", use_container_width=True):
                    st.session_state['joined'] = True; st.rerun()
        else:
            if AUTO_JOIN_ON_REFRESH and teacher_auth:
                st.session_state['joined'] = True
                st.rerun()
            if st.button(f"🚀 '{room_name}' 관리자 권한으로 입장", type="primary", use_container_width=True):
                st.session_state['joined'] = True; st.rerun()
    st.stop()

# ==========================================
# [5] 메인 화면 (의견 입력부)
# ==========================================
topic_df = get_df_from_db("SELECT title, mode FROM topic WHERE room_name = %s", (room_name,))
current_topic = topic_df.iloc[0]['title'] if not topic_df.empty else "자유 주제로 대화해 봅시다."
current_mode = topic_df.iloc[0]['mode'] if not topic_df.empty else "⚔️ 찬반 토론"

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
        execute_query("INSERT INTO debate (room_name, timestamp, student_name, content, sentiment, author_role) VALUES (%s, %s, %s, %s, %s, %s)",
                      (room_name, now, safe_student_name, safe_input, sentiment, user_role))
        log_audit("opinion_submitted", room_name=room_name, actor_name=safe_student_name, role=user_role, sentiment=sentiment)
        st.session_state['reset_key'] += 1
        st.rerun()
    else:
        st.warning("의견 내용을 입력해 주세요.")

st.divider()

# ==========================================
# [6] 실시간 업데이트 영역 (🔥 타이머 충돌 완벽 방지 설계)
# ==========================================
# 이 함수는 화면을 그리는 알맹이입니다.
def live_chat_board_core():
    df = get_recent_debate_df(room_name, LIVE_BOARD_FETCH_LIMIT)
    if not df.empty and "id" in df.columns:
        df = df.sort_values("id")
    df = with_fallback_author_role(df)
    
    with st.expander("📊 실시간 의견 통계 보기 (클릭하여 펼치기)"):
        if not df.empty:
            st.plotly_chart(px.pie(df, names="sentiment", hole=0.4, height=300), use_container_width=True, config={'displayModeBar': False})
        else: st.write("데이터 수집 중...")

    col_board_title, col_board_ref = st.columns([8, 2])
    with col_board_title:
        st.subheader(f"💬 실시간 {act_type} 보드") 
    with col_board_ref:
        if user_role == "교사" and teacher_auth:
            st.button("🔄 실시간 보드 새로고침", use_container_width=True, key="refresh_chat_board")
    
    if not df.empty:
        teacher_df = df[df["author_role"] == '교사']
        if not teacher_df.empty:
            st.success(f"👨‍🏫 **선생님의 생각 힌트!** ➡️ {teacher_df.iloc[0]['content']}")

        student_df = df[df["author_role"] == '학생']
        
        # 💡 [핵심 패치 1] 삭제 작업을 0.1초 만에 먼저 처리하는 '콜백 함수'
        def delete_chat_msg(msg_id):
            execute_query("DELETE FROM debate WHERE id = %s", (msg_id,))
            log_audit("chat_deleted", room_name=room_name, actor_name=student_name, role=user_role, message_id=msg_id)
            st.toast("의견이 즉시 삭제되었습니다.", icon="🗑️")

        def render_msg(row):
            if user_role == "교사" and teacher_auth:
                c_name, c_btn = st.columns([5, 1])
                with c_name:
                    st.markdown(f"**{row['student_name']}** <span style='color:gray; font-size:14px;'>{row['timestamp'][11:]}</span>", unsafe_allow_html=True)
                with c_btn:
                    # 💡 [핵심 패치 2] st.rerun()을 지우고 on_click 으로 콜백 함수 연결!
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

# 💡 [핵심 패치 2] 평소에는 5초 타이머 작동 모드!
@st.fragment(run_every=LIVE_REFRESH_INTERVAL)
def live_chat_board_auto():
    live_chat_board_core()

# 💡 [핵심 패치 3] AI가 일할 때는 수동 렌더링 모드! (타이머 해제)
def live_chat_board_manual():
    live_chat_board_core()

# AI가 일하는 중이면 타이머 없는 안전 모드로 화면을 그립니다.
if st.session_state.get('is_working', False):
    live_chat_board_manual()
else:
    live_chat_board_auto()

# ==========================================
# [7] 교사 전용 대시보드 (🔥 st.rerun() 완전 제거! 스크롤 튕김 완벽 해결)
# ==========================================
if user_role == "교사" and teacher_auth:
    st.divider()
    
    col_dash_title, col_dash_refresh = st.columns([8, 2])
    with col_dash_title:
        st.header("👨‍🏫 교사 관리 대시보드")
    with col_dash_refresh:
        if st.button("🔄 대시보드 수동 새로고침", use_container_width=True):
            st.rerun() # 이 버튼만 예외적으로 전체 새로고침을 허용합니다.

    df_all = with_fallback_author_role(get_recent_debate_df(room_name, DASHBOARD_FETCH_LIMIT))
    
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
    
    # --- 2. Teacher in the loop (🔥 스크롤 고정 패치) ---
    @st.fragment
    def teacher_hint_section():
        st.subheader(f"💡 AI {act_type} 촉진 (Teacher-in-the-loop)")
        st.info("AI 제안을 수정 후 전송하세요.")
        
        # [전송] 버튼을 눌렀을 때 실행될 백그라운드 함수 (화면 튕김 방지)
        def send_hint():
            val = st.session_state.get('hint_input_widget', '').strip()
            if val:
                now = get_kst_now_str()
                execute_query("INSERT INTO debate (room_name, timestamp, student_name, content, sentiment, author_role) VALUES (%s, %s, %s, %s, %s, %s)",
                              (room_name, now, "👨‍🏫 선생님 (AI 보조)", val, "❓ 질문", "교사"))
                log_audit("teacher_hint_sent", room_name=room_name, actor_name=student_name, role=user_role)
                st.session_state['hint_input_widget'] = "" # 전송 후 글상자 비우기

        hint_msg = st.empty()                
        if AI_HINT_ENABLED:
            if st.button("🪄 AI 힌트 초안 생성", use_container_width=True):
                hint_msg.info("👀 AI가 최근 대화 맥락을 읽고 있습니다...")
                time.sleep(1)
                
                context = "\n".join(df_all['content'].tail(5).tolist()) if not df_all.empty else "대화 없음"
                hint_msg.warning("✍️ AI가 예리한 질문을 작성하고 있습니다...")
                time.sleep(0.5)
                
                prompt = f"당신은 고등학교 {act_type} 조력자입니다. '{current_topic}' 주제로 {act_type} 중입니다. 학생들의 균형을 맞추거나 더 깊은 생각을 유도할 수 있는 예리한 질문을 1문장만 제안하세요. 번호 매기기나 번잡한 서론 없이 질문 자체만 출력하세요.\n최근 대화: {context}"
                res_text = generate_ai_response(
                    prompt,
                    "AI 힌트 생성 실패",
                    room_name=room_name,
                )
                if res_text:
                    st.session_state['hint_input_widget'] = res_text.strip().split('\n')[0]
                    st.session_state['ai_hint_manual_mode'] = False
                    hint_msg.success("✅ 힌트 작성 완료!")
                    time.sleep(1)
                else:
                    st.session_state['ai_hint_manual_mode'] = True
                    hint_msg.error("🚨 AI 호출 오류: 수동 입력 모드로 전환되었습니다.")
                    time.sleep(2)
                hint_msg.empty() # 작업 완료 후 알림창 자연스럽게 숨기기 (새로고침 없음!)
        else:
            st.session_state['ai_hint_manual_mode'] = True

        col_edit_txt, col_edit_btn = st.columns([8, 2])
        with col_edit_txt:
            # key를 부여하여 st.session_state와 완벽하게 동기화시킵니다.
            st.text_input("선생님의 검토 및 수정", key="hint_input_widget", label_visibility="collapsed", placeholder="여기에 AI 힌트가 나타납니다.")
        with col_edit_btn:
            # on_click 콜백을 사용하여 새로고침 없이 데이터를 DB에 꽂아 넣습니다.
            st.button("🚀 학생 화면 전송", use_container_width=True, type="primary", on_click=send_hint)
    
    teacher_hint_section()
    st.divider()

    # --- 3. 수업 종료 요약 리포트 (🔥 스크롤 고정 패치) ---
    @st.fragment
    def teacher_summary_section():
        st.subheader(f"📝 수업 종료 및 전체 {act_type} 요약 리포트")
        report_msg = st.empty()
        
        if st.button(f"{act_type} 요약 및 베스트 발언 추출 🪄", use_container_width=True):
            report_msg.info(f"👀 AI가 1차시 {act_type} 전체 기록을 꼼꼼히 읽고 있습니다...")
            time.sleep(1) 
            if not df_all.empty:
                full_history = "\n".join([f"[{row['student_name']} - {row['sentiment']}] {row['content']}" for _, row in df_all.iterrows()])
                report_msg.warning(f"✍️ AI가 {act_type} 요약 리포트를 작성하고 있습니다...")
                time.sleep(0.5)
                
                prompt = f"'{current_topic}' 주제의 고등학교 {act_type} 기록입니다.\n\n[엄격한 규칙]\n1. {act_type}의 전체 맥락을 파악하고 핵심 내용을 딱 3줄로 요약하세요.\n2. 가장 논리적이고 창의적인 주장을 펼친 '학생 이름' 1명과 그 이유를 구체적으로 추출하세요.\n3. 보고서 형식으로 깔끔하게 출력하세요.\n\n기록:\n{full_history}"
                res_text = generate_ai_response(
                    prompt,
                    "AI 요약 리포트 생성 실패",
                    room_name=room_name,
                )
                if res_text:
                    st.session_state['ai_report_text'] = res_text
                    report_msg.success("✅ 리포트 작성 완료!")
                    time.sleep(1)
                else:
                    report_msg.error("🚨 AI 호출 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
                    time.sleep(2)
            else:
                report_msg.error("🚨 분석할 데이터가 없습니다.")
                time.sleep(2)
            report_msg.empty()

        if st.session_state.get('ai_report_text'):
            st.info(f"📊 **AI 수업 {act_type} 요약 리포트**")
            st.markdown(st.session_state['ai_report_text'])
            
    teacher_summary_section()
    st.divider()

    # --- 4. 세특 생성 및 다운로드 (🔥 스크롤 고정 패치) ---
    @st.fragment
    def teacher_record_section():
        # [삭제] 버튼을 눌렀을 때 튕김 없이 조용히 DB만 지우는 함수
        def delete_selected_record():
            del_id = st.session_state.get('del_record_dropdown')
            if del_id:
                execute_query("DELETE FROM records WHERE id = %s", (del_id,))
                log_audit("record_deleted", room_name=room_name, actor_name=student_name, role=user_role, record_id=del_id)
                st.toast("기록이 삭제되었습니다.", icon="🗑️")

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
                record_msg = st.empty()
                
                if st.button(f"'{selected_student}' 세특 생성 🪄", use_container_width=True):
                    record_msg.info(f"👀 AI가 '{selected_student}' 학생의 활동 기록을 모아 읽고 있습니다...")
                    time.sleep(1)
                    try:
                        student_data = df_all[df_all['student_name'] == selected_student]
                        debate_history = "\n".join([f"- [{row['sentiment']}] {row['content']}" for _, row in student_data.iterrows()])
                        record_msg.warning(f"✍️ AI가 '{selected_student}' 학생의 세특 초안을 작성 중입니다...")
                        time.sleep(0.5)
                        prompt = f"당신은 정보 교사입니다. '{current_topic}' 주제 {act_type}에 참여한 '{selected_student}' 학생의 활동 기록입니다. 이를 바탕으로 생활기록부 교과세특 초안을 약 300자 내외로 작성하세요. 교육적 성장을 강조하세요.\n\n[활동 기록]\n{debate_history}"
                        res_text = generate_ai_response(
                            prompt,
                            "AI 세특 생성 실패",
                            room_name=room_name,
                            student=selected_student,
                        )
                        if not res_text:
                            raise RuntimeError("AI 응답이 비어 있습니다.")
                        st.session_state['ai_result_text'] = res_text
                        record_msg.warning("💾 작성 완료! 보관함에 안전하게 저장 중입니다...")
                        now = get_kst_now_str()
                        execute_query("INSERT INTO records (room_name, timestamp, student_name, content) VALUES (%s, %s, %s, %s)",
                                      (room_name, now, selected_student, res_text))
                        record_msg.success("✅ 세특 생성 및 보관함 저장 완료!")
                        time.sleep(1)
                    except Exception:
                        logger.exception("세특 생성 후처리 실패 (room_name=%s, student=%s)", room_name, selected_student)
                        record_msg.error("🚨 AI 호출 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
                        time.sleep(2)
                    record_msg.empty()
                
                if st.session_state.get('ai_result_text'):
                    st.success("🤖 **개인별 세특 초안** (보관함에 자동 저장되었습니다)")
                    st.text_area("내용 수정 후 복사하여 사용하세요", value=st.session_state['ai_result_text'], height=200, label_visibility="collapsed")
            else: st.info("실명 참여 학생이 없습니다.")

        st.divider()
        st.subheader("📂 저장된 세특 기록 보관함")
        
        # 내부에서 실시간으로 DB를 읽어와서 삭제 시 즉각 반영되도록 설계
        records_df = get_df_from_db(
            "SELECT id, timestamp, student_name, content FROM records WHERE room_name = %s ORDER BY id DESC LIMIT %s",
            (room_name, RECORDS_FETCH_LIMIT),
        )

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
                execute_query("DELETE FROM topic WHERE room_name = %s", (room_name,))
                execute_query("DELETE FROM debate WHERE room_name = %s", (room_name,))
                execute_query("DELETE FROM records WHERE room_name = %s", (room_name,))
                log_audit("room_destroyed", room_name=room_name, actor_name=student_name, role=user_role)
                st.success("성공적으로 파괴되었습니다.")
                st.session_state['ai_result_text'] = ""
                st.rerun() # 방 폭파는 화면 전체를 리셋해야 하므로 유일하게 허용!