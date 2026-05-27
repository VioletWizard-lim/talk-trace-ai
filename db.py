import logging

import pandas as pd
import streamlit as st
from supabase import Client, create_client

from auth import _hash_password, _is_hashed, _verify_password  # noqa: F401
from env import get_secret

logger = logging.getLogger("talk_trace_ai")


def upgrade_teacher_password(supabase: Client, account_id: int, plain: str):
    return execute_query(
        supabase.table("teacher_accounts")
        .update({"teacher_pw": _hash_password(plain)})
        .eq("id", account_id),
        fail_message="비밀번호 업그레이드 실패",
    )


# ==========================================
# [1] DB 초기화 및 인증
# ==========================================

@st.cache_resource
def init_db() -> Client:
    supabase_url = get_secret("SUPABASE_URL")
    supabase_key = (
        get_secret("SUPABASE_SERVICE_ROLE_KEY")
        or get_secret("SUPABASE_KEY")
    )
    return create_client(supabase_url, supabase_key)


def using_service_role_key() -> bool:
    return bool(get_secret("SUPABASE_SERVICE_ROLE_KEY"))


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
                "email": get_secret("SUPABASE_APP_EMAIL"),
                "password": get_secret("SUPABASE_APP_PASSWORD"),
            }
        )
        return True
    except Exception as e:
        st.error(f"🚨 DB 자동 로그인 실패: {e}")
        return False


# ==========================================
# [2] 에러 분류 헬퍼
# ==========================================

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
            logger.error("RLS_PERMISSION_ERROR %s: %s", fail_message, e)
            st.error(
                f"🔒 {fail_message}: 권한 오류가 발생했습니다. "
                "Supabase 대시보드에서 RLS 정책 및 Service Role Key 설정을 확인해 주세요. "
                f"(오류코드: RLS_PERMISSION_ERROR)"
            )
        else:
            logger.exception("DB_ERROR %s: %s", fail_message, e)
            st.error(f"🚨 {fail_message}: {e} (오류코드: DB_ERROR)")
        return None


# ==========================================
# [3] 컬럼 존재 확인 — 통합 함수
# ==========================================

@st.cache_data(ttl=3600)
def check_schema_columns() -> dict:
    supabase = init_db()

    checks = [
        ("debate.ip_address",              lambda: supabase.table("debate").select("ip_address").limit(1).execute()),
        ("topic.entry_code",               lambda: supabase.table("topic").select("entry_code").limit(1).execute()),
        ("topic.created_by_teacher_id",    lambda: supabase.table("topic").select("created_by_teacher_id").limit(1).execute()),
        ("topic.created_by",               lambda: supabase.table("topic").select("created_by").limit(1).execute()),
        ("teacher_accounts.is_admin",      lambda: supabase.table("teacher_accounts").select("is_admin").limit(1).execute()),
        ("opinion_changes.pre_opinion",    lambda: supabase.table("opinion_changes").select("pre_opinion").limit(1).execute()),
        ("opinion_changes.initial_stance", lambda: supabase.table("opinion_changes").select("initial_stance").limit(1).execute()),
        ("session_control.status",         lambda: supabase.table("session_control").select("status").limit(1).execute()),
        ("likes.opinion_id",               lambda: supabase.table("likes").select("opinion_id").limit(1).execute()),
        ("debate.depth_level",             lambda: supabase.table("debate").select("depth_level").limit(1).execute()),
    ]

    results = {}
    for key, query_fn in checks:
        try:
            query_fn()
            results[key] = True
        except Exception as e:
            logger.info("컬럼 미존재 확인 [%s]: %s", key, e)
            results[key] = False

    logger.info("schema_columns 체크 완료: %s", results)
    return results


def debate_ip_column_available() -> bool:
    return check_schema_columns().get("debate.ip_address", False)

def topic_entry_code_column_available() -> bool:
    return check_schema_columns().get("topic.entry_code", False)

def topic_created_by_teacher_id_column_available() -> bool:
    return check_schema_columns().get("topic.created_by_teacher_id", False)

def topic_created_by_column_available() -> bool:
    return check_schema_columns().get("topic.created_by", False)

def topic_owner_column_available() -> bool:
    schema = check_schema_columns()
    return schema.get("topic.created_by_teacher_id", False) or schema.get("topic.created_by", False)

def opinion_changes_available() -> bool:
    return check_schema_columns().get("opinion_changes.pre_opinion", False)

def stance_available() -> bool:
    return check_schema_columns().get("opinion_changes.initial_stance", False)

def session_control_available() -> bool:
    return check_schema_columns().get("session_control.status", False)

def teacher_is_admin_column_available() -> bool:
    return check_schema_columns().get("teacher_accounts.is_admin", False)

def likes_available() -> bool:
    return check_schema_columns().get("likes.opinion_id", False)

def depth_level_available() -> bool:
    return check_schema_columns().get("debate.depth_level", False)


# ==========================================
# [4] 방(topic) 관련 쿼리
# ==========================================

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


def update_topic(supabase: Client, room_name, title, mode):
    return execute_query(
        supabase.table("topic").update({"title": title, "mode": mode}).eq("room_name", room_name),
        fail_message="주제 수정 실패",
    )


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


# ==========================================
# [5] 토론(debate) 관련 쿼리
# ==========================================

@st.cache_data(ttl=5)
def fetch_live_messages(_supabase: Client, room_name, limit):
    res = execute_query(
        _supabase.table("debate").select("*").eq("room_name", room_name).order("id", desc=True).limit(limit),
        fail_message="🚨 데이터 불러오기 실패",
    )
    if not res or not res.data:
        logger.info("%s 방에 데이터가 없습니다.", room_name)
        return pd.DataFrame()
    return pd.DataFrame(res.data)


def submit_opinion(supabase: Client, payload):
    return execute_query(supabase.table("debate").insert(payload), fail_message="저장 실패")


def is_recent_submission(supabase: Client, room_name: str, student_name: str, cooldown_seconds: int = 15) -> bool:
    """같은 학생이 cooldown_seconds 이내에 이미 제출했으면 True를 반환합니다."""
    from datetime import timedelta
    from utils import get_kst_now
    cutoff = (get_kst_now() - timedelta(seconds=cooldown_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    res = execute_query(
        supabase.table("debate")
        .select("id")
        .eq("room_name", room_name)
        .eq("student_name", student_name)
        .gte("timestamp", cutoff)
        .limit(1),
        fail_message="제출 간격 확인 실패",
    )
    return bool(res and res.data)


def delete_opinion_message(supabase: Client, message_id: int):
    return execute_query(
        supabase.table("debate").delete().eq("id", message_id),
        fail_message="의견 삭제 실패",
    )


def create_teacher_hint(supabase: Client, payload):
    return execute_query(
        supabase.table("debate").insert(payload),
        fail_message="교사 힌트 전송 실패",
    )



def destroy_room_data(supabase: Client, room_name: str):
    topic_res = execute_query(
        supabase.table("topic").delete().eq("room_name", room_name),
        fail_message="방 주제 삭제 실패",
    )
    debate_res = execute_query(
        supabase.table("debate").delete().eq("room_name", room_name),
        fail_message="방 의견 삭제 실패",
    )
    if topic_res is None or debate_res is None:
        return None
    if opinion_changes_available():
        execute_query(
            supabase.table("opinion_changes").delete().eq("room_name", room_name),
            fail_message="생각 변화 기록 삭제 실패",
        )
    if session_control_available():
        execute_query(
            supabase.table("session_control").delete().eq("room_name", room_name),
            fail_message="토론 제어 상태 삭제 실패",
        )
    return {"topic": topic_res, "debate": debate_res}


# ==========================================
# [6] 생각 변화 기록(opinion_changes) 관련 쿼리
# ==========================================

def fetch_opinion_change(supabase: Client, room_name: str, student_name: str):
    if not opinion_changes_available():
        return None
    res = execute_query(
        supabase.table("opinion_changes")
        .select("*")
        .eq("room_name", room_name)
        .eq("student_name", student_name)
        .limit(1),
        fail_message="생각 변화 조회 실패",
    )
    if not res or not res.data:
        return None
    return res.data[0]


def upsert_pre_opinion(supabase: Client, room_name: str, student_name: str, pre_opinion: str, initial_stance: str = None, ip_address: str = None):
    if not opinion_changes_available():
        return None
    payload = {"pre_opinion": pre_opinion}
    if initial_stance and stance_available():
        payload["initial_stance"] = initial_stance
    existing = fetch_opinion_change(supabase, room_name, student_name)
    if existing is not None:
        res = execute_query(
            supabase.table("opinion_changes").update(payload).eq("room_name", room_name).eq("student_name", student_name),
            fail_message="토론 전 생각 저장 실패",
        )
    else:
        res = execute_query(
            supabase.table("opinion_changes").insert({"room_name": room_name, "student_name": student_name, **payload}),
            fail_message="토론 전 생각 저장 실패",
        )
    # IP는 별도 업데이트 — 컬럼 미존재 시 실패해도 메인 저장에 영향 없음
    if ip_address and res is not None:
        try:
            supabase.table("opinion_changes").update({"ip_address": ip_address}).eq("room_name", room_name).eq("student_name", student_name).execute()
        except Exception:
            pass
    return res


def upsert_post_opinion(supabase: Client, room_name: str, student_name: str, post_opinion: str, final_stance: str = None, discussion_conclusion: str = None):
    if not opinion_changes_available():
        return None
    payload = {"post_opinion": post_opinion}
    if final_stance and stance_available():
        payload["final_stance"] = final_stance
    if discussion_conclusion and stance_available():
        payload["discussion_conclusion"] = discussion_conclusion
    existing = fetch_opinion_change(supabase, room_name, student_name)
    if existing is not None:
        return execute_query(
            supabase.table("opinion_changes").update(payload).eq("room_name", room_name).eq("student_name", student_name),
            fail_message="토론 후 생각 저장 실패",
        )
    return execute_query(
        supabase.table("opinion_changes").insert({"room_name": room_name, "student_name": student_name, **payload}),
        fail_message="토론 후 생각 저장 실패",
    )


def fetch_all_opinion_changes(supabase: Client, room_name: str):
    if not opinion_changes_available():
        return pd.DataFrame()
    res = execute_query(
        supabase.table("opinion_changes")
        .select("*")
        .eq("room_name", room_name)
        .order("student_name"),
        fail_message="학생별 생각 변화 조회 실패",
    )
    if not res or not res.data:
        return pd.DataFrame()
    return pd.DataFrame(res.data)


def save_opinion_analysis(supabase: Client, room_name: str, student_name: str, ai_analysis: str):
    if not opinion_changes_available():
        return None
    return execute_query(
        supabase.table("opinion_changes")
        .update({"ai_analysis": ai_analysis})
        .eq("room_name", room_name)
        .eq("student_name", student_name),
        fail_message="AI 분석 저장 실패",
    )


def delete_opinion_change(supabase: Client, room_name: str, student_name: str):
    if not opinion_changes_available():
        return None
    return execute_query(
        supabase.table("opinion_changes")
        .delete()
        .eq("room_name", room_name)
        .eq("student_name", student_name),
        fail_message="학생 배움 분석 기록 삭제 실패",
    )


# ==========================================
# [7] 토론 제어(session_control) 관련 쿼리
# ==========================================

@st.cache_data(ttl=5)
def fetch_debate_status(_supabase: Client, room_name: str) -> str:
    if not session_control_available():
        return "active"
    res = execute_query(
        _supabase.table("session_control")
        .select("status")
        .eq("room_name", room_name)
        .limit(1),
        fail_message="토론 상태 조회 실패",
    )
    if not res or not res.data:
        return "active"
    return res.data[0].get("status", "active")


def set_debate_status(supabase: Client, room_name: str, status: str):
    if not session_control_available():
        return None
    existing = execute_query(
        supabase.table("session_control").select("room_name").eq("room_name", room_name).limit(1),
        fail_message="토론 상태 확인 실패",
    )
    if existing and existing.data:
        res = execute_query(
            supabase.table("session_control").update({"status": status}).eq("room_name", room_name),
            fail_message="토론 상태 변경 실패",
        )
    else:
        res = execute_query(
            supabase.table("session_control").insert({"room_name": room_name, "status": status}),
            fail_message="토론 상태 생성 실패",
        )
    if res is not None:
        fetch_debate_status.clear()
    return res


# ==========================================
# [8] 교사 계정(teacher_accounts) 관련 쿼리
# ==========================================

def fetch_teacher_account(supabase: Client, teacher_id: str):
    safe_id = str(teacher_id or "").strip()
    if not safe_id:
        return None

    teacher_select = (
        "id, teacher_id, teacher_pw, is_approved, approved_at, requested_at, is_admin"
        if teacher_is_admin_column_available()
        else "id, teacher_id, teacher_pw, is_approved, approved_at, requested_at"
    )

    res = execute_query(
        supabase.table("teacher_accounts")
        .select(teacher_select)
        .eq("teacher_id", safe_id)
        .limit(1),
        fail_message="교사 계정 조회 실패",
    )
    if res is None:
        return {"_query_failed": True}
    if res.data:
        return res.data[0]

    ci_res = execute_query(
        supabase.table("teacher_accounts")
        .select(teacher_select)
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
        "teacher_pw": _hash_password(str(teacher_pw or "").strip()),
        "is_approved": False,
    }
    if teacher_is_admin_column_available():
        payload["is_admin"] = False
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


def reject_teacher_account(supabase: Client, account_id: int):
    return execute_query(
        supabase.table("teacher_accounts").delete().eq("id", account_id),
        fail_message="교사 계정 거절 실패",
    )


# ==========================================
# [공감(likes)] 관련 쿼리
# ==========================================

@st.cache_data(ttl=3)
def fetch_room_likes(_supabase: Client, room_name: str):
    """방의 모든 공감 데이터를 반환한다: [{"opinion_id": ..., "student_name": ...}, ...]"""
    res = execute_query(
        _supabase.table("likes").select("opinion_id, student_name").eq("room_name", room_name),
        fail_message="공감 데이터 조회 실패",
    )
    return res.data if res and res.data else []


# ==========================================
# [발언 깊이 분석(depth_level)] 관련 쿼리
# ==========================================

def fetch_opinions_for_depth(supabase: Client, room_name: str) -> list:
    """깊이 분석용 발언 전체 조회 (학생 발언만, id/content/depth_level/timestamp/student_name)."""
    if not depth_level_available():
        return []
    res = execute_query(
        supabase.table("debate")
        .select("id, content, depth_level, timestamp, student_name, sentiment")
        .eq("room_name", room_name)
        .not_.ilike("student_name", "%선생님%")
        .order("id", desc=False),
        fail_message="발언 깊이 데이터 조회 실패",
    )
    return res.data if res and res.data else []


def bulk_update_depth_levels(supabase: Client, updates: list) -> bool:
    """updates: list of {"id": int, "depth_level": int}. True if all succeeded."""
    success = True
    for item in updates:
        res = execute_query(
            supabase.table("debate")
            .update({"depth_level": item["depth_level"]})
            .eq("id", item["id"]),
            fail_message=f"발언 깊이 업데이트 실패 (id={item['id']})",
        )
        if res is None:
            success = False
    return success


def toggle_like(supabase: Client, opinion_id: int, room_name: str, student_name: str) -> bool:
    """공감 토글. 이미 공감 시 취소(False 반환), 없으면 추가(True 반환)."""
    existing = execute_query(
        supabase.table("likes").select("id").eq("opinion_id", opinion_id).eq("student_name", student_name),
        fail_message="공감 확인 실패",
    )
    if existing and existing.data:
        execute_query(
            supabase.table("likes").delete().eq("opinion_id", opinion_id).eq("student_name", student_name),
            fail_message="공감 취소 실패",
        )
        return False
    else:
        execute_query(
            supabase.table("likes").insert({"opinion_id": opinion_id, "room_name": room_name, "student_name": student_name}),
            fail_message="공감 추가 실패",
        )
        return True
