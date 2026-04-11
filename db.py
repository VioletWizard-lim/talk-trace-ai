import logging
import time

import pandas as pd
import streamlit as st
from supabase import Client, create_client


logger = logging.getLogger("talk_trace_ai")


@st.cache_resource
def init_db() -> Client:
    supabase_key = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY") or st.secrets["SUPABASE_KEY"]
    return create_client(st.secrets["SUPABASE_URL"], supabase_key)

def using_service_role_key() -> bool:
    return bool(str(st.secrets.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip())

def ensure_db_login(supabase: Client) -> bool:
    curr_session = None
    try:
        res = supabase.auth.get_session()
        curr_session = res.session if hasattr(res, "session") else res
    except Exception as e:
        logger.warning("기존 Supabase 세션 확인 실패: %s", e)

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


def _is_undefined_column_error(error: Exception, column_name: str) -> bool:
    msg = str(error).lower()
    has_missing_column_signal = (
        "42703" in msg
        or "pgrst204" in msg
        or "does not exist" in msg
        or "could not find" in msg
    )
    return has_missing_column_signal and column_name.lower() in msg
    
def _is_rls_permission_error(error: Exception) -> bool:
    msg = str(error).lower()
    return (
        "42501" in msg
        or "permission denied" in msg
        or "row-level security" in msg
        or "violates row-level security policy" in msg
    )

def execute_query(query, fail_message="DB 작업 실패"):
    try:
        return query.execute()
    except Exception as e:
        if _is_rls_permission_error(e):
            st.error(f"{fail_message}: {e} (RLS 정책 또는 권한 설정을 확인해 주세요)")
        else:
            st.error(f"{fail_message}: {e}")
        logger.exception("%s: %s", fail_message, e)
        return None

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

@st.cache_data(ttl=300)
def topic_created_by_teacher_id_column_available() -> bool:
    supabase = init_db()
    try:
        supabase.table("topic").select("created_by_teacher_id").limit(1).execute()
        return True
    except Exception as e:
        if _is_undefined_column_error(e, "created_by_teacher_id"):
            return False
        logger.warning("topic.created_by_teacher_id 컬럼 확인 중 예외 발생: %s", e)
        return False

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

def topic_owner_column_available() -> bool:
    return topic_created_by_teacher_id_column_available() or topic_created_by_column_available()

def fetch_room_names(supabase: Client):
    if topic_created_by_teacher_id_column_available():
        res = execute_query(
            supabase.table("topic")
            .select("room_name, created_by_teacher_id")
            .not_.is_("created_by_teacher_id", "null")
            .order("room_name", desc=False),
            fail_message="🚨 방 목록 조회 에러",
        )
        if not res or not res.data:
            return []
        return [
            str(item.get("room_name", "")).strip()
            for item in res.data
            if str(item.get("room_name", "")).strip() and str(item.get("created_by_teacher_id", "")).strip()
        ]

    res = execute_query(
        supabase.table("topic")
        .select("room_name, created_by")
        .not_.is_("created_by", "null")
        .order("room_name", desc=False),
        fail_message="🚨 방 목록 조회 에러",
    )
    if not res or not res.data:
        return []
    return [
        str(item.get("room_name", "")).strip()
        for item in res.data
        if str(item.get("room_name", "")).strip() and str(item.get("created_by", "")).strip()
    ]

def fetch_room_names_by_owner(supabase: Client, owner_teacher_id: str):
    safe_owner = str(owner_teacher_id or "").strip()
    if not safe_owner:
        return []

    if topic_created_by_teacher_id_column_available():
        res = execute_query(
            supabase.table("topic")
            .select("room_name")
            .eq("created_by_teacher_id", safe_owner)
            .order("room_name", desc=False),
            fail_message="🚨 교사별 방 목록 조회 에러",
        )
        if not res or not res.data:
            return []
        return [item.get("room_name", "") for item in res.data if str(item.get("room_name", "")).strip()]
    
    res = execute_query(
        supabase.table("topic")
        .select("room_name")
        .eq("created_by", safe_owner)
        .order("room_name", desc=False),
        fail_message="🚨 교사별 방 목록 조회 에러",
    )
    if not res or not res.data:
        return []
    return [item.get("room_name", "") for item in res.data if str(item.get("room_name", "")).strip()]

def upsert_topic_room(supabase: Client, room_name, title, mode, entry_code, created_by=None):
    payload = {
        "room_name": room_name,
        "title": title,
        "mode": mode,
        "entry_code": entry_code,
    }
    if topic_created_by_teacher_id_column_available() and created_by is not None:
        payload["created_by_teacher_id"] = str(created_by).strip()
    elif created_by is not None:
        payload["created_by"] = str(created_by).strip()
    return execute_query(supabase.table("topic").upsert(payload), fail_message="방 개설 실패")

def fetch_room_entry_code(supabase: Client, room_name):
    order_candidates = ["id", "created_at", None]

    for order_col in order_candidates:
        try:
            query = supabase.table("topic").select("entry_code").eq("room_name", room_name)
            if order_col:
                query = query.order(order_col, desc=True)
            res = query.execute()
            if not res or not res.data:
                return ""

            raw_values = [item.get("entry_code") for item in res.data]
            if raw_values and all(value is None for value in raw_values):
                logger.warning("entry_code 조회 결과가 모두 None입니다. 권한/정책 문제로 판단되어 입장을 차단합니다.")
                return None

            for code in [str(v).strip() for v in raw_values if v is not None]:
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
            query = supabase.table("topic").select("title, mode").eq("room_name", room_name).limit(1)
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
    safe_id = str(teacher_id or "").strip()
    if not safe_id:
        return None
    res = execute_query(
        supabase.table("teacher_accounts")
        .select("id, teacher_id, teacher_pw, is_approved, approved_at, requested_at")
        .eq("teacher_id", safe_id)
        .limit(1),
        fail_message="교사 계정 조회 실패",
    )
    if res is None:
        return {"_query_failed": True}
    if res.data:
        return res.data[0]

    # 대소문자 차이로 인한 로그인 실패를 줄이기 위해 2차 조회(대소문자 무시)를 수행합니다.
    ci_res = execute_query(
        supabase.table("teacher_accounts")
        .select("id, teacher_id, teacher_pw, is_approved, approved_at, requested_at")
        .ilike("teacher_id", safe_id)
        .limit(1),
        fail_message="교사 계정 조회 실패",
    )
    if ci_res is None:
        return {"_query_failed": True}
    if not ci_res.data:
        return None
    return ci_res.data[0]



def request_teacher_account(supabase: Client, teacher_id: str, teacher_pw: str):
    payload = {
        "teacher_id": str(teacher_id or "").strip(),
        "teacher_pw": str(teacher_pw or "").strip(),
        "is_approved": False,
    }
    return execute_query(supabase.table("teacher_accounts").insert(payload), fail_message="교사 계정 신청 실패")

def fetch_pending_teacher_accounts(supabase: Client):
    res = execute_query(
        supabase.table("teacher_accounts")
        .select("id, teacher_id, requested_at, is_approved")
        .eq("is_approved", False)
        .order("id", desc=False),
        fail_message="승인 대기 계정 조회 실패",
    )
    return res.data if res and res.data else []


def approve_teacher_account(supabase: Client, account_id: int, approved_at: str):
    return execute_query(
        supabase.table("teacher_accounts").update({"is_approved": True, "approved_at": approved_at}).eq("id", account_id),
        fail_message="교사 계정 승인 실패",
    )
