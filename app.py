import streamlit as st
import pandas as pd
import io
from datetime import datetime
import psycopg2
import psycopg2.extras
import google.generativeai as genai

# ==========================================
# [1] 데이터베이스 연결 및 초기화
# ==========================================
@st.cache_resource(ttl=600)
def get_connection():
    db_url = st.secrets["SUPABASE_URL"]
    return psycopg2.connect(db_url)

def init_db():
    try:
        conn = get_connection()
        with conn.cursor() as c:
            c.execute('CREATE TABLE IF NOT EXISTS debate (id SERIAL PRIMARY KEY, room_name TEXT, timestamp TEXT, student_name TEXT, content TEXT, sentiment TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS records (id SERIAL PRIMARY KEY, room_name TEXT, timestamp TEXT, student_name TEXT, content TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS topic (room_name TEXT PRIMARY KEY, title TEXT, mode TEXT)')
        conn.commit()
    except Exception as e:
        st.error(f"🚨 DB 연결 실패: {e}"); st.stop()

init_db()

def get_df_from_db(query, params=()):
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute(query, params)
            data = c.fetchall()
            return pd.DataFrame(data, columns=[desc[0] for desc in c.description] if c.description else [])
    except Exception as e:
        return pd.DataFrame()

# ==========================================
# [2] 앱 기본 설정 및 세션 초기화
# ==========================================
st.set_page_config(page_title="Talk-Trace AI", layout="wide")

if 'reset_key' not in st.session_state: st.session_state['reset_key'] = 0
if 'ai_result_text' not in st.session_state: st.session_state['ai_result_text'] = ""

# ==========================================
# [3] 사이드바 설정 (방 접속 권한)
# ==========================================
with st.sidebar:
    st.header("👤 접속 권한")
    user_role = st.radio("모드 선택", ["학생", "교사"])
    st.caption("✨ 최신 실시간 동기화 엔진 적용 완료 (깜빡임 방지)")
    st.divider()

    rooms_df = get_df_from_db("SELECT DISTINCT room_name FROM topic")
    existing_rooms = rooms_df['room_name'].tolist() if not rooms_df.empty else []
    room_name = ""; teacher_auth = False
    
    if user_role == "교사":
        pw = st.text_input("교사 인증 암호", type="password")
        if pw == "admin":
            teacher_auth = True; st.success("인증 성공!")
            room_opt = st.radio("방 선택", ["기존 방 선택", "새 방 만들기"])
            room_name = st.selectbox("토론방 목록", existing_rooms) if room_opt == "기존 방 선택" and existing_rooms else st.text_input("방 이름 입력", value="정보_토론방")
    else:
        room_name = st.text_input("🏠 접속할 방 이름", value="정보_토론방")
        
    student_name = st.text_input("내 이름", value="익명" if user_role == "학생" else "교사")

# ==========================================
# [4] 방 주제 설정
# ==========================================
topic_df = get_df_from_db("SELECT title, mode FROM topic WHERE room_name = %s", (room_name,))
current_topic = topic_df.iloc[0]['title'] if not topic_df.empty else "자유 주제로 대화해 봅시다."
current_mode = topic_df.iloc[0]['mode'] if not topic_df.empty else "⚔️ 찬반 토론"

st.title(f"🎙️ Talk-Trace AI [{room_name}]")
st.info(f"**현재 주제:** {current_topic} ({current_mode})")

# ==========================================
# [5] 의견 입력 영역 (고정 영역 - 깜빡이지 않음!)
# ==========================================
st.subheader("🗣️ 내 의견 작성")
col_input, col_stt = st.columns([4, 1])

with col_input:
    user_input = st.text_area("의견을 입력하세요", key=f"input_{st.session_state['reset_key']}", height=80, label_visibility="collapsed")
    opts = ["🔵 찬성", "🔴 반대"] if current_mode == "⚔️ 찬반 토론" else ["💡 아이디어", "➕ 보충", "❓ 질문"]
    sentiment = st.radio("의견 성격", opts, horizontal=True)

with col_stt:
    st.components.v1.html(
        """
        <button id="stt-btn" style="width:100%; height:80px; font-weight:bold; border-radius:10px; background-color:#e8f0fe; border:1px solid #1a73e8; color:#1a73e8; cursor:pointer;">
            🎤 음성 입력 시작
        </button>
        <p id="status" style="font-size:11px; color:gray; text-align:center; margin-top:5px;">대기 중... (버튼을 누르세요)</p>
        
        <script>
            const btn = document.getElementById('stt-btn');
            const status = document.getElementById('status');
            const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
            recognition.lang = 'ko-KR';
            
            let isRecognizing = false;

            btn.onclick = () => { 
                if (!isRecognizing) {
                    recognition.start(); 
                }
            };

            recognition.onstart = () => {
                isRecognizing = true;
                status.innerText = "듣는 중... (끝내려면 스페이스바를 누르세요!)"; 
                btn.style.backgroundColor = "#ff4b4b"; 
                btn.style.color = "white"; 
            };

            recognition.onresult = (e) => {
                alert("인식 내용: " + e.results[0][0].transcript + "\\n\\n복사해서 의견란에 붙여넣으세요!");
            };

            recognition.onend = () => {
                isRecognizing = false;
                status.innerText = "대기 중... (버튼을 누르세요)"; 
                btn.style.backgroundColor = "#e8f0fe"; 
                btn.style.color = "#1a73e8";
            };

            // 💡 킬스위치(Kill-Switch): 스페이스바를 누르면 즉시 강제 종료!
            document.addEventListener('keydown', (event) => {
                if (event.code === 'Space' && isRecognizing) {
                    event.preventDefault(); // 스페이스바 누를 때 화면 밑으로 내려가는 것 방지
                    recognition.stop();
                    status.innerText = "스페이스바로 마이크 꺼짐!";
                }
            });
        </script>
        """, height=120
    )

if st.button("의견 제출", use_container_width=True, type="primary"):
    if user_input.strip():
        conn = get_connection()
        with conn.cursor() as c:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO debate (room_name, timestamp, student_name, content, sentiment) VALUES (%s, %s, %s, %s, %s)",
                      (room_name, now, student_name, user_input, sentiment))
        conn.commit()
        st.session_state['reset_key'] += 1
        st.rerun()

st.divider()

# ==========================================
# 🚀 [6] 실시간 업데이트 영역 (st.fragment의 마법!)
# ==========================================
# 💡 이 영역만 3초마다 부드럽게 새로고침 됩니다. 타이핑이 끊기지 않습니다!
@st.fragment(run_every="3s")
def live_chat_board():
    # 1. AI 15초 침묵 감지 로직 (학생 화면에서만 뒤에서 조용히 작동)
    if user_role == "학생":
        last_msg_df = get_df_from_db("SELECT id, timestamp, student_name FROM debate WHERE room_name = %s ORDER BY id DESC LIMIT 1", (room_name,))
        if not last_msg_df.empty:
            last_time = datetime.strptime(last_msg_df.iloc[0]['timestamp'], "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - last_time).total_seconds() > 15 and "AI" not in last_msg_df.iloc[0]['student_name']:
                try:
                    # 자리 찜하기
                    conn = get_connection()
                    with conn.cursor() as c:
                        c.execute("INSERT INTO debate (room_name, timestamp, student_name, content, sentiment) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                                  (room_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "🤖 AI 조력자", "토론 질문 생성 중...", "❓ 질문"))
                        inserted_id = c.fetchone()[0]
                    conn.commit()
                    
                    # 제미나이 호출
                    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                    context = "\n".join(get_df_from_db("SELECT content FROM debate WHERE room_name = %s ORDER BY id DESC LIMIT 3", (room_name,))['content'].tolist())
                    res = genai.GenerativeModel('gemini-2.5-flash').generate_content(f"'{current_topic}' 주제로 15초 침묵 중입니다. 토론을 유도할 짧은 질문 1개를 던지세요:\n{context}")
                    
                    # 진짜 질문으로 덮어쓰기
                    with conn.cursor() as c:
                        c.execute("UPDATE debate SET content = %s WHERE id = %s", (res.text.strip(), inserted_id))
                    conn.commit()
                    st.rerun() # Fragment 내부에서만 부드럽게 새로고침 됨
                except: pass

    # 2. 통계 및 대화 내역 불러오기
    df = get_df_from_db("SELECT * FROM debate WHERE room_name = %s ORDER BY id DESC", (room_name,))
    
    col_stat, col_chat = st.columns([1, 2])
    with col_stat:
        st.subheader("📊 의견 통계")
        if not df.empty:
            import plotly.express as px
            st.plotly_chart(px.pie(df, names="sentiment", hole=0.4, height=300), use_container_width=True)
        else:
            st.write("데이터 수집 중...")
            
    with col_chat:
        st.subheader("💬 실시간 토론 현황")
        if not df.empty:
            # 스크롤 박스 형태로 깔끔하게 표시
            chat_html = "<div style='height:300px; overflow-y:auto; padding:10px; border:1px solid #ddd; border-radius:5px;'>"
            for _, row in df.iterrows():
                bg_color = "#f0f2f6" if "AI" in row['student_name'] else ("#ffebee" if "교사" in row['student_name'] else "#e8f0fe")
                icon = "🤖" if "AI" in row['student_name'] else ("👨‍🏫" if "교사" in row['student_name'] else "👤")
                chat_html += f"""
                <div style='background-color:{bg_color}; padding:10px; border-radius:10px; margin-bottom:10px;'>
                    <div style='font-size:0.8em; color:gray; margin-bottom:5px;'>{icon} <b>{row['student_name']}</b> ({row['sentiment']}) - {row['timestamp'][11:]}</div>
                    <div style='font-size:1em;'>{row['content']}</div>
                </div>
                """
            chat_html += "</div>"
            st.components.v1.html(chat_html, height=320)
        else:
            st.info("아직 대화가 없습니다. 첫 의견을 남겨주세요!")

# 화면에 실시간 영역 실행
live_chat_board()

# ==========================================
# [7] 교사 전용 대시보드 (입력 폼이므로 깜빡임 영향 안 받음!)
# ==========================================
if user_role == "교사" and teacher_auth:
    st.divider()
    st.header("👨‍🏫 교사 관리 대시보드")
    df_all = get_df_from_db("SELECT * FROM debate WHERE room_name = %s", (room_name,))
    
    col3, col4 = st.columns([1, 1])
    
    with col3:
        st.subheader("📥 활동 데이터 다운로드")
        if not df_all.empty:
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer: df_all.to_excel(writer, index=False)
            st.download_button("전체 활동 로그 다운로드 (Excel)", data=buffer.getvalue(), file_name=f"{room_name}_log.xlsx")

    with col4:
        st.subheader("🤖 AI 세특 초안 생성")
        student_list = df_all[~df_all['student_name'].isin(['교사', '익명', '🤖 AI 조력자'])]['student_name'].unique() if not df_all.empty else []
        
        if len(student_list) > 0:
            selected_student = st.selectbox("분석할 학생을 선택하세요", student_list)
            
            if st.button(f"'{selected_student}' 학생 세특 생성 🪄"):
                with st.spinner("Gemini 2.5 AI 분석 중..."):
                    try:
                        student_data = df_all[df_all['student_name'] == selected_student]
                        debate_history = "\n".join([f"- [{row['sentiment']}] {row['content']}" for _, row in student_data.iterrows()])
                        
                        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                        prompt = f"정보 교사로서 '{current_topic}' 토론에 참여한 '{selected_student}' 학생의 세특 300자:\n{debate_history}"
                        response = genai.GenerativeModel('gemini-2.5-flash').generate_content(prompt)
                        
                        st.session_state['ai_result_text'] = response.text
                        conn = get_connection()
                        with conn.cursor() as c:
                            c.execute("INSERT INTO records (room_name, timestamp, student_name, content) VALUES (%s, %s, %s, %s)",
                                      (room_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), selected_student, response.text))
                        conn.commit()
                        st.rerun()
                    except Exception as e: st.error(f"오류: {e}")
            
            if st.session_state['ai_result_text']:
                st.success("보관함에 자동 저장되었습니다.")
                st.text_area("AI 생성 결과 (수정 후 복사하여 사용하세요)", value=st.session_state['ai_result_text'], height=200)
        else:
            st.info("실명 참여 학생이 없습니다.")

    st.divider()
    st.subheader("📂 저장된 세특 기록 보관함")
    records_df = get_df_from_db("SELECT timestamp, student_name, content FROM records WHERE room_name = %s ORDER BY id DESC", (room_name,))
    if not records_df.empty:
        st.dataframe(records_df, use_container_width=True)
        buffer_records = io.BytesIO()
        with pd.ExcelWriter(buffer_records, engine='openpyxl') as writer: records_df.to_excel(writer, index=False)
        st.download_button("📥 저장된 세특 전체 다운로드 (Excel)", data=buffer_records.getvalue(), file_name=f"{room_name}_세특기록.xlsx")
