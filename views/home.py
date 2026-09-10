import streamlit as st

from db import fetch_judge_account
from config import JUDGE_ACCESS_CODE


def render_home_page(supabase):
    admin_auth = st.session_state.get('admin_auth', False)
    teacher_auth = st.session_state.get('teacher_auth', False)

    if admin_auth and teacher_auth:
        col_title, col_admin1, col_admin2 = st.columns([4, 1, 1])
        with col_title:
            st.title("🏠 말자취(Talk-Trace) AI 토론/토의방 홈")
        with col_admin1:
            if st.button("📝 ID 요청 수락", use_container_width=True):
                st.session_state['page'] = "admin_approval"
                st.rerun()
        with col_admin2:
            if st.button("🚪 말자취 AI 대기실", use_container_width=True):
                st.session_state['page'] = "lobby"
                st.rerun()
    else:
        st.title("🏠 말자취(Talk-Trace) AI 토론/토의방 홈")

    st.info(
        "## 말자취 AI: 토론·토의 발언 기록 및 사고 변화 분석 시스템\n\n"
        "**🎓 대상학년: 고등학교 1학년**"
    )

    st.markdown(
        """
        ### 사용 방법 (간단 안내)
        1. **대기실로 이동** 버튼을 눌러 시작합니다.
        2. 왼쪽 사이드바에서 **학생/교사 모드**를 선택합니다.
        3. 접속할 **토론/토의방**을 선택하고 입장합니다.
        4. 주제에 맞게 의견을 작성하고 제출하면 실시간 보드에 반영됩니다.
        ---
        - 교사 모드에서는 방 개설/관리 및 대시보드 기능을 사용할 수 있습니다.
        - 언제든 왼쪽 상단의 **🏠 홈** 버튼으로 이 화면으로 돌아올 수 있습니다.
        """
    )
    if st.button("🚀 대기실로 이동", type="primary", use_container_width=True):
        st.session_state['page'] = "lobby"
        st.rerun()

    judge_account = None if teacher_auth else fetch_judge_account(supabase)
    if judge_account and judge_account.get("is_active"):
        # 이 버튼은 클릭 한 번으로 관리자 권한(모든 방 접근)을 부여하므로,
        # JUDGE_ACCESS_CODE를 아는 사람만 입장할 수 있도록 코드 확인을 거친다.
        # 코드가 설정되어 있지 않으면(운영자 설정 누락) 안전하게 버튼 자체를 숨긴다.
        if not JUDGE_ACCESS_CODE:
            st.caption("🎓 심사위원 입장 기능이 준비 중입니다. (관리자: JUDGE_ACCESS_CODE 설정 필요)")
        else:
            with st.expander("🎓 심사위원으로 입장"):
                entered_code = st.text_input(
                    "심사위원 안내에 포함된 입장 코드를 입력하세요",
                    type="password", key="judge_access_code_input",
                )
                if st.button("입장", key="judge_access_enter_btn", use_container_width=True):
                    if entered_code.strip() != JUDGE_ACCESS_CODE:
                        st.error("입장 코드가 올바르지 않습니다.")
                    else:
                        st.session_state['teacher_auth'] = True
                        # 모든 방을 볼 수 있어야 하므로 일반 교사가 아닌 관리자 권한으로 로그인시킨다.
                        st.session_state['admin_auth'] = True
                        st.session_state['teacher_id'] = judge_account.get("teacher_id", "")
                        # 사이드바의 "모드 선택"이 기본값(학생)으로 남아있으면 위 인증 상태가
                        # 곧바로 초기화되므로, 모드도 함께 "교사"로 강제 전환해준다.
                        st.session_state['user_role_radio'] = "교사"
                        st.session_state['page'] = "lobby"
                        st.rerun()

    st.stop()
