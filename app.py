import streamlit as st
import pandas as pd
import io
from datetime import datetime
import psycopg2
import psycopg2.extras
import google.generativeai as genai
from streamlit_autorefresh import st_autorefresh

# --- [1. DB 연결] ---
@st.cache_resource(ttl=600)
def get_connection():
    return psycopg2.connect(st.secrets["SUPABASE_URL"])

def init_db():
    try:
        conn = get_connection()
        with conn.cursor() as c:
            c.execute('CREATE TABLE IF NOT EXISTS debate (id SERIAL PRIMARY KEY, room_name TEXT, timestamp TEXT, student_name TEXT, content TEXT, sentiment TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS records (id SERIAL PRIMARY KEY, room_name TEXT, timestamp TEXT, student_name TEXT, content TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS topic (room_name TEXT PRIMARY KEY, title TEXT, mode TEXT)')
        conn.commit()
    except: pass

init_db()

def get_df_from_db(query, params=()):
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute(query, params)
            return pd.DataFrame(c.fetchall(), columns=[desc[0] for desc in c.description]) if c.description else pd.DataFrame()
    except: return pd.DataFrame()

# --- [2. 앱 기본 설정 및 세션 초기화] ---
st.set_page_config(page_title="Talk-Trace AI", layout="wide")
if 'reset_key' not in st.session_state: st.session_state['reset_key'] = 0
if 'ai_result' not in st.session_state: st.session_state['ai_result'] = ""

# --- [3. 사이드바 (권한 및 💡자동새로고침 제어)] ---
with st.sidebar:
    st.header("👤 접속 권한")
    user_role = st.radio("모드 선택", ["학생", "교사"])
    
    # 🚨 [가장 중요한 해결책] 학생일 때만 자동 새로고침! 교사는 세특 작성 중 끊김 방지!
    if user_role == "학생":
        st_autorefresh(interval=7000, key="student_refresh")
        st.caption("🔄 학생 모드: 7초 실시간 동기화 켜짐")
    else:
        st.caption("⏸️ 교사 모드: 세특 작성 보호를 위해 동기화 꺼짐")

    rooms_df = get_df_from_db("SELECT DISTINCT room_name FROM topic")
    existing_rooms = rooms_df['room_name'].tolist() if not rooms_df.empty else []
    
    room_name = ""; teacher_auth = False
    if user_role == "교사":
        if st.text_input("교사 인증 암호", type="password") == "admin":
            teacher_auth = True; st.success("인증 성공!")
            room_opt = st.radio("방 선택", ["기존 방 선택", "새 방 만들기"])
            room_name = st.selectbox("목록", existing_rooms) if room_opt == "기존 방 선택" and existing_rooms else st.text_input("방 이름", value="정보_토론방")
    else: 
        room_name = st.text_input("🏠 접속할 방 이름", value="정보_토론방")
        
    student_name = st.text_input("내 이름", value="익명" if user_role == "학생" else "교사")

# --- [4. 토론 설정 및 AI 퍼실리테이터] ---
topic_df = get_df_from_db("SELECT title, mode FROM topic WHERE room_name = %s", (room_name,))
current_topic = topic_df.iloc[0]['title'] if not topic_df.empty else "자유 주제"
current_mode = topic_df.iloc[0]['mode'] if not topic_df.empty else "⚔️ 찬반 토론"

if user_role == "학생":
    last_msg_df = get_df_from_db("SELECT timestamp, student_name FROM debate WHERE room_name = %s ORDER BY id DESC LIMIT 1", (room_name,))
    if not last_msg_df.empty:
        last_time = datetime.strptime(last_msg_df.iloc[0]['timestamp'], "%Y-%m-%d %H:%M:%S")
        if (datetime.now() - last_time).total_seconds() > 15 and "AI" not in last_msg_df.iloc[0]['student_name']:
            try:
                genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                recent_msgs = get_df_from_db("SELECT content FROM debate WHERE room_name = %s ORDER BY id DESC LIMIT 3", (room_name,))
                context = "\n".join(recent_msgs['content'].tolist())
                res = genai.GenerativeModel('gemini-2.5-flash').generate_content(f"'{current_topic}' 토론이 조용합니다. 예리한 질문 1개만 던지세요:\n{context}")
                conn = get_connection()
                with conn.cursor() as c:
                    c.execute("INSERT INTO debate (room_name, timestamp, student_name, content, sentiment) VALUES (%s, %s, %s, %s, %s)",
                              (room_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "🤖 AI 조력자", res.text.strip(), "❓ 질문"))
                conn.commit(); st.rerun()
            except: pass

# --- [5. 메인 화면] ---
st.title(f"🎙️ Talk-Trace AI [{room_name}]")
st.info(f"**현재 주제:** {current_topic} ({current_mode})")

col1, col2 = st.columns([1, 1])
with col1:
    st.subheader("🗣️ 내 의견 작성")
    user_input = st.text_area("의견을 입력하세요", key=f"in_{st.session_state['reset_key']}", height=100)
    
    st.components.v1.html("""
        <button id="stt-btn" style="width:100%; padding:10px; border-radius:5px; border:none; background:#f0f2f6; cursor:pointer;">🎤 음성 인식 (말씀하세요)</button>
        <script>
            const btn = document.getElementById('stt-btn');
            const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
            recognition.lang = 'ko-KR';
            btn.onclick = () => { recognition.start(); btn.style.background = '#ff4b4b'; btn.innerText = '듣고 있어요...'; };
            recognition.onresult = (e) => {
                alert("인식 결과: " + e.results[0][0].transcript + "\\n복사해서 의견란에 붙여넣어 주세요!");
                btn.style.background = '#f0f2f6'; btn.innerText = '🎤 음성 인식 (말씀하세요)';
            };
        </script>""", height=60)
        
    opts = ["🔵 찬성", "🔴 반대"] if current_mode == "⚔️ 찬반 토론" else ["💡 아이디어", "➕ 보충", "❓ 질문"]
    sentiment = st.radio("성격", opts, horizontal=True)
    if st.button("의견 제출", use_container_width=True):
        if user_input.strip():
            conn = get_connection()
            with conn.cursor() as c:
                c.execute("INSERT INTO debate (room_name, timestamp, student_name, content, sentiment) VALUES (%s, %s, %s, %s, %s)",
                          (room_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), student_name, user_input, sentiment))
            conn.commit(); st.session_state['reset_key'] += 1; st.rerun()

with col2:
    st.subheader("📊 의견 통계")
    df = get_df_from_db("SELECT * FROM debate WHERE room_name = %s", (room_name,))
    if not df.empty:
        import plotly.express as px
        st.plotly_chart(px.pie(df, names="sentiment", hole=0.4), use_container_width=True)
    else: st.write("의견 대기 중...")

st.divider()
st.subheader("💬 전체 의견 보기")
if not df.empty:
    for _, row in df.sort_values(by="id", ascending=False).iterrows():
        with st.chat_message("user" if "AI" not in row['student_name'] else "assistant"):
            st.write(f"**{row['student_name']}** ({row['sentiment']}) - {row['timestamp']}")
            st.info(row['content'])

# --- [6. 교사 전용 도구 (세특 끊김 방지 완벽 적용!)] ---
if user_role == "교사" and teacher_auth:
    st.divider(); st.header("👨‍🏫 교사 관리 대시보드")
    col3, col4 = st.columns([1, 1])
    
    with col3:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer: df.to_excel(writer, index=False)
        st.download_button("📥 전체 로그 다운로드", data=buffer.getvalue(), file_name=f"{room_name}_log.xlsx")
        # 교사는 자동 갱신이 꺼져있으므로 수동 갱신 버튼 제공
        if st.button("🔄 학생들 새 의견 불러오기"): st.rerun()
    
    with col4:
        st.subheader("🤖 AI 세특 초안 생성")
        student_list = df[~df['student_name'].isin(['교사', '익명', '🤖 AI 조력자'])]['student_name'].unique()
        if len(student_list) > 0:
            sel_std = st.selectbox("학생 선택", student_list)
            if st.button(f"'{sel_std}' AI 세특 생성 🪄"):
                with st.spinner("Gemini AI 분석 중... (절대 안 끊깁니다!)"):
                    try:
                        std_hist = "\n".join(df[df['student_name'] == sel_std]['content'].tolist())
                        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                        res = genai.GenerativeModel('gemini-2.5-flash').generate_content(f"정보 교사로서 '{current_topic}' 토론에 참여한 '{sel_std}' 학생의 세특 300자:\n{std_hist}")
                        
                        st.session_state['ai_result'] = res.text
                        
                        conn = get_connection()
                        with conn.cursor() as c:
                            c.execute("INSERT INTO records (room_name, timestamp, student_name, content) VALUES (%s, %s, %s, %s)",
                                      (room_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sel_std, res.text))
                        conn.commit()
                        st.success("보관함에 자동 저장되었습니다!")
                        st.rerun() # 저장 직후 아래 표에 반영하기 위해 안전하게 새로고침
                        
                    except Exception as e:
                        st.error(f"오류: {e}")
            
            if st.session_state['ai_result']:
                st.text_area("생성 결과 (복사하세요)", value=st.session_state['ai_result'], height=200)
        else:
            st.info("실명 참여 학생이 없습니다.")

    st.subheader("📂 세특 보관함")
    rec_df = get_df_from_db("SELECT timestamp, student_name, content FROM records WHERE room_name = %s ORDER BY id DESC", (room_name,))
    if not rec_df.empty:
        st.dataframe(rec_df, use_container_width=True)
        buf_rec = io.BytesIO()
        with pd.ExcelWriter(buf_rec, engine='openpyxl') as writer: rec_df.to_excel(writer, index=False)
        st.download_button("📥 세특 기록 다운로드", data=buf_rec.getvalue(), file_name=f"{room_name}_세특.xlsx")
