import streamlit as st

from db import (
    fetch_room_names,
    topic_entry_code_column_available,
    topic_is_hidden_available,
    fetch_all_rooms_hidden_status,
    toggle_room_visibility,
    upsert_topic_room,
)
from validators import (
    validate_entry_code,
    validate_opinion_content,
    validate_room_name,
)
from config import MAX_ROOM_NAME_LEN, MAX_TOPIC_LEN, MAX_ENTRY_CODE_LEN, DIGITAL_ETHICS_TOPICS

_VIEW_KEY = "_room_mgmt_view"
_ROOMS_PER_ROW = 4


def _render_visibility_section(supabase):
    if not topic_is_hidden_available():
        st.info("이 기능을 사용하려면 topic.is_hidden 컬럼이 필요합니다.")
        return
    all_rooms_for_manage = fetch_room_names(supabase, include_hidden=True)
    if not all_rooms_for_manage:
        st.info("아직 개설된 방이 없습니다. '✨ 새 방 만들기'에서 첫 번째 방을 만들어보세요.")
        return

    st.caption("✅ 체크 = 학생에게 보임 / ☐ 해제 = 숨김 (변경 즉시 자동 저장)")
    _hidden_status = fetch_all_rooms_hidden_status(supabase)
    _hidden_changed = False
    _cols = st.columns(_ROOMS_PER_ROW)
    for i, _r in enumerate(all_rooms_for_manage):
        with _cols[i % _ROOMS_PER_ROW]:
            _cur_hidden = _hidden_status.get(_r, False)
            _checked = st.checkbox(_r, value=not _cur_hidden, key=f"vis_{_r}")
            _want_hidden = not _checked
            if _want_hidden != _cur_hidden:
                toggle_room_visibility(supabase, _r, _want_hidden)
                _hidden_changed = True
    if _hidden_changed:
        st.rerun()


def _render_create_section(supabase, teacher_id_for_scope):
    if '_bulk_create_msg' in st.session_state:
        st.success(st.session_state['_bulk_create_msg'])
        st.session_state['_bulk_create_msg_ttl'] = st.session_state.get('_bulk_create_msg_ttl', 0) + 1
        if st.session_state['_bulk_create_msg_ttl'] >= 8:
            del st.session_state['_bulk_create_msg']
            del st.session_state['_bulk_create_msg_ttl']
    if '_single_create_msg' in st.session_state:
        st.success(st.session_state.pop('_single_create_msg'))

    _bulk_mode = st.checkbox("📋 여러 반 한번에 만들기")
    col_name, col_pw = st.columns(2)
    with col_name:
        if _bulk_mode:
            _class_prefix = st.text_input("반 이름 공통 앞부분", value="1학년")
            _class_nums = st.text_input("반 번호/구분 (쉼표로 구분)", value="1,2,3", help="예: 1,2,3 또는 가,나,다")
        else:
            new_room = st.text_input("새로 만들 방 이름", placeholder="예: 1학년 3반")
    with col_pw:
        new_pw = st.text_input("🔒 학생 입장용 암호 (비워두면 공개방)")

    _preset_labels = ["직접 입력"] + [t["label"] for t in DIGITAL_ETHICS_TOPICS]
    col_topic, col_mode = st.columns(2)
    with col_topic:
        _topic_choice = st.selectbox("📚 정보윤리 추천 주제", _preset_labels, index=0)

    _preset = None if _topic_choice == "직접 입력" else next(t for t in DIGITAL_ETHICS_TOPICS if t["label"] == _topic_choice)
    _preset_mode_idx = 0 if (_preset is None or _preset["mode"] == "⚔️ 찬반 토론") else 1
    with col_mode:
        new_mode = st.radio("진행 방식", ["⚔️ 찬반 토론", "💡 자유 토의"], index=_preset_mode_idx, horizontal=True)

    if _preset is None:
        new_title = st.text_input("주제 직접 입력", placeholder="예: 인공지능 윤리")
    else:
        _edit_title_key = f"edit_preset_title_{_topic_choice}"
        _editing = st.session_state.get(f"editing_{_topic_choice}", False)
        if _editing:
            new_title = st.text_input("주제 수정", value=_preset["title"], key=_edit_title_key)
            if st.button("✅ 수정 완료", key=f"done_{_topic_choice}"):
                st.session_state[f"editing_{_topic_choice}"] = False
                st.rerun()
        else:
            new_title = _preset["title"]
            st.caption(f"📌 {new_title}")
            if _preset.get("pro") and _preset.get("con"):
                with st.expander("💡 찬성/반대 핵심 논점 보기", expanded=False):
                    st.markdown(f"**🔵 찬성:** {_preset['pro']}")
                    st.markdown(f"**🔴 반대:** {_preset['con']}")
            if st.button("✏️ 주제 수정", key=f"edit_{_topic_choice}"):
                st.session_state[f"editing_{_topic_choice}"] = True
                st.rerun()

    st.caption("⚠️ 방 이름은 개설 후 변경할 수 없습니다. 신중하게 입력해 주세요.")
    if st.button("새 방 개설하기", type="primary", use_container_width=True):
        entry_ok, safe_new_pw, _, entry_error_message = validate_entry_code(new_pw, max_len=MAX_ENTRY_CODE_LEN)
        title_ok, safe_new_title, _, title_error_message = validate_opinion_content(new_title, max_len=MAX_TOPIC_LEN)
        can_store_room_pw = topic_entry_code_column_available()
        if not title_ok:
            st.error(f"❌ {title_error_message}")
        elif not entry_ok:
            st.error(f"❌ {entry_error_message}")
        elif safe_new_pw and not can_store_room_pw:
            st.error("현재 DB 구조에서는 방 비밀번호 저장을 지원하지 않습니다.")
        elif _bulk_mode:
            _nums = [n.strip() for n in _class_nums.split(",") if n.strip()]
            _existing_rooms = set(fetch_room_names(supabase))
            _created, _failed, _skipped = [], [], []
            for _num in _nums:
                _room = f"{_class_prefix} {_num}반"
                room_ok, safe_r, _, _ = validate_room_name(_room, max_len=MAX_ROOM_NAME_LEN)
                if not room_ok:
                    _failed.append(_room)
                    continue
                if safe_r in _existing_rooms:
                    _skipped.append(safe_r)
                    continue
                res = upsert_topic_room(
                    supabase=supabase, room_name=safe_r, title=safe_new_title,
                    mode=new_mode, entry_code=safe_new_pw, created_by=teacher_id_for_scope,
                )
                (_created if res is not None else _failed).append(safe_r)
            if _skipped:
                st.warning(f"이미 생성된 방 (건너뜀): {', '.join(_skipped)}")
            if _failed:
                st.error(f"❌ 개설 실패: {', '.join(_failed)}")
            if _created:
                st.session_state['current_room'] = _created[-1]
                st.session_state['_bulk_create_msg'] = f"✅ {len(_created)}개 방 생성 완료: {', '.join(_created)}"
                st.rerun()
        else:
            room_ok, safe_new_room, _, room_error_message = validate_room_name(new_room, max_len=MAX_ROOM_NAME_LEN)
            if not room_ok:
                st.error(f"❌ {room_error_message}")
            elif safe_new_room and safe_new_title:
                res = upsert_topic_room(
                    supabase=supabase, room_name=safe_new_room, title=safe_new_title,
                    mode=new_mode, entry_code=safe_new_pw, created_by=teacher_id_for_scope,
                )
                if res is not None:
                    st.session_state['current_room'] = safe_new_room
                    st.session_state['_single_create_msg'] = f"✅ '{safe_new_room}' 방 생성이 완료되었습니다!"
                    st.toast(f"'{safe_new_room}' 방이 개설되었습니다!", icon="🎉")
                    st.rerun()


def render_room_management_page(supabase):
    teacher_auth = st.session_state.get('teacher_auth', False)
    if not teacher_auth:
        st.session_state['page'] = "lobby"
        st.toast("교사 로그인이 필요합니다.", icon="ℹ️")
        st.rerun()

    teacher_id_for_scope = st.session_state.get('teacher_id', '')

    col_title, col_btn = st.columns([6, 2])
    with col_title:
        st.title("🏠 방 관리")
    with col_btn:
        if st.button("🚪 대기실로", use_container_width=True):
            st.session_state['page'] = "lobby"
            st.session_state['joined'] = False
            st.rerun()

    view = st.session_state.get(_VIEW_KEY, "create")
    col_v1, col_v2 = st.columns(2)
    with col_v1:
        if st.button("✨ 새 방 만들기", use_container_width=True, type="primary" if view == "create" else "secondary"):
            st.session_state[_VIEW_KEY] = "create"
            st.rerun()
    with col_v2:
        if st.button("👁️ 방 공개/숨김 관리", use_container_width=True, type="primary" if view == "visibility" else "secondary"):
            st.session_state[_VIEW_KEY] = "visibility"
            st.rerun()

    with st.container(border=True):
        if view == "visibility":
            _render_visibility_section(supabase)
        else:
            _render_create_section(supabase, teacher_id_for_scope)
    st.stop()
