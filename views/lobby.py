import streamlit as st
from db import (
    fetch_room_entry_code,
    find_duplicate_session,
    check_and_log_presence,
    find_number_switch_abuse,
    fetch_room_names,
    fetch_room_names_by_owner,
    topic_owner_column_available,
)
from validators import validate_student_number
from config import AUTO_JOIN_ON_REFRESH
from components.teacher_auth import render_teacher_auth

_ROLE_TAB_KEY = "user_role_radio"
_ROLE_TAB_CSS = f"""
    <style>
    div[class*="st-key-{_ROLE_TAB_KEY}"] div[role="radiogroup"] {{
        gap: 4px;
    }}
    div[class*="st-key-{_ROLE_TAB_KEY}"] label {{
        background: #f0f2f6;
        border-radius: 8px;
        padding: 10px 22px !important;
        margin: 0 !important;
        transition: background 0.15s, color 0.15s;
    }}
    div[class*="st-key-{_ROLE_TAB_KEY}"] label p {{
        color: #1a1a1a !important;
    }}
    div[class*="st-key-{_ROLE_TAB_KEY}"] label > div:first-child {{
        display: none !important;
    }}
    div[class*="st-key-{_ROLE_TAB_KEY}"] label:has(input:checked) {{
        background: #ff4b4b;
    }}
    div[class*="st-key-{_ROLE_TAB_KEY}"] label:has(input:checked) p {{
        color: white !important;
        font-weight: 700;
    }}
    </style>
"""


def _reset_joined_state():
    st.session_state['joined'] = False
    st.session_state['teacher_auth'] = False
    st.session_state['admin_auth'] = False
    st.session_state['teacher_id'] = ""
    st.session_state.pop('_admin_redirected', None)


def _enter_room(room_name: str):
    st.session_state['current_room'] = room_name
    st.session_state['ai_hint_text'] = ""
    st.session_state['ai_report_text'] = ""
    st.session_state['joined'] = True
    st.rerun()


def render_lobby_page(supabase):
    admin_auth = st.session_state.get('admin_auth', False)
    teacher_auth = st.session_state.get('teacher_auth', False)

    _header_buttons = []
    if admin_auth and teacher_auth:
        _header_buttons.append(("📝 ID 요청 수락", "admin_approval"))
    if teacher_auth:
        _header_buttons.append(("🔓 로그아웃", "__logout__"))

    if _header_buttons:
        col_title, *_header_cols = st.columns([6] + [2] * len(_header_buttons))
    else:
        col_title, _header_cols = st.container(), []
    with col_title:
        st.title("🚪 말자취 AI 대기실")
    for _col, (_label, _target) in zip(_header_cols, _header_buttons):
        with _col:
            if st.button(_label, use_container_width=True, key=f"lobby_header_{_target}"):
                if _target == "__logout__":
                    st.session_state['teacher_auth'] = False
                    st.session_state['admin_auth'] = False
                    st.session_state['teacher_id'] = ""
                    st.session_state['joined'] = False
                    st.session_state.pop('_admin_redirected', None)
                else:
                    st.session_state['page'] = _target
                st.rerun()

    if teacher_auth:
        # 로그인 상태에서는 라디오의 남은 값에 의존하지 않고 역할을 "교사"로
        # 고정한다. (관리자 화면/방 관리 화면을 거쳐 돌아왔을 때 라디오가
        # 기본값인 "학생"으로 잘못 표시되던 문제 방지)
        user_role = "교사"
        st.caption("🔒 교사로 로그인되어 있습니다. 로그아웃해야 모드를 변경할 수 있습니다.")
    else:
        st.markdown(_ROLE_TAB_CSS, unsafe_allow_html=True)
        user_role = st.radio(
            "모드 선택", ["학생", "교사"], on_change=_reset_joined_state,
            key=_ROLE_TAB_KEY, horizontal=True, label_visibility="collapsed",
        )
    st.divider()

    if user_role == "교사":
        render_teacher_auth(supabase)
        teacher_auth = st.session_state['teacher_auth']
        admin_auth = st.session_state['admin_auth']
        teacher_id_for_scope = st.session_state.get('teacher_id', '')

        if not teacher_auth:
            st.stop()

        existing_rooms = (
            fetch_room_names(supabase, include_hidden=False) if admin_auth else (
                fetch_room_names_by_owner(supabase, teacher_id_for_scope)
                if topic_owner_column_available()
                else []
            )
        )
        if not admin_auth and not topic_owner_column_available():
            st.warning("교사별 방 조회를 위해 topic.created_by_teacher_id(권장) 또는 topic.created_by 컬럼이 필요합니다.")

        if st.button("🏠 방 관리 (개설 / 공개 설정)", use_container_width=True):
            st.session_state['page'] = "room_management"
            st.rerun()

        if not existing_rooms:
            st.info("아직 개설된 방이 없습니다. '🏠 방 관리'에서 첫 번째 방을 만들어보세요.")
            st.stop()

        current = st.session_state.get('current_room', '')
        default_idx = existing_rooms.index(current) if current in existing_rooms else 0
        room_name = st.selectbox("토론/토의방 목록", existing_rooms, index=default_idx, key="teacher_room_select")

        if AUTO_JOIN_ON_REFRESH and not admin_auth:
            _enter_room(room_name)
        if st.button(f"🚀 '{room_name}' 관리자 권한으로 입장", type="primary", use_container_width=True):
            _enter_room(room_name)

    else:
        st.session_state['teacher_auth'] = False
        st.session_state['admin_auth'] = False
        st.session_state['teacher_id'] = ""
        if st.session_state.get('page') == "admin_approval":
            st.session_state['page'] = "lobby"

        try:
            all_rooms = fetch_room_names(supabase, include_hidden=False)
        except Exception:
            all_rooms = []

        if not all_rooms:
            st.warning("선생님이 아직 열어둔 방이 없습니다.")
            st.stop()

        room_name = st.selectbox("🏠 접속할 방 선택", all_rooms, key="student_room_select")
        col_number, col_pw = st.columns(2)
        with col_number:
            student_number = st.text_input(
                "학번", key="student_number_input",
                placeholder="예: 10101 (4~5자리 숫자)", max_chars=5,
            )
        with col_pw:
            student_pw = st.text_input("🔒 방 입장 암호 (공개방이면 비워두세요)", type="password")
        number_ok, _, _, number_error_message = validate_student_number(student_number)
        if st.button(f"🚀 '{room_name}' 입장하기", type="primary", use_container_width=True):
            real_pw = fetch_room_entry_code(supabase, room_name)
            if real_pw is None:
                st.error("🚨 방 암호 정보를 확인할 수 없어 입장을 차단했습니다. 잠시 후 다시 시도해 주세요.")
            elif real_pw and student_pw != real_pw:
                st.error("❌ 암호가 틀렸습니다.")
            elif not number_ok:
                st.error(f"❌ {number_error_message}")
            else:
                session_id = st.session_state.get("session_uuid", "")
                already_used = find_number_switch_abuse(supabase, room_name, session_id, student_number)
                if already_used:
                    st.error(
                        f"❌ 이 브라우저는 이미 {len(already_used)}개의 다른 학번({', '.join(already_used)})으로 "
                        "이 방에 입장한 기록이 있습니다. 학번을 여러 번 바꿔 입장할 수 없습니다."
                    )
                else:
                    is_duplicate = (
                        check_and_log_presence(supabase, room_name, student_number, session_id)
                        or find_duplicate_session(supabase, room_name, student_number, session_id)
                    )
                    if is_duplicate:
                        st.toast(
                            "⚠️ 이 학번은 다른 기기/브라우저에서 이미 접속 중인 것 같습니다. 본인이 맞는지 확인해 주세요.",
                            icon="⚠️",
                        )
                    _enter_room(room_name)
    st.stop()
