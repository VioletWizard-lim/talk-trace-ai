import streamlit as st
import pandas as pd
import os
import io
from datetime import datetime
import psycopg2
import psycopg2.extras
import google.generativeai as genai

# --- [1. ⚡ 초고속 클라우드 연결 설정 (IPv4 우회 통로 완벽 적용!)] ---
@st.cache_resource(ttl=600)
def get_connection():
    db_url = st.secrets["SUPABASE_URL"]
    return psycopg2.connect(db_url)

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
if 'reset_key' not in st.session_state: st.session_state['reset_key'] = 0

# --- [3. 사이드바 설정 (권한 및 방 접속)] ---
with st.sidebar:
    st.header("👤 접속 권한")
    user_role = st.radio("모드 선택", ["학생", "교사"])
    
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

# --- [4. 동아리 수업 주제 관리] ---
topic_df = get_df_from_db("SELECT title, mode FROM topic WHERE room_name = %s", (room_name,))
current_topic = topic_df.iloc[0]['title'] if not topic_df.empty else "자유 주제로 대화해 봅시다."
current_mode = topic_df.iloc[0]['mode'] if not topic_df.empty else "⚔️ 찬반 토론"

if user_role == "교사" and teacher_auth:
    with st.sidebar:
        st.divider()
        st.subheader("📢 동아리 설정")
        new_mode = st.radio("모드 변경", ["⚔️ 찬반 토론", "🤝 자유 토의"])
        new_topic = st.text_input("주제 변경", value=current_topic)
        if st.button("설정 적용"):
            conn = get_connection()
            with conn.cursor() as c:
                c.execute("INSERT INTO topic (room_name, title, mode) VALUES (%s, %s, %s) ON CONFLICT (room_name) DO UPDATE SET title=EXCLUDED.title, mode=EXCLUDED.mode", (room_name, new_topic, new_mode))
            conn.commit()
            st.rerun()

# --- [5. 메인 화면 (학생 토론 영역)] ---
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

# --- [5.5 🔄 새로고침 및 🤖 15초 AI 퍼실리테이터] ---
col_ref, col_space = st.columns([1, 4])
with col_ref:
    if st.button("🔄 실시간 새로고침", use_container_width=True):
        st.rerun()

# 15초 침묵 감지 로직
last_msg_df = get_df_from_db("SELECT timestamp, student_name FROM debate WHERE room_name = %s ORDER BY id DESC LIMIT 1", (room_name,))
if not last_msg_df.empty:
    last_time_str = last_msg_df.iloc[0]['timestamp']
    last_speaker = last_msg_df.iloc[0]['student_name']
    
    last_time = datetime.strptime(last_time_str, "%Y-%m-%d %H:%M:%S")
    time_diff = (datetime.now() - last_time).total_seconds()
    
    # 15초 경과 & 마지막 발언자가 AI가 아닐 때 발동!
    if time_diff > 15 and "AI" not in last_speaker:
        with st.spinner("🤖 AI 조력자가 토론의 열기를 띄울 질문을 고민 중입니다..."):
            try:
                recent_msgs = get_df_from_db("SELECT content FROM debate WHERE room_name = %s ORDER BY id DESC LIMIT 3", (room_name,))
                context = "\n".join(recent_msgs['content'].tolist())
                
                genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                model = genai.GenerativeModel('gemini-2.5-flash') # ✅ 2.5 최신 모델 원상 복구!
                
                prompt = f"""
                당신은 고등학교 정보 토론 동아리의 AI 조력자입니다. 
                주제: '{current_topic}'
                
                현재 학생들이 15초 이상 침묵하고 있습니다. 아래 최근 토론 내용을 읽고, 
                학생들이 다시 활발하게 토론할 수 있도록 호기심을 자극하는 짧고 예리한 질문을 딱 1개만 던져주세요.
                (정답을 알려주지 말고, 새로운 생각의 방향을 제시할 것)
                
                [최근 토론 내용]
                {context}
                """
                response = model.generate_content(prompt)
                ai_question = response.text.strip()
                
                conn = get_connection()
                with conn.cursor() as c:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    c.execute("INSERT INTO debate (room_name, timestamp, student_name, content, sentiment) VALUES (%s, %s, %s, %s, %s)",
                              (room_name, now, "🤖 AI 조력자", ai_question, "❓ 질문"))
                conn.commit()
                st.rerun() # AI 질문 등록 후 화면 강제 새로고침
            except Exception as e:
                pass # 에러 발생 시 토론 흐름을 끊지 않기 위해 조용히 넘어감

# --- [6. 전체 의견 보기] ---
st.subheader("💬 전체 의견 보기")
if not df.empty:
    for _, row in df.sort_values(by="id", ascending=False).iterrows():
        # 교사와 AI의 아이콘을 구분하여 표시
        with st.chat_message("user" if "AI" not in row['student_name'] and "교사" not in row['student_name'] else "assistant"):
            st.write(f"**{row['student_name']}** ({row['sentiment']}) - {row['timestamp']}")
            st.info(row['content'])

# --- [7. 교사 전용: 데이터 다운로드 및 AI 세특 자동 생성] ---
if user_role == "교사" and teacher_auth:
    st.divider()
    st.header("👨‍🏫 교사 관리 대시보드")
    
    col3, col4 = st.columns([1, 1])
    
    with col3:
        st.subheader("📥 활동 데이터 다운로드")
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False)
        st.download_button("전체 활동 로그 다운로드 (Excel)", data=buffer.getvalue(), file_name=f"{room_name}_log.xlsx")

    with col4:
        st.subheader("🤖 AI 세특 초안 생성")
        if not df.empty:
            # AI, 교사, 익명 사용자는 세특 목록에서 제외
            student_list = df[~df['student_name'].isin(['교사', '익명', '🤖 AI 조력자'])]['student_name'].unique()
            
            if len(student_list) > 0:
                selected_student = st.selectbox("분석할 학생을 선택하세요", student_list)
                
                if st.button(f"'{selected_student}' 학생 세특 생성 🪄"):
                    with st.spinner("Gemini AI가 학생의 활동을 분석하여 세특을 작성 중입니다..."):
                        try:
                            student_data = df[df['student_name'] == selected_student]
                            debate_history = "\n".join([f"- [{row['sentiment']}] {row['content']}" for _, row in student_data.iterrows()])
                            
                            genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                            model = genai.GenerativeModel('gemini-2.5-flash') # ✅ 2.5 최신 모델 원상 복구!
                            
                            prompt = f"""
                            당신은 고등학교 정보 교사입니다. 다음은 '{current_topic}'을(를) 주제로 한 동아리 토론에서 '{selected_student}' 학생이 발언한 내용입니다.
                            이 내용을 바탕으로 학교생활기록부 교과세부능력 및 특기사항(세특)에 들어갈 초안을 300자 내외로 작성해주세요.
                            학생의 논리적 사고력, 문제 해결 능력, 참여도를 긍정적이고 전문적인 교육용 어휘로 평가해주세요.

                            [학생 발언 기록]
                            {debate_history}
                            """
                            response = model.generate_content(prompt)
                            
                            st.success(f"✅ {selected_student} 학생의 세특 초안이 완성되었습니다!")
                            st.text_area("AI 생성 결과 (수정 후 복사하여 사용하세요)", value=response.text, height=250)
                            
                            # ⬇️ 여기서부터 6줄 추가! (미리 만들어둔 records 테이블에 저장)
                            conn = get_connection()
                            with conn.cursor() as c:
                                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                c.execute("INSERT INTO records (room_name, timestamp, student_name, content) VALUES (%s, %s, %s, %s)",
                                          (room_name, now, selected_student, response.text))
                            conn.commit()
                            st.info("💾 생성된 세특 초안이 수파베이스(records 테이블)에 안전하게 보관되었습니다.")
                            
                        except Exception as e:
                            st.error(f"AI 생성 중 오류 발생: {e}\n(Secrets에 GEMINI_API_KEY가 정확한지 확인해주세요!)")
            else:
                st.info("아직 실명으로 의견을 제출한 학생이 없습니다.")
