import streamlit as st
import pandas as pd
import os
import io
from datetime import datetime, timedelta
import psycopg2
import psycopg2.extras
from google import genai


# --- [진짜 마지막! 금고 내용물 체크리스트] ---
with st.expander("🔍 내 비밀 금고(Secrets)에 뭐가 들어있을까?"):
    keys = list(st.secrets.keys())
    if not keys:
        st.error("🚨 금고가 텅 비어있습니다! 스트림릿 Secrets 설정을 확인하세요.")
    else:
        st.write(f"현재 인식된 이름들: `{keys}`")
        for key in keys:
            # 보안을 위해 비밀번호나 키는 길이만 표시합니다.
            if "PW" in key.upper() or "KEY" in key.upper() or "URL" in key.upper():
                st.write(f"✅ **{key}**: [보안상 마스킹] (길이: {len(str(st.secrets[key]))}자)")
            else:
                st.write(f"✅ **{key}**: `{st.secrets[key]}`")
# ------------------------------------------
# --- [1. ⚡ 초고속 클라우드 연결 설정] ---
@st.cache_resource(ttl=600)
def get_connection():
    # 수파베이스가 준 '공식 주소'를 그대로 사용하여 연결합니다.
    # 이 방식이 가장 오류가 적고 확실합니다.
    db_url = st.secrets["SUPABASE_URL"]
    return psycopg2.connect(db_url)

def init_db():
    try:
        conn = get_connection()
        with conn.cursor() as c:
            # 토론 데이터 테이블
            c.execute('''CREATE TABLE IF NOT EXISTS debate 
                         (id SERIAL PRIMARY KEY, room_name TEXT, timestamp TEXT, student_name TEXT, content TEXT, sentiment TEXT)''')
            # 세특 기록 테이블
            c.execute('''CREATE TABLE IF NOT EXISTS records 
                         (id SERIAL PRIMARY KEY, room_name TEXT, timestamp TEXT, student_name TEXT, content TEXT)''')
            # 수업 설정 테이블
            c.execute('''CREATE TABLE IF NOT EXISTS topic 
                         (room_name TEXT PRIMARY KEY, title TEXT, mode TEXT)''')
        conn.commit()
    except Exception as e:
        st.error(f"🚨 DB 연결 실패: {e}")
        st.stop()

# DB 실행
init_db()

def get_df_from_db(query, params=()):
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute(query, params)
            data = c.fetchall()
            columns = [desc[0] for desc in c.description] if c.description else []
            return pd.DataFrame(data, columns=columns)
    except:
        return pd.DataFrame()

# --- [2. 앱 기본 설정] ---
st.set_page_config(page_title="Talk-Trace AI", layout="wide")

# 세션 상태 초기화
if 'reset_key' not in st.session_state: st.session_state['reset_key'] = 0
if 'input_text' not in st.session_state: st.session_state['input_text'] = ""

# --- [3. 사이드바 설정] ---
with st.sidebar:
    st.header("👤 접속 권한")
    user_role = st.radio("모드 선택", ["학생", "교사"])
    
    # 기존 방 목록 가져오기
    rooms_df = get_df_from_db("SELECT DISTINCT room_name FROM topic")
    existing_rooms = rooms_df['room_name'].tolist() if not rooms_df.empty else []
    
    room_name = ""
    teacher_auth = False
    
    if user_role == "교사":
        pw = st.text_input("교사 인증 암호", type="password")
        if pw == "admin":
            teacher_auth = True
            st.success("인증 성공!")
            room_opt = st.radio("방 선택", ["기존 방 선택", "새 방 만들기"])
            if room_opt == "기존 방 선택" and existing_rooms:
                room_name = st.selectbox("토론방 목록", existing_rooms)
            else:
                room_name = st.text_input("방 이름 입력", value="정보_토론방")
    else:
        room_name = st.text_input("🏠 접속할 방 이름", value="정보_토론방")
    
    student_name = st.text_input("내 이름", value="익명" if user_role == "학생" else "교사")

# --- [4. 수업 주제 관리] ---
topic_df = get_df_from_db("SELECT title, mode FROM topic WHERE room_name = %s", (room_name,))
current_topic = topic_df.iloc[0]['title'] if not topic_df.empty else "자유 주제로 대화해 봅시다."
current_mode = topic_df.iloc[0]['mode'] if not topic_df.empty else "⚔️ 찬반 토론"

if user_role == "교사" and teacher_auth:
    with st.sidebar:
        st.divider()
        st.subheader("📢 수업 설정")
        new_mode = st.radio("모드 변경", ["⚔️ 찬반 토론", "🤝 자유 토의"])
        new_topic = st.text_input("주제 변경", value=current_topic)
        if st.button("설정 적용"):
            conn = get_connection()
            with conn.cursor() as c:
                c.execute("INSERT INTO topic (room_name, title, mode) VALUES (%s, %s, %s) ON CONFLICT (room_name) DO UPDATE SET title=EXCLUDED.title, mode=EXCLUDED.mode", (room_name, new_topic, new_mode))
            conn.commit()
            st.rerun()

# --- [5. 메인 화면] ---
st.title(f"🎙️ Talk-Trace AI [{room_name}]")
st.info(f"**현재 주제:** {current_topic} ({current_mode})")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("🗣️ 내 의견 작성")
    text_key = f"input_{st.session_state['reset_key']}"
    user_input = st.text_area("의견을 입력하세요", key=text_key, height=150)
    
    opts = ["🔵 찬성", "🔴 반대"] if current_mode == "⚔️ 찬반 토론" else ["💡 아이디어", "➕ 보충", "❓ 질문"]
    sentiment = st.radio("의견 성격", opts, horizontal=True)
    
    if st.button("의견 제출", use_container_width=True):
        if user_input.strip():
            conn = get_connection()
            with conn.cursor() as c:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.execute("INSERT INTO debate (room_name, timestamp, student_name, content, sentiment) VALUES (%s, %s, %s, %s, %s)",
                          (room_name, now, student_name, user_input, sentiment))
            conn.commit()
            st.session_state['reset_key'] += 1
            st.rerun()

with col2:
    st.subheader("📊 실시간 의견 통계")
    df = get_df_from_db("SELECT * FROM debate WHERE room_name = %s", (room_name,))
    if not df.empty:
        import plotly.express as px
        fig = px.pie(df, names="sentiment", hole=0.4)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.write("아직 제출된 의견이 없습니다.")

st.divider()
st.subheader("💬 전체 의견 보기")
if not df.empty:
    for _, row in df.sort_values(by="id", ascending=False).iterrows():
        with st.chat_message("user" if "AI" not in row['student_name'] else "assistant"):
            st.write(f"**{row['student_name']}** ({row['sentiment']}) - {row['timestamp']}")
            st.info(row['content'])

# --- [6. 교사 전용 관리 도구] ---
if user_role == "교사" and teacher_auth:
    st.divider()
    st.subheader("👨‍🏫 생활기록부 관리")
    
    # 엑셀 다운로드
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    st.download_button("📥 전체 활동 로그 다운로드 (Excel)", data=buffer.getvalue(), file_name=f"{room_name}_log.xlsx")
    
    # AI 세특 생성 로직 (생략 가능하나 구조 유지)
    st.write("*(학생 이름을 클릭하여 AI 세특 초안을 생성할 수 있습니다)*")
