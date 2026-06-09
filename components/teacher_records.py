import io

import pandas as pd
import streamlit as st

from config import DASHBOARD_FETCH_LIMIT
from utils import get_kst_now


@st.fragment
def render_records_section(room_name, act_type, df_all):
    st.subheader("📥 활동 데이터 다운로드")
    if df_all.empty:
        st.info(f"아직 {act_type} 데이터가 없습니다. 학생들이 의견을 제출하면 다운로드할 수 있습니다.")
        return
    if len(df_all) >= DASHBOARD_FETCH_LIMIT:
        st.warning(f"⚠️ 의견이 {DASHBOARD_FETCH_LIMIT}개 이상입니다. 최근 {DASHBOARD_FETCH_LIMIT}개만 다운로드됩니다.")
    EXCLUDE_COLS = {'user_id', 'ip_address', 'created_at'}
    export_df = df_all.drop(columns=[c for c in EXCLUDE_COLS if c in df_all.columns])
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        export_df.to_excel(writer, index=False)
    st.download_button(
        f"{act_type} 전체 활동 로그 (Excel)",
        data=buffer.getvalue(),
        file_name=f"{room_name}_log_{get_kst_now().strftime('%Y%m%d_%H%M')}.xlsx",
    )
