import io

import pandas as pd
import streamlit as st

from utils import get_kst_now


@st.fragment
def render_records_section(room_name, act_type, df_all):
    st.subheader("📥 활동 데이터 다운로드")
    if not df_all.empty:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_all.to_excel(writer, index=False)
        st.download_button(
            f"{act_type} 전체 활동 로그 (Excel)",
            data=buffer.getvalue(),
            file_name=f"{room_name}_log_{get_kst_now().strftime('%Y%m%d_%H%M')}.xlsx",
        )
