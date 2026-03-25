import streamlit as st
import pandas as pd
import io
from datetime import datetime
import psycopg2
import psycopg2.extras
import google.generativeai as genai
from streamlit_autorefresh import st_autorefresh

# ==========================================
# [1] 데이터베이스 연결 및 초기화 설정
# ==========================================
@st.cache_resource(ttl=600)
def get_connection():
    db_url = st.secrets["SUPABASE_URL"]
    return psycopg2.connect(db_url)

def init_db():
    try:
        conn = get_connection()
        with conn.cursor() as c:
            # 토론 기록 테이블
            c.execute('''CREATE TABLE IF NOT EXISTS debate 
                         (id SERIAL PRIMARY KEY, room_name TEXT, timestamp TEXT, student_name TEXT, content TEXT, sentiment TEXT)''')
            # 세특(연구 기록) 보관 테이블
            c.execute('''CREATE TABLE IF NOT EXISTS records 
                         (id SERIAL PRIMARY KEY, room_name TEXT, timestamp TEXT, student_name TEXT, content TEXT)''')
            # 방 주제 설정 테이블
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
    except Exception as e:
        return pd.DataFrame()

# ==========================================
# [2] 앱 기본 설정 및 세션 초기화
# ==========================================
st.set_page_config(page_title="Talk-Trace AI", layout="wide")

# 입력창 초기화용 키
if 'reset_key' not in st.session_state: 
    st.session_state['reset_key'] = 0

# 세특 생성 결과 화면 유지용 세션
if 'ai_result_text' not in st.session_state: 
    st.session_state['ai_result_text'] = ""

# ==========================================
# [3] 사이드바 (권한 및 새로고침 제어 스위치)
# ==========================================
with st.sidebar:
    st.header("👤 접속 권한")
    user_role = st.radio("모드 선택", ["학생", "교사"])
    
    # --- [핵심] 모드별 새로고침 제어 로직 ---
    if user_role == "학생":
        # 학생은 무조건 7초마다 실시간 동기화 (친구들 글 확인)
        st_autorefresh(interval=7000, key="student_refresh")
        st.caption("🔄 학생 모드: 7초 실시간 동기화 켜짐")
    else:
        # 교사는 스위치로 동기화 여부 선택 (세특 작성 중 끊김 방지)
        st.divider()
        st.markdown("**👀 교사 전용 제어**")
        live_monitor = st.toggle("🔄 실시간 모니터링 켜기", value=True)
        
        if live_monitor:
            st_autorefresh(interval=7000, key="teacher_refresh")
            st.caption("✅ 켜짐: 학생들 대화를 실시간으로 봅니다.")
            st.warning("🚨 주의: AI 세특을 생성하기 전에는 반드시 이 스위치를 꺼주세요!")
        else:
            st.caption("⏸️ 꺼짐: 화면이 갱신되지 않아 안전하게 세특을 작성할 수 있습니다.")
    st.divider()

    # --- 방 접속 로직 ---
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

# ==========================================
# [4] 방 주제 설정 및 🤖 AI 중복 생성 방지 로직 (DB Lock)
# ==========================================
topic_df = get_df_from_db("SELECT title, mode FROM topic WHERE room_name = %s", (room_name,))
current_topic = topic_df.iloc[0]['title'] if not topic_df.empty else "자유 주제로 대화해 봅시다."
current_mode = topic_df.iloc[0]['mode'] if not topic_df.empty else "⚔️ 찬반 토론"

# 학생 모드일 때만 15초 침묵 검사 실행 (교사는 개입 안 함)
if user_role == "학생":
    last_msg_df = get_df_from_db("SELECT id, timestamp, student_name, content FROM debate WHERE room_name = %s ORDER BY id DESC LIMIT 1", (room_name,))
    
    if not last_msg_df.empty:
        last_time_str = last_msg_df.iloc[0]['timestamp']
        last_speaker = last_msg_df.iloc[0]['student_name']
        last_content = last_msg_df.iloc[0]['content']
        
        last_time = datetime.strptime(last_time_str, "%Y-%m-%d %H:%M:%S")
        time_diff = (datetime.now() - last_time).total_seconds()
        
        # 💡 [핵심] 15초가 지났고, 마지막 발언자가 AI가 아닐 때
        if time_diff > 15 and "AI" not in last_speaker:
            try:
                # 1단계: 빈 메시지를 DB에 먼저 꽂아 넣어서 '다른 창'들이 인식하게 만듭니다. (자리 찜하기)
                placeholder_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                conn = get_connection()
                with conn.cursor() as c:
                    c.execute("INSERT INTO debate (room_name, timestamp, student_name, content, sentiment) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                              (room_name, placeholder_time, "🤖 AI 조력자", "토론의 열기를 띄울 질문을 고민 중입니다... (잠시만 기다려주세요)", "❓ 질문"))
                    inserted_id = c.fetchone()[0]
                conn.commit()
                
                # 2단계: 그제야 제미나이에게 천천히 질문을 만들어 달라고 요청합니다.
                genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                model = genai.GenerativeModel('gemini-2.5-flash')
                
                recent_msgs = get_df_from_db("SELECT content FROM debate WHERE room_name = %s ORDER BY id DESC LIMIT 3", (room_name,))
                context = "\n".join(recent_msgs['content'].tolist())
                
                prompt = f"""
                당신은 고등학교 정보 토론 동아리의 AI 조력자입니다. 주제: '{current_topic}'
                학생들이 15초 이상 침묵하고 있습니다. 아래 토론 내용을 읽고 호기심을 자극하는 예리한 질문을 딱 1개만 던져주세요.
                [최근 토론 내용]
                {context}
                """
                response = model.generate_content(prompt)
                ai_question = response.text.strip()
                
                # 3단계: 제미나이가 답변을 주면, 아까 만들어둔 빈 메시지(자리)를 실제 질문으로 '수정(UPDATE)' 합니다.
                with conn.cursor() as c:
                    c.execute("UPDATE debate SET content = %s WHERE id = %s", (ai_question, inserted_id))
                conn.commit()
                
                # 화면 새로고침
                st.rerun()
                
            except Exception as e:
                pass # 에러 발생 시 토론 흐름을 끊지 않고 패스

# ==========================================
# [5] 메인 화면 (학생 토론 영역 + 음성인식 복구)
# ==========================================
st.title(f"🎙️ Talk-Trace AI [{room_name}]")
st.info(f"**현재 주제:** {current_topic} ({current_mode})")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("🗣️ 내 의견 작성")
    text_key = f"input_{st.session_state['reset_key']}"
    user_input = st.text_area("의견을 직접 타이핑하거나 아래 음성 인식을 사용하세요", key=text_key, height=100)
    
    # 🎙️ HTML/JS 기반 음성인식(STT) 기능 원상 복구
    st.components.v1.html(
        """
        <button id="stt-btn" style="width:100%; padding:10px; border-radius:5px; background-color:#f0f2f6; border:1px solid #ccc; cursor:pointer;">
            🎤 음성 인식 시작 (말씀하세요)
        </button>
        <p id="status" style="font-size:12px; color:gray; margin-top:5px;">대기 중...</p>
        <script>
            const btn = document.getElementById('stt-btn');
            const status = document.getElementById('status');
            const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
            recognition.lang = 'ko-KR';
            
            btn.onclick = () => {
                recognition.start();
                status.innerText = "듣고 있어요... (말씀이 끝나면 자동으로 알림창이 뜹니다)";
                btn.style.backgroundColor = "#ff4b4b";
                btn.style.color = "white";
            };
            recognition.onresult = (event) => {
                const text = event.results[0][0].transcript;
                alert("인식된 내용: " + text + "\\n\\n복사해서 위쪽 의견란에 붙여넣어 주세요!");
                status.innerText = "인식 완료!";
                btn.style.backgroundColor = "#f0f2f6";
                btn.style.color = "black";
            };
        </script>
        """,
        height=90,
    )
    
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

# ==========================================
# [6] 전체 의견 보기 (수동 새로고침 버튼 포함)
# ==========================================
col_title, col_btn = st.columns([4, 1])
with col_title:
    st.subheader("💬 전체 의견 보기")
with col_btn:
    if st.button("🔄 수동 새로고침", use_container_width=True):
        st.rerun()

if not df.empty:
    for _, row in df.sort_values(by="id", ascending=False).iterrows():
        # 교사와 AI의 아이콘을 구분하여 표시
        with st.chat_message("user" if "AI" not in row['student_name'] and "교사" not in row['student_name'] else "assistant"):
            st.write(f"**{row['student_name']}** ({row['sentiment']}) - {row['timestamp']}")
            st.info(row['content'])

# ==========================================
# [7] 교사 전용 대시보드 (세특 작성 및 데이터 다운로드)
# ==========================================
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
        # AI, 교사, 익명 사용자는 세특 목록에서 제외
        student_list = df[~df['student_name'].isin(['교사', '익명', '🤖 AI 조력자'])]['student_name'].unique()
        
        if len(student_list) > 0:
            selected_student = st.selectbox("분석할 학생을 선택하세요", student_list)
            
            if st.button(f"'{selected_student}' 학생 세특 생성 🪄"):
                # 교사가 모니터링 스위치를 켜두고 눌렀을 경우를 대비한 경고
                if live_monitor:
                    st.error("🚨 화면 왼쪽 사이드바에서 '실시간 모니터링' 스위치를 먼저 꺼주세요! 작성 중 내용이 날아갈 수 있습니다.")
                else:
                    with st.spinner("Gemini 2.5 AI가 학생의 활동을 분석하여 세특을 작성 중입니다..."):
                        try:
                            # 1. 해당 학생의 모든 발언 기록 가져오기
                            student_data = df[df['student_name'] == selected_student]
                            debate_history = "\n".join([f"- [{row['sentiment']}] {row['content']}" for _, row in student_data.iterrows()])
                            
                            # 2. 제미나이 호출
                            genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                            model = genai.GenerativeModel('gemini-2.5-flash')
                            
                            prompt = f"""
                            당신은 고등학교 정보 교사입니다. 다음은 '{current_topic}'을(를) 주제로 한 토론에서 '{selected_student}' 학생이 발언한 내용입니다.
                            이 내용을 바탕으로 학교생활기록부 교과세부능력 및 특기사항(세특)에 들어갈 초안을 300자 내외로 작성해주세요.
                            논리적 사고력, 문제 해결 능력, 참여도를 긍정적이고 전문적인 교육용 어휘로 평가해주세요.
                            말의 끝은 명사형으로 끝내줘.

                            [학생 발언 기록]
                            {debate_history}
                            """
                            response = model.generate_content(prompt)
                            
                            # 3. 세션 상태에 저장 (화면 유지용)
                            st.session_state['ai_result_text'] = response.text
                            
                            # 4. DB records 테이블에 저장 (방 이름, 시간, 이름, 내용 순서 정확히 일치)
                            conn = get_connection()
                            with conn.cursor() as c:
                                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                c.execute("INSERT INTO records (room_name, timestamp, student_name, content) VALUES (%s, %s, %s, %s)",
                                          (room_name, now, selected_student, response.text))
                            conn.commit()
                            
                            # 아래 보관함 표에 즉시 뜨도록 새로고침
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"AI 생성 중 오류 발생: {e}")
            
            # 세션에 저장된 결과가 있으면 항상 텍스트 박스로 보여줌
            if st.session_state['ai_result_text']:
                st.success(f"✅ AI 세특 생성이 완료되었습니다. 아래 보관함에도 자동 저장되었습니다.")
                st.text_area("AI 생성 결과 (수정 후 복사하여 사용하세요)", value=st.session_state['ai_result_text'], height=250)
                
        else:
            st.info("아직 실명으로 의견을 제출한 학생이 없습니다.")

    # --- [세특 보관함] ---
    st.divider()
    st.subheader("📂 저장된 세특 기록 보관함")
    
    # DB에서 records 테이블 꺼내오기
    records_df = get_df_from_db("SELECT timestamp, student_name, content FROM records WHERE room_name = %s ORDER BY id DESC", (room_name,))
    
    if not records_df.empty:
        st.dataframe(records_df, use_container_width=True)
        
        # 엑셀 다운로드
        buffer_records = io.BytesIO()
        with pd.ExcelWriter(buffer_records, engine='openpyxl') as writer:
            records_df.to_excel(writer, index=False)
        st.download_button("📥 저장된 세특 전체 다운로드 (Excel)", data=buffer_records.getvalue(), file_name=f"{room_name}_세특기록.xlsx")
    else:
        st.info("아직 저장된 세특 기록이 없습니다. 위에서 AI 세특을 생성하면 여기에 차곡차곡 쌓입니다!")
