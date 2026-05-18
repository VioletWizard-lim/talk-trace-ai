import os

import streamlit as st


def get_secret(key: str, default: str = "") -> str:
    """환경변수(HF Spaces) → st.secrets(Streamlit Cloud) 순서로 값을 읽습니다."""
    env_val = os.environ.get(key, "").strip()
    if env_val:
        return env_val
    try:
        return str(st.secrets.get(key, default)).strip()
    except Exception:
        return default
