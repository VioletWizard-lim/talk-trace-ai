import streamlit as st
import pandas as pd
import os
import sys
import subprocess
import io
from datetime import datetime, timedelta
from dotenv import load_dotenv

# --- [0. 라이브러리 자동 설치] ---
def install_requirements():
    try:
        from streamlit_autorefresh import st_autorefresh
        from google import genai
        import psycopg2
    except ImportError:
        st.info("🔄 필수 라이브러리를 설치 중입니다...")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", 
            "streamlit-autorefresh", "google-genai", 
            "SpeechRecognition", "pyaudio", "plotly", 
            "python-dotenv", "openpyxl", "psycopg2-binary"
        ])
        st.success("✅ 설치 완료! 새로고침(F5) 해주세요.")
        st.stop()

install_requirements()

from streamlit_autorefresh import st_autorefresh
from google import genai
import speech_recognition as sr
import psycopg2
import psycopg2.extras

# 환경변수 강제 업데이트
load_dotenv(override=True)
MY_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")

# --- [1. ⚡ 초고속 클라우드 연결 유지 (캐싱)] ---
@st.cache_resource(ttl=600)
def get_connection():
    return psycopg2.connect(SUPABASE_URL)

def init_db():
    try:
        conn = get_connection()
        with conn.cursor() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS debate 
                         (id SERIAL PRIMARY KEY, room_name TEXT, timestamp TEXT, student_name TEXT, content TEXT, sentiment TEXT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS records 
                         (id SERIAL PRIMARY KEY, room_name TEXT, timestamp TEXT, student_name TEXT, content TEXT)''')
            c.execute('''CREATE TABLE IF NOT EXISTS topic 
                         (room_name TEXT PRIMARY KEY, title TEXT, mode TEXT)''')
        conn.commit()
    except Exception as e:
        st.error(f"🚨 DB 연결 실패: {e}")
        st.stop()

init_db()

def get_df_from_db(query, params=()):
    conn = get_connection()
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
        c.execute(query, params)
        data = c.fetchall()
        columns = [desc[0] for desc in c.description] if c.description else []
        return pd.DataFrame(data, columns=columns)

# --- [2. 세션 상태 관리] ---
if 'is_writing' not in st.session_state: st.session_state['is_writing'] = False
if 'input_text' not in st.session_state: st.session_state['input_text'] = ""
if 'reset_key' not in st.session_state: st.session_state['reset_key'] = 0
if 'target_student_name' not in st.session_state: st.session_state['target_student_name'] = ""

@st.cache_resource
def get_ai_lock(): return {"is_generating": False}
ai_lock = get_ai_lock()

if not st.session_state.get('is_writing', False):
    st_autorefresh(interval=5000, limit=100000, key="global_refresh")

# --- [3. UI 설정 및 사이드바] ---
st.set_page_config(page_title="Talk-Trace AI", layout="wide")

def get_existing_rooms():
    try:
        df = get_df_from_db("SELECT DISTINCT room_name FROM topic UNION SELECT DISTINCT room_name FROM debate")
        return [r for r in df['room_name'].tolist() if r]
    except: return []

with st.sidebar:
    st.header("👤 접속 권한")
    user_role = st.radio("모드 선택", ["학생", "교사"])
    
    existing_rooms = get_existing_rooms()
    room_name = "" 
    teacher_authenticated = False
    
    if user_role == "교사":
        password = st.text_input("교사 인증 암호", type="password")
        if password == "admin": 
            teacher_authenticated = True
            st.success("인증되었습니다.")
            st.divider()
            st.subheader("🏠 토론방 설정")
            
            if existing_rooms:
                room_opt = st.radio("방 접속 방식", ["기존 방 선택", "새로운 방 만들기"])
                if room_opt == "기존 방 선택":
                    room_name = st.selectbox("개설된 토론방 목록", existing_rooms)
                    with st.expander("🛠️ 현재 방 이름 변경"):
                        new_room_name = st.text_input("새로운 방 이름 입력", key="rename_input")
                        if st.button("이름 싹 바꾸기", use_container_width=True):
                            new_room_name = new_room_name.strip()
                            if new_room_name and new_room_name not in existing_rooms:
                                conn = get_connection()
                                with conn.cursor() as c:
                                    c.execute("UPDATE topic SET room_name = %s WHERE room_name = %s", (new_room_name, room_name))
                                    c.execute("UPDATE debate SET room_name = %s WHERE room_name = %s", (new_room_name, room_name))
                                    c.execute("UPDATE records SET room_name = %s WHERE room_name = %s", (new_room_name, room_name))
                                conn.commit()
                                st.toast("✅ 방 이름 변경 완료!", icon="✨")
                                st.rerun()
                else: 
                    room_name = st.text_input("새로운 토론방 이름", value="새로운_방")
            else: 
                room_name = st.text_input("새로운 토론방 이름", value="동아리_토론방")
    else:
        room_name = st.text_input("🏠 접속할 방 이름 (선생님 안내)", value="")
            
    st.divider()
    student_name = st.text_input("내 이름", value="익명" if user_role == "학생" else "교사")

    if user_role == "교사" and teacher_authenticated:
        st.divider()
        st.subheader("📢 현재 방의 수업 설정")
        new_mode = st.radio("수업 모드", ["⚔️ 찬반 토론", "🤝 자유 토의"], horizontal=True)
        new_topic = st.text_input("새로운 주제를 입력하세요")
        
        if st.button("주제 및 모드 적용", use_container_width=True):
            if new_topic.strip():
                conn = get_connection()
                with conn.cursor() as c:
                    c.execute('''INSERT INTO topic (room_name, title, mode) VALUES (%s, %s, %s) 
                                 ON CONFLICT (room_name) DO UPDATE SET title = EXCLUDED.title, mode = EXCLUDED.mode''', 
                              (room_name, new_topic, new_mode))
                conn.commit()
                st.toast("✅ 설정 변경 완료!", icon="🎯")
                st.rerun()

# --- [4. 메인 화면] ---
topic_df = get_df_from_db("SELECT title, mode FROM topic WHERE room_name = %s", (room_name,))
current_topic = topic_df.iloc[0]['title'] if not topic_df.empty else "자유롭게 의견을 나누어 봅시다."
current_mode = topic_df.iloc[0]['mode'] if not topic_df.empty else "⚔️ 찬반 토론"

st.title(f"🎙️ Talk-Trace AI [{room_name}]")
st.info(f"**{current_mode} 주제:** {current_topic}")

df = get_df_from_db("SELECT * FROM debate WHERE room_name = %s", (room_name,))

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("🗣️ 내 의견 말하기")
    
    # 음성 인식 기능
    if st.button("🎙️ 음성 인식 시작"):
        r = sr.Recognizer()
        with sr.Microphone() as source:
            st.toast("듣고 있습니다... 🎤")
            try:
                audio = r.listen(source, timeout=5, phrase_time_limit=10)
                st.session_state['input_text'] = r.recognize_google(audio, language='ko-KR')
                st.rerun()
            except: st.error("음성 인식 실패.")
            
    current_key = f"text_area_{st.session_state['reset_key']}"
    user_input = st.text_area("의견 내용", value=st.session_state['input_text'], key=current_key, height=100)
    sentiment_options = ["🔵 찬성", "🔴 반대"] if current_mode == "⚔️ 찬반 토론" else ["💡 아이디어 제안", "➕ 보충 설명", "❓ 질문"]
    sentiment = st.radio("나의 의견 유형", sentiment_options, horizontal=True) 
    
    if st.button("의견 제출"):
        if user_input.strip():
            conn = get_connection()
            with conn.cursor() as c:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.execute("INSERT INTO debate (room_name, timestamp, student_name, content, sentiment) VALUES (%s, %s, %s, %s, %s)",
                          (room_name, now, student_name, user_input, sentiment))
            conn.commit()
            st.session_state['input_text'] = ""
            st.session_state['reset_key'] += 1
            st.toast("✅ 의견 제출 완료!", icon="🎉")
            st.rerun()

with col2:
    st.subheader("📊 실시간 의견 지형도")
    chart_df = df[df['sentiment'].isin(["🔵 찬성", "🔴 반대", "💡 아이디어 제안", "➕ 보충 설명", "❓ 질문"])]
    if not chart_df.empty:
        import plotly.express as px
        color_map = {'🔵 찬성': '#1f77b4', '🔴 반대': '#ff7f0e', '💡 아이디어 제안': '#2ca02c', '➕ 보충 설명': '#9467bd', '❓ 질문': '#e377c2'}
        fig = px.pie(chart_df, names="sentiment", hole=0.4, color="sentiment", color_discrete_map=color_map)
        st.plotly_chart(fig, use_container_width=True)
    else: st.info("데이터가 충분하지 않습니다.")

st.divider()
st.subheader("💬 실시간 게시판")
if not df.empty:
    with st.container(height=300):
        display_df = df.sort_values(by='id', ascending=False)
        for _, row in display_df.iterrows():
            st.markdown(f"**{row['student_name']}** `{row['sentiment']}` *({row['timestamp'][11:16]})*")
            st.info(row['content'])

# --- [5. AI 자동 퍼실리테이터] ---
if not df.empty and not ai_lock.get('is_generating', False):
    last_row = df.iloc[-1]
    last_time = datetime.strptime(last_row['timestamp'], "%Y-%m-%d %H:%M:%S")
    if (datetime.now() - last_time > timedelta(seconds=15)) and ("AI" not in str(last_row['student_name'])):
        ai_lock['is_generating'] = True
        try:
            client = genai.Client(api_key=MY_GEMINI_API_KEY)
            context = "\n".join(df['content'].tail(5).tolist())
            prompt = f"현재 수업 모드는 '{current_mode}'이고, 주제는 '{current_topic}'입니다.\n지금까지 내용:\n{context}\n\n이 주제와 맥락을 바탕으로 학생들의 논리가 맞서거나 브레인스토밍을 촉진할 수 있도록 날카로운 꼬리 질문을 부드럽게 한 문장으로 작성해."
            response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            
            conn = get_connection()
            with conn.cursor() as c:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.execute("INSERT INTO debate (room_name, timestamp, student_name, content, sentiment) VALUES (%s, %s, %s, %s, %s)",
                          (room_name, now, "🤖 AI 가이드", response.text, "🤖 AI 가이드"))
            conn.commit()
            ai_lock['is_generating'] = False
            st.rerun()
        except: ai_lock['is_generating'] = False

# --- [6. 교사 전용 패널 (엑셀 다운로드 복구!)] ---
if user_role == "교사" and teacher_authenticated:
    st.divider()
    st.subheader(f"👨‍🏫 교사 패널 [{room_name} 관리]")

    if st.session_state.get('is_writing', False):
        target = st.session_state['target_student_name']
        with st.status(f"🚀 {target} 학생 세특 작성 중...") as status:
            try:
                client = genai.Client(api_key=MY_GEMINI_API_KEY)
                s_text = "\n".join(df[df['student_name'] == target]['content'].tolist())
                prompt = f"당신은 정보교사입니다. 다음 학생의 '{current_mode}' 발언을 토대로 생활기록부 세부능력 및 특기사항을 작성하세요. 명사형 종결(~함, ~임) 사용. 서두 생략. 400자 내외.\n\n내용:\n{s_text}"
                response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
                
                conn = get_connection()
                with conn.cursor() as c:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    c.execute("INSERT INTO records (room_name, timestamp, student_name, content) VALUES (%s, %s, %s, %s)",
                              (room_name, now, target, response.text))
                conn.commit()
                st.session_state['is_writing'] = False
                st.rerun()
            except Exception as e: 
                st.error(f"오류: {e}")
                st.session_state['is_writing'] = False

    tab1, tab2 = st.tabs(["📋 활동 로그", "✍️ 세특 보관함"])

    with tab1:
        st.dataframe(df.sort_values(by="id", ascending=False), use_container_width=True)
        
        # 엑셀 다운로드 버튼 복구
        col_d1, col_d2 = st.columns([1, 1])
        with col_d1:
            buffer_db = io.BytesIO()
            with pd.ExcelWriter(buffer_db, engine='openpyxl') as writer:
                df.sort_values(by="id", ascending=False).to_excel(writer, index=False, sheet_name='활동로그')
            st.download_button("📥 현재 방 로그 엑셀 다운로드", data=buffer_db.getvalue(), file_name=f"{room_name}_log.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            
        with col_d2:
            if st.button("⚠️ 현재 방 데이터 초기화", use_container_width=True):
                conn = get_connection()
                with conn.cursor() as c: c.execute("DELETE FROM debate WHERE room_name = %s", (room_name,))
                conn.commit()
                st.rerun()

    with tab2:
        students = df[~df['student_name'].str.contains("AI", na=False)]['student_name'].unique()
        if len(students) > 0:
            col_a, col_b = st.columns([10, 2])
            with col_a:
                selected = st.selectbox("학생 선택", students)
            with col_b:
                st.markdown('<div style="margin-top: 28px;"></div>', unsafe_allow_html=True)
                if st.button("🚀 세특 생성", use_container_width=True):
                    st.session_state['is_writing'] = True
                    st.session_state['target_student_name'] = selected
                    st.rerun()
        
        records_df = get_df_from_db("SELECT * FROM records WHERE room_name = %s ORDER BY id DESC", (room_name,))
        if not records_df.empty:
            st.divider()
            col_h, col_ex = st.columns([4, 2])
            with col_h: 
                st.markdown(f"#### 📁 [{room_name}] 세특 보관함 ({len(records_df)}건)")
            with col_ex:
                # 세특 엑셀 다운로드 복구
                buffer_rec = io.BytesIO()
                with pd.ExcelWriter(buffer_rec, engine='openpyxl') as writer:
                    records_df.to_excel(writer, index=False, sheet_name='세특기록')
                st.download_button("📊 세특 전체 엑셀 다운로드", data=buffer_rec.getvalue(), file_name=f"{room_name}_records.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

            for _, row in records_df.iterrows():
                with st.expander(f"📌 {row['student_name']} ({row['timestamp']})"):
                    st.write(row['content'])
                    if st.button("🗑️ 삭제", key=f"del_{row['id']}"):
                        conn = get_connection()
                        with conn.cursor() as c: c.execute("DELETE FROM records WHERE id = %s", (row['id'],))
                        conn.commit()
                        st.rerun()