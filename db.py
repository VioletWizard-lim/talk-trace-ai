import logging
import time

import pandas as pd
import streamlit as st
from supabase import Client, create_client


logger = logging.getLogger("talk_trace_ai")


@st.cache_resource
def init_db() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


def ensure_db_login(supabase: Client) -> bool:
    curr_session = None
    try:
        res = supabase.auth.get_session()
        curr_session = res.session if hasattr(res, "session") else res
    except Exception as e:
        logger.warning("기존 Supabase 세션 확인 실패: %s", e)
        curr_session = None

    if curr_session:
        return True

    try:
        supabase.auth.sign_in_with_password(
            {
                "email": st.secrets["SUPABASE_APP_EMAIL"],
                "password": st.secrets["SUPABASE_APP_PASSWORD"],
            }
        )
        time.sleep(0.5)
        return True
    except Exception as e:
        st.error(f"🚨 DB 자동 로그인 실패: {e}")
        return False

def execute_query(query, fail_message="DB 작업 실패"):
    try:
        return query.execute()
    except Exception as e:
        st.error(f"{fail_message}: {e}")
        logger.exception("%s: %s", fail_message, e)
        return None

def _is_undefined_column_error(error: Exception, column_name: str) -> bool:
    msg = str(error).lower()
    has_missing_column_signal = (
        "42703" in msg
        or "pgrst204" in msg
        or "does not exist" in msg
        or "could not find" in msg
    )
    return (
        has_missing_column_signal
        and column_name.lower() in msg
    )

@st.cache_data(ttl=300)
def debate_ip_column_available() -> bool:
    supabase = init_db()
    try:
        supabase.table("debate").select("ip_address").limit(1).execute()
        return True
    except Exception:
        return False

@st.cache_data(ttl=300)
def topic_entry_code_column_available() -> bool:
    supabase = init_db()
    try:
        supabase.table("topic").select("entry_code").limit(1).execute()
        return True
    except Exception as e:
        if _is_undefined_column_error(e, "entry_code"):
            return False
        logger.warning("topic.entry_code 컬럼 확인 중 예외 발생: %s", e)
        return False

def fetch_room_names(supabase: Client):
    res = execute_query(
        supabase.table("topic").select("room_name").order("room_name", desc=False),
        fail_message="🚨 방 목록 조회 에러",
    )
    if not res or not res.data:
        return []
    return [item.get("room_name", "") for item in res.data if item.get("room_name", "").strip()]


def upsert_topic_room(supabase: Client, room_name, title, mode, entry_code):
    payload = {
        "room_name": room_name,
        "title": title,
        "mode": mode,
        "entry_code": entry_code,
    }
    try:
        return supabase.table("topic").upsert(payload).execute()
    except Exception as e:
        if _is_undefined_column_error(e, "entry_code"):
            logger.warning("topic.entry_code 컬럼이 없어 공개방으로 저장합니다.")
            legacy_payload = {
                "room_name": room_name,
                "title": title,
                "mode": mode,
            }
            return execute_query(
                supabase.table("topic").upsert(legacy_payload),
                fail_message="방 개설 실패",
            )
        st.error(f"방 개설 실패: {e}")
        logger.exception("방 개설 실패: %s", e)
        return None

def fetch_room_entry_code(supabase: Client, room_name):
    try:
        res = (
            supabase.table("topic")
            .select("entry_code")
            .eq("room_name", room_name)
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        return res.data[0]["entry_code"] if res and res.data else ""
    except Exception as e:
        if _is_undefined_column_error(e, "entry_code"):
            logger.warning("topic.entry_code 컬럼이 없어 공개방으로 처리합니다.")
            return ""
        st.error(f"방 입장 암호 조회 실패: {e}")
        logger.exception("방 입장 암호 조회 실패: %s", e)
        return ""


def fetch_topic_data(supabase: Client, room_name):
    res = execute_query(
        supabase.table("topic").select("title, mode").eq("room_name", room_name).order("id", desc=True).limit(1),
        fail_message="주제 조회 실패",
    )
    return res.data[0] if res and res.data else {}


def fetch_live_messages(supabase: Client, room_name, limit):
    res = execute_query(
        supabase.table("debate").select("*").eq("room_name", room_name).order("id", desc=True).limit(limit),
        fail_message="🚨 데이터 불러오기 실패",
    )
    if not res or not res.data:
        logger.info("%s 방에 데이터가 없습니다.", room_name)
        return pd.DataFrame()
    return pd.DataFrame(res.data)


def submit_opinion(supabase: Client, payload):
    return execute_query(supabase.table("debate").insert(payload), fail_message="저장 실패")
