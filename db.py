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
    try:
        res = execute_query(
            supabase.table("topic")
            .select("room_name")
            .neq("created_by", "")
            .not_.is_("created_by", "null")
            .order("room_name", desc=False),
            fail_message="🚨 방 목록 조회 에러",
        )
    except Exception as e:
        if _is_undefined_column_error(e, "created_by"):
            logger.warning("topic.created_by 컬럼이 없어 교사 생성 방만 조회할 수 없습니다.")
            return []
        raise
    if not res or not res.data:
        return []
    visible_rooms = []
    for item in res.data:
        room = str(item.get("room_name", "")).strip()
        owner = str(item.get("created_by", "")).strip()
        if room and owner:
            visible_rooms.append(room)
    return visible_rooms

def fetch_room_names_by_owner(supabase: Client, owner_teacher_id: str):
    safe_owner = str(owner_teacher_id or "").strip()
    if not safe_owner:
        return []

    res = execute_query(
        supabase.table("topic")
        .select("room_name")
        .eq("created_by", safe_owner)
        .order("room_name", desc=False),
        fail_message="🚨 교사별 방 목록 조회 에러",
    )
    if not res or not res.data:
        return []
    return [item.get("room_name", "") for item in res.data if item.get("room_name", "").strip()]

@st.cache_data(ttl=300)
def topic_created_by_column_available() -> bool:
    supabase = init_db()
    try:
        supabase.table("topic").select("created_by").limit(1).execute()
        return True
    except Exception as e:
        if _is_undefined_column_error(e, "created_by"):
            return False
        logger.warning("topic.created_by 컬럼 확인 중 예외 발생: %s", e)
        return False

def upsert_topic_room(supabase: Client, room_name, title, mode, entry_code, created_by=None):
    payload = {
        "room_name": room_name,
        "title": title,
        "mode": mode,
        "entry_code": entry_code,
    }
    if created_by is not None:
        payload["created_by"] = str(created_by).strip()
    try:
        return supabase.table("topic").upsert(payload).execute()
    except Exception as e:
        if _is_undefined_column_error(e, "entry_code") or _is_undefined_column_error(e, "created_by"):
            logger.warning("topic.entry_code 또는 topic.created_by 컬럼이 없어 레거시 모드로 저장합니다.")
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
    order_candidates = ["id", "created_at", None]

    for order_col in order_candidates:
        try:
            query = (
                supabase.table("topic")
                .select("entry_code")
                .eq("room_name", room_name)
            )
            if order_col:
                query = query.order(order_col, desc=True)
            res = query.execute()
            if not res or not res.data:
                return ""

            raw_values = [item.get("entry_code") for item in res.data]
            if raw_values and all(value is None for value in raw_values):
                logger.warning("entry_code 조회 결과가 모두 None입니다. 권한/정책 문제로 판단되어 입장을 차단합니다.")
                return None

            # 동일 room_name 레코드가 여러 개인 환경에서는
            # 비어있지 않은 암호가 하나라도 있으면 암호방으로 취급한다.
            codes = [
                str(item.get("entry_code", "")).strip()
                for item in res.data
                if item.get("entry_code") is not None
            ]
            for code in codes:
                if code:
                    return code
            return ""
        except Exception as e:
            if _is_undefined_column_error(e, "entry_code"):
                logger.warning("topic.entry_code 컬럼이 없어 공개방으로 처리합니다.")
                return ""
            if order_col and _is_undefined_column_error(e, order_col):
                logger.info("topic.%s 컬럼이 없어 다음 정렬 기준으로 재시도합니다.", order_col)
                continue
            st.error(f"방 입장 암호 조회 실패: {e}")
            logger.exception("방 입장 암호 조회 실패: %s", e)
            return None
    return None


def fetch_topic_data(supabase: Client, room_name):
    order_candidates = ["id", "created_at", None]

    for order_col in order_candidates:
        try:
            query = (
                supabase.table("topic")
                .select("title, mode")
                .eq("room_name", room_name)
                .limit(1)
            )
            if order_col:
                query = query.order(order_col, desc=True)
            res = query.execute()
            return res.data[0] if res and res.data else {}
        except Exception as e:
            if order_col and _is_undefined_column_error(e, order_col):
                logger.info("topic.%s 컬럼이 없어 다음 정렬 기준으로 재시도합니다.", order_col)
                continue
            st.error(f"주제 조회 실패: {e}")
            logger.exception("주제 조회 실패: %s", e)
            return {}
    return {}


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



def fetch_teacher_account(supabase: Client, teacher_id: str):
    safe_id = str(teacher_id or '').strip()
    if not safe_id:
        return None
    res = execute_query(
        supabase.table("teacher_accounts").select("id, teacher_id, teacher_pw, is_approved, approved_at, requested_at").eq("teacher_id", safe_id).limit(1),
        fail_message="교사 계정 조회 실패",
    )
    if not res or not res.data:
        return None
    return res.data[0]


def request_teacher_account(supabase: Client, teacher_id: str, teacher_pw: str):
    payload = {
        "teacher_id": str(teacher_id or '').strip(),
        "teacher_pw": str(teacher_pw or '').strip(),
        "is_approved": False,
    }
    return execute_query(supabase.table("teacher_accounts").insert(payload), fail_message="교사 계정 신청 실패")


def fetch_pending_teacher_accounts(supabase: Client):
    res = execute_query(
        supabase.table("teacher_accounts").select("id, teacher_id, requested_at, is_approved").eq("is_approved", False).order("id", desc=False),
        fail_message="승인 대기 계정 조회 실패",
    )
    return res.data if res and res.data else []


def approve_teacher_account(supabase: Client, account_id: int, approved_at: str):
    return execute_query(
        supabase.table("teacher_accounts").update({"is_approved": True, "approved_at": approved_at}).eq("id", account_id),
        fail_message="교사 계정 승인 실패",
    )
