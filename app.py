import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
import psycopg2
import psycopg2.extras
import google.generativeai as genai

# 💡 [핵심 패치 1] 무조건 한국 시간(KST)을 반환하는 마법의 함수!
def get_kst_now():
    return datetime.utcnow() + timedelta(hours=9)

def insert_ai_placeholder_atomic(room_name):
    conn = None
    try:
        conn = psycopg2.connect(st.secrets["SUPABASE_URL"])
        with conn.cursor() as c:
            c.execute("SELECT pg_advisory_xact_lock(9999)")
            
            # KST 기준으로 10초 전 시간 계산
            ten_secs_ago = (get_kst_now() - timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("SELECT 1 FROM debate WHERE room_name = %s AND student_name LIKE '%%AI%%' AND timestamp > %s", (room_name, ten_secs_ago))
            
            if c.fetchone():
                return None 
                
            now_str = get_kst_now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO debate (room_name, timestamp, student_name, content, sentiment) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                      (room_name, now_str, "🤖 AI 조력자", "토론 질문 생성 중...", "❓ 질문"))
            inserted_id = c.fetchone()[0]
            conn.commit() 
            return inserted_id
    except Exception:
        return None
    finally:
        if conn is not None: conn.close()

def get_df_from_db(query, params=()):
    conn = None
    try:
        conn = psycopg2.connect(st.secrets["SUPABASE_URL"])
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as c:
            c.execute(query, params)
            data = c.fetchall()
            return pd.DataFrame(data, columns=[desc[0] for desc in c.description] if c.description else [])
    except Exception:
        return pd.DataFrame()
    finally:
        if conn is not None: conn.close()

def execute_query(query, params=()):
    conn = None
    try:
        conn = psycopg2.connect(st.secrets["SUPABASE_URL"])
        with conn.cursor() as c:
            c.execute(query, params)
        conn.commit()
    finally:
        if conn is not None: conn.close()

def init_db():
    conn = None
    try:
        conn = psycopg2.connect(st.secrets["SUPABASE_URL"])
        with conn.cursor() as c:
            c.execute('CREATE TABLE IF NOT EXISTS debate (id SERIAL PRIMARY KEY, room_name TEXT, timestamp TEXT, student_name TEXT, content TEXT, sentiment TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS records (id SERIAL PRIMARY KEY, room_name TEXT, timestamp TEXT, student_name TEXT, content TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS topic (room_name TEXT PRIMARY KEY, title TEXT, mode TEXT, entry_code TEXT DEFAULT \'\')')
        conn.commit()
    except Exception as e:
        st.error(f"🚨 DB 연결 실패: {e}")
    finally:
        if conn is not None: conn.close()

init_db()

st.set_page_config(page_title="Talk-Trace AI", layout="wide")

if 'reset_key' not in st.session_state: st.session_state['reset_key'] = 0
if 'ai_result_text' not in st.session_state: st.session_state['ai_result_text'] = ""
if 'joined' not in st.session_state: st.session_state['joined'] = False

# 💡 [핵심 패치 2] 모드가 바뀔 때마다 무조건 대기실로 쫓아내는 초기화 함수
def reset_joined_state():
    st.session_state['joined'] = False

with st.sidebar:
    st.header("👤 접속 권한")
    # 라디오 버튼을 클릭할 때마다 reset_joined_state 함수가 실행됩니다! (유령 방 납치 완벽 차단)
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
            room_opt = st.radio("방 선택", ["기존 방 선택", "새 방 만들기"])
            
            if room_opt == "기존 방 선택" and existing_rooms:
                room_name = st.selectbox("토론방 목록", existing_rooms)
            else:
                new_room = st.text_input("새로 만들 방 이름 입력")
                new_pw = st.text_input("🔒 학생 입장용 암호 (비워두면 공개방)")
                if st.button("새 방 개설하기") and new_room:
                    execute_query("INSERT INTO topic (room_name, title, mode, entry_code) VALUES (%s, %s, %s, %s) ON CONFLICT (room_name) DO NOTHING", 
                                  (new_room, "자유 주제로 대화해 봅시다.", "⚔️ 찬반 토론", new_pw))
                    st.success(f"'{new_room}' 방이 개설되었습니다! 위쪽에서 '기존 방 선택'을 눌러 입장하세요.")
                room_name = new_room
    else:
        if existing_rooms:
            room_name = st.selectbox("🏠 접속할 방 선택", existing_rooms)
        else:
            st.warning("선생님이 아직 열어둔 토론방이 없습니다.")
            room_name = ""
            
    student_name = st.text_input("내 이름", value="익명" if user_role == "학생" else "교사")
    
    if st.session_state['joined']:
        st.divider()
        if st.button("🚪 방 나가기 (대기실로)"):
            st.session_state['joined'] = False
            st.rerun()

if not st.session_state['joined']:
    st.title("🚪 Talk-Trace AI 대기실")
    
    if user_role == "교사" and not teacher_auth:
        st.warning("🚨 교사 인증 암호를 입력해야 입장할 수 있습니다.")
    elif not room_name.strip():
        st.error("🚨 접속할 방을 먼저 선택해 주세요.")
    else:
        if user_role == "학생":
            topic_info = get_df_from_db("SELECT entry_code FROM topic WHERE room_name = %s", (room_name,))
            real_pw = topic_info.iloc[0]['entry_code'] if not topic_info.empty and topic_info.iloc[0]['entry_code'] else ""
            
            if real_pw:
                student_pw = st.text_input("🔒 방 입장 암호 (선생님께 확인하세요)", type="password")
                if student_pw == real_pw:
                    if st.button(f"🚀 '{room_name}' 입장하기", type="primary", use_container_width=True):
                        st.session_state['joined'] = True
                        st.rerun()
                elif student_pw:
                    st.error("❌ 암호가 틀렸습니다. 다시 확인해 주세요!")
            else:
                if st.button(f"🚀 '{room_name}' 입장하기", type="primary", use_container_width=True):
                    st.session_state['joined'] = True
                    st.rerun()
        else:
            if st.button(f"🚀 '{room_name}' 관리자 권한으로 입장", type="primary", use_container_width=True):
                st.session_state['joined'] = True
                st.rerun()
    st.stop()

topic_df = get_df_from_db("SELECT title, mode FROM topic WHERE room_name = %s", (room_name,))
current_topic = topic_df.iloc[0]['title'] if not topic_df.empty else "자유 주제로 대화해 봅시다."
current_mode = topic_df.iloc[0]['mode'] if not topic_df.empty else "⚔️ 찬반 토론"

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
        <button id="stt-btn" style="width:100%; height:80px; font-weight:bold; border-radius:10px; background-color:#e8f0fe; border:1px solid #1a73e8; color:#1a73e8; cursor:pointer;">
            🎤 음성 입력 시작
        </button>
        <p id="status" style="font-size:11px; color:gray; text-align:center; margin-top:5px;">대기 중...</p>
        <script>
            const btn = document.getElementById('stt-btn');
            const status = document.getElementById('status');
            const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
            recognition.lang = 'ko-KR';
            let isRecognizing = false;

            btn.onclick = () => { 
                if (!isRecognizing) recognition.start(); 
                else recognition.stop();
            };

            recognition.onstart = () => {
                isRecognizing = true;
                status.innerText = "듣는 중... (종료: 버튼/스페이스바)"; 
                btn.style.backgroundColor = "#ff4b4b"; 
                btn.style.color = "white"; 
                btn.innerHTML = "🛑 음성 입력 중지";
            };

            recognition.onresult = (event) => {
                const text = event.results[0][0].transcript;
                const parentDoc = window.parent.document;
                const textArea = parentDoc.querySelector('textarea[aria-label="의견을 입력하세요"]');
                
                if (textArea) {
                    const currentText = textArea.value;
                    const newText = currentText ? currentText + " " + text : text;
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
                    nativeInputValueSetter.call(textArea, newText);
                    textArea.dispatchEvent(new Event('input', { bubbles: true }));
                    status.innerText = "입력 완료!";
                } else {
                    alert("인식 내용: " + text);
                }
            };

            recognition.onend = () => {
                isRecognizing = false;
                setTimeout(() => {
                    status.innerText = "대기 중..."; 
                    btn.style.backgroundColor = "#e8f0fe"; 
                    btn.style.color = "#1a73e8";
                    btn.innerHTML = "🎤 음성 입력 시작";
                }, 1500); 
            };

            document.addEventListener('keydown', (event) => {
                if (event.code === 'Space' && isRecognizing) {
                    event.preventDefault(); 
                    recognition.stop();
                }
            });
        </script>
        """, height=120
    )

if st.button("의견 제출", use_container_width=True, type="primary"):
    if user_input.strip():
        # KST 한국 시간 적용
        now = get_kst_now().strftime("%Y-%m-%d %H:%M:%S")
        execute_query("INSERT INTO debate (room_name, timestamp, student_name, content, sentiment) VALUES (%s, %s, %s, %s, %s)",
                      (room_name, now, student_name, user_input, sentiment))
        st.session_state['reset_key'] += 1
        st.rerun()

st.divider()

@st.fragment(run_every="5s")
def live_chat_board():
    if user_role == "학생":
        last_msg_df = get_df_from_db("SELECT id, timestamp, student_name FROM debate WHERE room_name = %s ORDER BY id DESC LIMIT 1", (room_name,))
        if not last_msg_df.empty:
            last_time = datetime.strptime(last_msg_df.iloc[0]['timestamp'], "%Y-%m-%d %H:%M:%S")
            
            # 현재 시간 비교도 KST 한국 시간으로 통일!
            if (get_kst_now() - last_time).total_seconds() > 60 and "AI" not in last_msg_df.iloc[0]['student_name']:
                try:
                    inserted_id = insert_ai_placeholder_atomic(room_name)
                    if inserted_id:
                        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
                        context = "\n".join(get_df_from_db("SELECT content FROM debate WHERE room_name = %s ORDER BY id DESC LIMIT 3", (room_name,))['content'].tolist())
                        prompt = f"""
                        당신은 고등학교 토론 조력자입니다. '{current_topic}' 주제로 1분 침묵 중입니다. 
                        최근 대화: {context}
                        [엄격한 규칙] 학생들의 호기심을 자극하는 짧은 질문을 딱 1문장만 작성하세요. 줄바꿈이나 번호 매기기는 절대 금지입니다.
                        """
                        res = genai.GenerativeModel('gemini-2.5-flash').generate_content(prompt)
                        ai_final_text = res.text.strip().split('\n')[0] 
                        execute_query("UPDATE debate SET content = %s WHERE id = %s", (ai_final_text, inserted_id))
                        st.rerun() 
                except: pass

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
        st.subheader("💬 실시간 전체 의견")
        if not df.empty:
            with st.container(height=400):
                for _, row in df.iterrows():
                    is_ai = "AI" in row['student_name']
                    with st.chat_message("assistant" if is_ai else "user"):
                        if user_role == "교사" and teacher_auth:
                            c_text, c_btn = st.columns([9, 1])
                            with c_text:
                                st.write(f"**{row['student_name']}** ({row['sentiment']}) - {row['timestamp'][11:]}")
                                st.info(row['content'])
                            with c_btn:
                                if st.button("❌", key=f"del_msg_{row['id']}", help="메시지 강제 삭제"):
                                    execute_query("DELETE FROM debate WHERE id = %s", (row['id'],))
                                    st.rerun() 
                        else:
                            st.write(f"**{row['student_name']}** ({row['sentiment']}) - {row['timestamp'][11:]}")
                            st.info(row['content'])
        else:
            st.info("아직 대화가 없습니다. 첫 의견을 남겨주세요!")

live_chat_board()

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
                        now = get_kst_now().strftime("%Y-%m-%d %H:%M:%S")
                        execute_query("INSERT INTO records (room_name, timestamp, student_name, content) VALUES (%s, %s, %s, %s)",
                                      (room_name, now, selected_student, response.text))
                        st.rerun()
                    except Exception as e: st.error(f"오류: {e}")
            
            if st.session_state['ai_result_text']:
                st.success("보관함에 자동 저장되었습니다.")
                st.text_area("AI 생성 결과 (수정 후 복사하여 사용하세요)", value=st.session_state['ai_result_text'], height=200)
        else:
            st.info("실명 참여 학생이 없습니다.")

    st.divider()
    st.subheader("📂 저장된 세특 기록 보관함")
    records_df = get_df_from_db("SELECT id, timestamp, student_name, content FROM records WHERE room_name = %s ORDER BY id DESC", (room_name,))
    
    if not records_df.empty:
        st.dataframe(records_df, use_container_width=True)
        col_down, col_del = st.columns([1, 1])
        with col_down:
            buffer_records = io.BytesIO()
            with pd.ExcelWriter(buffer_records, engine='openpyxl') as writer: 
                records_df.drop(columns=['id']).to_excel(writer, index=False)
            st.download_button("📥 세특 기록 다운로드 (Excel)", data=buffer_records.getvalue(), file_name=f"{room_name}_세특.xlsx")
            
        with col_del:
            del_id = st.selectbox("🗑️ 삭제할 세특의 '고유 번호(id)'를 선택하세요", records_df['id'].tolist())
            if st.button("선택한 세특 영구 삭제"):
                execute_query("DELETE FROM records WHERE id = %s", (del_id,))
                st.success("세특이 삭제되었습니다.")
                st.rerun()
    else:
        st.info("아직 저장된 세특 기록이 없습니다.")

    st.divider()
    st.subheader("🚨 위험 구역 (방 관리)")
    with st.expander("이 토론방 전체 삭제하기 (클릭 시 펼쳐짐)"):
        st.warning(f"정말 '{room_name}' 방을 삭제하시겠습니까? (복구 불가)")
        if st.button(f"네, '{room_name}' 방을 완전히 삭제합니다", type="primary"):
            execute_query("DELETE FROM topic WHERE room_name = %s", (room_name,))
            execute_query("DELETE FROM debate WHERE room_name = %s", (room_name,))
            execute_query("DELETE FROM records WHERE room_name = %s", (room_name,))
            st.success("방이 성공적으로 폭파되었습니다. 화면 상단(사이드바)에서 다른 방을 선택해 주세요.")
            st.session_state['ai_result_text'] = ""
