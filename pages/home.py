import streamlit as st


def render_home_page():
    st.title("🏠 말자취(Talk-Trace) AI 홈")
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
    st.stop()
