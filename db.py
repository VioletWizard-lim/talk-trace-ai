import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import streamlit as st
from supabase import Client, create_client

from auth import _hash_password, _is_hashed, _verify_password  # noqa: F401
from env import get_secret
from utils import get_kst_now_str

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


_CONNECTION_ERROR_KEYWORDS = (
    "network", "eof",
    "unreachable", "broken pipe", "remote end closed",
    "connection refused", "connection reset", "connection timed out", "connection closed",
    "ssl", "timed out", "read timeout", "connect timeout",
)


def _is_connection_error(error: Exception) -> bool:
    # 예외 타입으로 먼저 확인 (키워드보다 신뢰성 높음)
    try:
        import httpx
        if isinstance(error, (httpx.ConnectError, httpx.TimeoutException,
                               httpx.RemoteProtocolError, httpx.ReadError)):
            return True
    except ImportError:
        pass
    import ssl as _ssl
    if isinstance(error, _ssl.SSLError):
        return True
    msg = str(error).lower()
    return any(k in msg for k in _CONNECTION_ERROR_KEYWORDS)


def execute_query(query, fail_message="DB 작업 실패"):
    try:
        return query.execute()
    except Exception as e:
        if _is_connection_error(e):
            logger.error("CONNECTION_ERROR %s: %s", fail_message, e)
            init_db.clear()
            check_schema_columns.clear()
            st.warning(
                "🌐 Supabase 연결이 일시적으로 끊어졌습니다. "
                "**페이지를 새로고침(F5)하면 자동으로 재연결됩니다.**"
            )
        elif _is_rls_permission_error(e):
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

@st.cache_data(ttl=300)
def check_schema_columns() -> dict:
    supabase = init_db()

    checks = [
        ("debate.ip_address",              lambda: supabase.table("debate").select("ip_address").limit(1).execute()),
        ("debate.session_id",              lambda: supabase.table("debate").select("session_id").limit(1).execute()),
        ("debate.is_deleted",              lambda: supabase.table("debate").select("is_deleted").limit(1).execute()),
        ("debate.deleted_by",              lambda: supabase.table("debate").select("deleted_by").limit(1).execute()),
        ("debate.deleted_at",              lambda: supabase.table("debate").select("deleted_at").limit(1).execute()),
        ("opinion_changes.session_id",     lambda: supabase.table("opinion_changes").select("session_id").limit(1).execute()),
        ("topic.entry_code",               lambda: supabase.table("topic").select("entry_code").limit(1).execute()),
        ("topic.created_by_teacher_id",    lambda: supabase.table("topic").select("created_by_teacher_id").limit(1).execute()),
        ("topic.created_by",               lambda: supabase.table("topic").select("created_by").limit(1).execute()),
        ("teacher_accounts.is_admin",      lambda: supabase.table("teacher_accounts").select("is_admin").limit(1).execute()),
        ("opinion_changes.pre_opinion",    lambda: supabase.table("opinion_changes").select("pre_opinion").limit(1).execute()),
        ("opinion_changes.initial_stance", lambda: supabase.table("opinion_changes").select("initial_stance").limit(1).execute()),
        ("session_control.status",         lambda: supabase.table("session_control").select("status").limit(1).execute()),
        ("likes.opinion_id",               lambda: supabase.table("likes").select("opinion_id").limit(1).execute()),
        ("debate.depth_level",             lambda: supabase.table("debate").select("depth_level").limit(1).execute()),
        ("opinion_changes.ai_feedback",    lambda: supabase.table("opinion_changes").select("ai_feedback").limit(1).execute()),
        ("topic.ai_report",                lambda: supabase.table("topic").select("ai_report").limit(1).execute()),
        ("topic.is_hidden",                lambda: supabase.table("topic").select("is_hidden").limit(1).execute()),
        ("session_attempts.session_id",    lambda: supabase.table("session_attempts").select("session_id").limit(1).execute()),
        ("comments.debate_id",             lambda: supabase.table("comments").select("debate_id").limit(1).execute()),
        ("comments.ip_address",            lambda: supabase.table("comments").select("ip_address").limit(1).execute()),
        ("comments.session_id",            lambda: supabase.table("comments").select("session_id").limit(1).execute()),
        ("comment_likes.comment_id",       lambda: supabase.table("comment_likes").select("comment_id").limit(1).execute()),
        ("content_flags.reason",           lambda: supabase.table("content_flags").select("reason").limit(1).execute()),
        ("teacher_accounts.is_judge",      lambda: supabase.table("teacher_accounts").select("is_judge").limit(1).execute()),
        ("teacher_accounts.is_active",     lambda: supabase.table("teacher_accounts").select("is_active").limit(1).execute()),
    ]

    def _run_check(item):
        key, query_fn = item
        try:
            query_fn()
            return key, True, None
        except Exception as e:
            if _is_connection_error(e):
                return key, False, e
            logger.info("컬럼 미존재 확인 [%s]: %s", key, e)
            return key, False, None

    results = {}
    connection_error: Exception | None = None
    with ThreadPoolExecutor(max_workers=len(checks)) as executor:
        for key, ok, err in executor.map(_run_check, checks):
            results[key] = ok
            if err is not None:
                connection_error = err

    if connection_error is not None:
        # 연결 오류 발생 시 결과를 캐시하지 않고 예외 전파 → 다음 호출 시 재시도
        raise RuntimeError(f"Supabase 연결 오류로 스키마 체크 실패: {connection_error}") from connection_error

    logger.info("schema_columns 체크 완료: %s", results)
    return results


def _schema() -> dict:
    """check_schema_columns를 안전하게 호출 — 연결 오류 시 빈 dict 반환."""
    try:
        return check_schema_columns()
    except Exception as e:
        logger.warning("스키마 체크 실패, 기능 플래그를 기본값(False)으로 처리합니다: %s", e)
        return {}


def debate_ip_column_available() -> bool:
    return _schema().get("debate.ip_address", False)

def debate_session_id_column_available() -> bool:
    return _schema().get("debate.session_id", False)

def debate_soft_delete_available() -> bool:
    return _schema().get("debate.is_deleted", False)

def debate_deleted_by_column_available() -> bool:
    return _schema().get("debate.deleted_by", False)

def debate_deleted_at_column_available() -> bool:
    return _schema().get("debate.deleted_at", False)

def opinion_changes_session_id_column_available() -> bool:
    return _schema().get("opinion_changes.session_id", False)

def topic_entry_code_column_available() -> bool:
    return _schema().get("topic.entry_code", False)

def topic_created_by_teacher_id_column_available() -> bool:
    return _schema().get("topic.created_by_teacher_id", False)

def topic_created_by_column_available() -> bool:
    return _schema().get("topic.created_by", False)

def topic_owner_column_available() -> bool:
    schema = _schema()
    return schema.get("topic.created_by_teacher_id", False) or schema.get("topic.created_by", False)

def opinion_changes_available() -> bool:
    return _schema().get("opinion_changes.pre_opinion", False)

def stance_available() -> bool:
    return _schema().get("opinion_changes.initial_stance", False)

def session_control_available() -> bool:
    return _schema().get("session_control.status", False)

def teacher_is_admin_column_available() -> bool:
    return _schema().get("teacher_accounts.is_admin", False)

def likes_available() -> bool:
    return _schema().get("likes.opinion_id", False)

def depth_level_available() -> bool:
    return _schema().get("debate.depth_level", False)

def ai_feedback_available() -> bool:
    return _schema().get("opinion_changes.ai_feedback", False)

def session_attempts_available() -> bool:
    return _schema().get("session_attempts.session_id", False)

def comments_available() -> bool:
    return _schema().get("comments.debate_id", False)

def comments_ip_column_available() -> bool:
    return _schema().get("comments.ip_address", False)

def comments_session_id_column_available() -> bool:
    return _schema().get("comments.session_id", False)

def content_flags_available() -> bool:
    return _schema().get("content_flags.reason", False)


def teacher_judge_column_available() -> bool:
    return _schema().get("teacher_accounts.is_judge", False)


def teacher_active_column_available() -> bool:
    return _schema().get("teacher_accounts.is_active", False)


def comment_likes_available() -> bool:
    return _schema().get("comment_likes.comment_id", False)


# ==========================================
# [4] 방(topic) 관련 쿼리
# ==========================================

@st.cache_data(ttl=20, show_spinner="설정을 불러오는 중입니다...")
def fetch_room_names(_supabase: Client, include_hidden: bool = False):
    hide_filter = topic_is_hidden_available() and not include_hidden

    if topic_created_by_teacher_id_column_available():
        q = (
            _supabase.table("topic")
            .select("room_name, created_by_teacher_id")
            .not_.is_("created_by_teacher_id", "null")
            .order("room_name", desc=False)
        )
        if hide_filter:
            q = q.eq("is_hidden", False)
        res = execute_query(q, fail_message="🚨 방 목록 조회 에러")
        if not res or not res.data:
            return []
        return [
            str(item.get("room_name", "")).strip()
            for item in res.data
            if str(item.get("room_name", "")).strip() and str(item.get("created_by_teacher_id", "")).strip()
        ]

    q = (
        _supabase.table("topic")
        .select("room_name, created_by")
        .not_.is_("created_by", "null")
        .order("room_name", desc=False)
    )
    if hide_filter:
        q = q.eq("is_hidden", False)
    res = execute_query(q, fail_message="🚨 방 목록 조회 에러")
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


def topic_ai_report_available() -> bool:
    return _schema().get("topic.ai_report", False)

def topic_is_hidden_available() -> bool:
    return _schema().get("topic.is_hidden", False)

def toggle_room_visibility(supabase: Client, room_name: str, hidden: bool):
    res = execute_query(
        supabase.table("topic").update({"is_hidden": hidden}).eq("room_name", room_name),
        fail_message="방 숨기기 설정 실패",
    )
    if res is not None:
        fetch_room_names.clear()
        fetch_all_rooms_hidden_status.clear()
    return res

@st.cache_data(ttl=10)
def fetch_all_rooms_hidden_status(_supabase: Client) -> dict:
    """모든 방의 숨김 상태를 한 번에 조회해 {room_name: is_hidden} dict 반환."""
    if not topic_is_hidden_available():
        return {}
    res = execute_query(
        _supabase.table("topic").select("room_name, is_hidden").order("room_name"),
        fail_message="방 숨김 상태 일괄 조회 실패",
    )
    if not res or not res.data:
        return {}
    return {item["room_name"]: bool(item.get("is_hidden", False)) for item in res.data}

def fetch_room_is_hidden(supabase: Client, room_name: str) -> bool:
    return fetch_all_rooms_hidden_status(supabase).get(room_name, False)


def save_ai_report(supabase: Client, room_name: str, report_text: str):
    return execute_query(
        supabase.table("topic").update({"ai_report": report_text}).eq("room_name", room_name),
        fail_message="AI 리포트 저장 실패",
    )


def fetch_ai_report(supabase: Client, room_name: str) -> str:
    try:
        res = supabase.table("topic").select("ai_report").eq("room_name", room_name).limit(1).execute()
        if res and res.data:
            return str(res.data[0].get("ai_report") or "")
    except Exception as e:
        logger.warning("AI 리포트 불러오기 실패: %s", e)
    return ""


def update_topic(supabase: Client, room_name, title, mode):
    res = execute_query(
        supabase.table("topic").update({"title": title, "mode": mode}).eq("room_name", room_name),
        fail_message="주제 수정 실패",
    )
    if res is not None:
        fetch_topic_data.clear()
    return res


def update_room_entry_code(supabase: Client, room_name: str, entry_code: str):
    return execute_query(
        supabase.table("topic").update({"entry_code": entry_code}).eq("room_name", room_name),
        fail_message="방 암호 변경 실패",
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

    res = execute_query(supabase.table("topic").upsert(payload), fail_message="방 개설 실패")
    if res is not None:
        fetch_room_names.clear()
    return res


@st.cache_resource
def _resolve_topic_order_col(_supabase: Client):
    """topic 테이블 정렬에 쓸 수 있는 컬럼을 프로세스당 한 번만 판별해 캐시.
    topic 테이블에는 id 컬럼이 없으므로(room_name이 PK) 시도하지 않고,
    created_at으로 바로 시도한다 — 없는 컬럼을 매번 찔러보며 42703 에러로
    로그를 채우는 것을 방지하기 위함."""
    for order_col in ["created_at", None]:
        try:
            query = _supabase.table("topic").select("room_name")
            if order_col:
                query = query.order(order_col, desc=True)
            query.limit(1).execute()
            return order_col
        except Exception as e:
            if order_col and _is_undefined_column_error(e, order_col):
                logger.info("topic.%s 컬럼이 없어 정렬 기준에서 제외합니다.", order_col)
                continue
            return None
    return None


def fetch_room_entry_code(supabase: Client, room_name):
    order_col = _resolve_topic_order_col(supabase)
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
        st.error(f"방 입장 암호 조회 실패: {e}")
        logger.exception("방 입장 암호 조회 실패: %s", e)
        return None


@st.cache_data(ttl=30)
def fetch_topic_data(_supabase: Client, room_name):
    order_col = _resolve_topic_order_col(_supabase)
    try:
        query = _supabase.table("topic").select("title, mode").eq("room_name", room_name).limit(1)
        if order_col:
            query = query.order(order_col, desc=True)
        res = query.execute()
        return res.data[0] if res and res.data else {}
    except Exception as e:
        st.error(f"주제 조회 실패: {e}")
        logger.exception("주제 조회 실패: %s", e)
        return {}


# ==========================================
# [5] 토론(debate) 관련 쿼리
# ==========================================

@st.cache_data(ttl=20)
def fetch_live_messages(_supabase: Client, room_name, limit):
    query = _supabase.table("debate").select("*").eq("room_name", room_name)
    if debate_soft_delete_available():
        # 삭제된(보관함으로 이동한) 발언은 실시간 보드/통계에서 제외
        query = query.or_("is_deleted.is.null,is_deleted.eq.false")
    res = execute_query(
        query.order("id", desc=True).limit(limit),
        fail_message="🚨 데이터 불러오기 실패",
    )
    if not res or not res.data:
        logger.info("%s 방에 데이터가 없습니다.", room_name)
        return pd.DataFrame()
    return pd.DataFrame(res.data)


def fetch_latest_message_id(supabase: Client, room_name: str):
    """이 방의 가장 최근 발언 id만 가볍게 조회합니다 (변경 감지 전용, 캐시 없음).

    실시간 보드가 새 발언 유무만 자주 확인할 때 쓰는 저비용 쿼리 — id 하나만
    가져오므로 fetch_live_messages(전체 발언+컬럼)보다 훨씬 가볍다.
    """
    res = execute_query(
        supabase.table("debate").select("id").eq("room_name", room_name).order("id", desc=True).limit(1),
        fail_message="최신 발언 확인 실패",
    )
    if res and res.data:
        return res.data[0]["id"]
    return None


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


def find_duplicate_session(
    supabase: Client, room_name: str, student_name: str, current_session_id: str, window_minutes: int = 10
) -> bool:
    """같은 방·같은 학번이 다른 브라우저/기기(session_id)에서 최근에 활동했는지 확인합니다.

    차단은 하지 않고 경고 표시용으로만 쓰인다. session_id 컬럼이 없으면 확인 불가하므로 False.
    """
    if not current_session_id:
        return False

    from datetime import timedelta
    from utils import get_kst_now
    cutoff = (get_kst_now() - timedelta(minutes=window_minutes)).strftime("%Y-%m-%d %H:%M:%S")

    if debate_session_id_column_available():
        res = execute_query(
            supabase.table("debate")
            .select("session_id")
            .eq("room_name", room_name)
            .eq("student_name", student_name)
            .neq("session_id", current_session_id)
            .gte("timestamp", cutoff)
            .limit(1),
            fail_message="중복 접속 확인 실패",
        )
        if res and res.data:
            return True

    if opinion_changes_session_id_column_available():
        res = execute_query(
            supabase.table("opinion_changes")
            .select("session_id")
            .eq("room_name", room_name)
            .eq("student_name", student_name)
            .neq("session_id", current_session_id)
            .limit(1),
            fail_message="중복 접속 확인 실패(opinion_changes)",
        )
        if res and res.data:
            return True

    return False


def check_and_log_presence(
    supabase: Client, room_name: str, student_name: str, session_id: str, window_minutes: int = 5
) -> bool:
    """입장 시점에 학번 점유 상태를 확인하고, 이번 시도를 session_attempts에 기록한다.

    별도의 점유(presence) 테이블 없이, session_attempts의 "이 학번에 대한 가장 최근 행"을
    현재 점유자로 간주한다 — 시도 기록과 점유 확인을 하나의 로그 테이블로 겸한다.

    - 최근(window_minutes 이내) 다른 session_id의 기록이 있으면 → 다른 사람이 아직
      쓰고 있다는 뜻이므로 True(중복 경고 필요) 반환.
    - 기록이 없거나, 나 자신의 기록이거나, 오래(window_minutes 이상) 조용했던 기록이면 → False.

    반환값과 무관하게 이번 시도는 항상 기록되므로, 먼저 들어온 사람이 새로고침해도
    자기 자신이 침입자로 오인되지 않는다. session_attempts 테이블이 없으면 확인
    자체가 불가능하므로 항상 False.
    """
    if not session_attempts_available() or not session_id:
        return False

    from datetime import timedelta
    from utils import get_kst_now
    cutoff = (get_kst_now() - timedelta(minutes=window_minutes)).strftime("%Y-%m-%d %H:%M:%S")

    latest = execute_query(
        supabase.table("session_attempts")
        .select("session_id, last_seen")
        .eq("room_name", room_name)
        .eq("student_name", student_name)
        .order("last_seen", desc=True)
        .limit(1),
        fail_message="접속 기록 조회 실패",
    )
    row = latest.data[0] if latest and latest.data else None
    is_duplicate = bool(row and row.get("session_id") != session_id and (row.get("last_seen") or "") >= cutoff)

    log_session_attempt(supabase, room_name, session_id, student_name)
    return is_duplicate


def touch_session_attempt(supabase: Client, room_name: str, student_name: str, session_id: str):
    """접속을 유지 중임을 알리는 heartbeat. 새 행을 추가하지 않고 기존 최신 행의 last_seen만 갱신한다.

    입장할 때마다(log_session_attempt) 새 행이 쌓이는 것과 달리, 접속을 유지하는 동안
    반복 호출되는 heartbeat까지 매번 새 행을 쌓으면 session_attempts가 불필요하게
    커지므로, 같은 (room, 학번, session_id) 조합의 최신 행을 찾아 갱신만 한다.
    """
    if not session_attempts_available() or not session_id:
        return None
    existing = execute_query(
        supabase.table("session_attempts")
        .select("id")
        .eq("room_name", room_name)
        .eq("student_name", student_name)
        .eq("session_id", session_id)
        .order("last_seen", desc=True)
        .limit(1),
        fail_message="접속 기록 조회 실패(heartbeat)",
    )
    if existing and existing.data:
        return execute_query(
            supabase.table("session_attempts").update({"last_seen": get_kst_now_str()}).eq("id", existing.data[0]["id"]),
            fail_message="접속 기록 갱신 실패(heartbeat)",
        )
    return log_session_attempt(supabase, room_name, session_id, student_name)


def find_number_switch_abuse(
    supabase: Client,
    room_name: str,
    session_id: str,
    student_name: str,
    window_minutes: int = 10,
    max_numbers: int = 3,
) -> list:
    """같은 브라우저(session_id)가 같은 방에서 최근 서로 다른 학번을 몇 개나 시도했는지 확인합니다.

    session_attempts는 점유 성공 여부와 무관하게 모든 시도를 기록하므로,
    이미 남이 점유 중인 학번에 계속 들어가려고 시도만 하는 경우도 카운트에 포함된다.

    오타 등 실수를 감안해 max_numbers(기본 3개)까지는 허용하고,
    이번 시도까지 포함해 그 이상이 되면 이미 시도한 다른 학번 목록을 반환한다
    (허용 범위 내면 빈 리스트).
    """
    if not session_attempts_available() or not session_id:
        return []

    from datetime import timedelta
    from utils import get_kst_now
    cutoff = (get_kst_now() - timedelta(minutes=window_minutes)).strftime("%Y-%m-%d %H:%M:%S")

    res = execute_query(
        supabase.table("session_attempts")
        .select("student_name")
        .eq("room_name", room_name)
        .eq("session_id", session_id)
        .gte("last_seen", cutoff),
        fail_message="학번 전환 확인 실패",
    )
    others = sorted({row["student_name"] for row in (res.data if res else [])} - {student_name})
    if len(others) + 1 > max_numbers:
        return others
    return []


def log_session_attempt(supabase: Client, room_name: str, session_id: str, student_name: str):
    """이 브라우저(session_id)가 이 학번으로 입장을 시도했다는 기록을 남긴다.

    점유 성공 여부와 무관하게 항상 기록해야
    학번 돌려막기 감지(find_number_switch_abuse)가 정확하게 동작한다.
    """
    if not session_attempts_available() or not session_id:
        return None
    return execute_query(
        supabase.table("session_attempts").insert(
            {"room_name": room_name, "session_id": session_id, "student_name": student_name, "last_seen": get_kst_now_str()}
        ),
        fail_message="접속 시도 기록 실패",
    )


def clear_session_attempts(supabase: Client, room_name: str, student_name: str):
    """특정 학번의 접속 시도 기록(session_attempts)을 초기화합니다.

    학생이 장난으로(또는 실수로) 학번을 여러 번 바꿔 입장이 막혔을 때,
    교사가 해당 학번의 기록을 지워 다시 입장할 수 있게 한다.
    방 전체를 한 번에 초기화하는 기능은 오남용 위험이 있어 제공하지 않는다.
    """
    if not student_name or not session_attempts_available():
        return None
    return execute_query(
        supabase.table("session_attempts").delete().eq("room_name", room_name).eq("student_name", student_name),
        fail_message="접속 시도 기록 초기화 실패",
    )


def fetch_session_attempts_by_room(supabase: Client, room_name: str, window_minutes: int = 10) -> list:
    """이 방의 최근(window_minutes) 접속 시도 기록(session_attempts)을 반환합니다.

    반환 형식: [{"student_name", "session_id", "last_seen"}, ...]
    find_number_switch_abuse와 같은 시간창을 써서, 실제로 차단 대상인 학번만 보여준다.
    """
    if not session_attempts_available():
        return []
    from datetime import timedelta
    from utils import get_kst_now
    cutoff = (get_kst_now() - timedelta(minutes=window_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    res = execute_query(
        supabase.table("session_attempts")
        .select("student_name, session_id, last_seen")
        .eq("room_name", room_name)
        .gte("last_seen", cutoff),
        fail_message="접속 시도 기록 조회 실패",
    )
    return res.data if res and res.data else []


def delete_opinion_message(supabase: Client, message_id: int, deleted_by: str = ""):
    """발언을 삭제(보관)합니다.

    is_deleted 컬럼이 있으면 소프트 삭제(보관소로 이동, 복구 가능)하고,
    없으면 기존처럼 완전 삭제(하드 삭제)합니다.
    """
    if debate_soft_delete_available():
        payload = {"is_deleted": True}
        if debate_deleted_at_column_available():
            payload["deleted_at"] = get_kst_now_str()
        if deleted_by and debate_deleted_by_column_available():
            payload["deleted_by"] = deleted_by
        res = execute_query(
            supabase.table("debate").update(payload).eq("id", message_id),
            fail_message="의견 삭제(보관) 실패",
        )
        return res

    res = execute_query(
        supabase.table("debate").delete().eq("id", message_id),
        fail_message="의견 삭제 실패",
    )
    if res is not None and likes_available():
        execute_query(
            supabase.table("likes").delete().eq("opinion_id", message_id),
            fail_message="연관 공감 데이터 삭제 실패",
        )
    return res


def restore_opinion_message(supabase: Client, message_id: int):
    """보관소에서 발언을 복구합니다 (소프트 삭제 취소)."""
    payload = {"is_deleted": False}
    if debate_deleted_at_column_available():
        payload["deleted_at"] = None
    return execute_query(
        supabase.table("debate").update(payload).eq("id", message_id),
        fail_message="의견 복구 실패",
    )


def fetch_deleted_messages(supabase: Client, room_name: str):
    """방의 삭제(보관)된 발언 목록을 조회합니다."""
    if not debate_soft_delete_available():
        return pd.DataFrame()
    res = execute_query(
        supabase.table("debate").select("*").eq("room_name", room_name).eq("is_deleted", True).order("id", desc=True),
        fail_message="삭제 보관함 조회 실패",
    )
    if not res or not res.data:
        return pd.DataFrame()
    return pd.DataFrame(res.data)


def permanently_delete_message(supabase: Client, message_id: int):
    """보관소에서 발언을 완전히 삭제합니다 (되돌릴 수 없음)."""
    res = execute_query(
        supabase.table("debate").delete().eq("id", message_id),
        fail_message="완전 삭제 실패",
    )
    if res is not None and likes_available():
        execute_query(
            supabase.table("likes").delete().eq("opinion_id", message_id),
            fail_message="연관 공감 데이터 삭제 실패",
        )
    return res


def create_teacher_hint(supabase: Client, payload):
    return execute_query(
        supabase.table("debate").insert(payload),
        fail_message="교사 힌트 전송 실패",
    )


# ==========================================
# [댓글(반박/보충)] 관련 쿼리
# ==========================================

@st.cache_data(ttl=15)
def fetch_comments_for_room(_supabase: Client, room_name: str) -> list:
    """이 방의 삭제되지 않은 모든 댓글을 반환합니다. [{"id", "debate_id", "student_name", ...}, ...]"""
    if not comments_available():
        return []
    res = execute_query(
        _supabase.table("comments")
        .select("*")
        .eq("room_name", room_name)
        .or_("is_deleted.is.null,is_deleted.eq.false")
        .order("id"),
        fail_message="댓글 조회 실패",
    )
    return res.data if res and res.data else []


def create_comment(
    supabase: Client, room_name: str, debate_id: int, student_name: str, comment_type: str, content: str,
    ip_address: str = None, session_id: str = None,
):
    """발언에 댓글(반박/보충)을 작성합니다."""
    if not comments_available():
        return None
    payload = {
        "room_name": room_name,
        "debate_id": debate_id,
        "student_name": student_name,
        "comment_type": comment_type,
        "content": content,
        "timestamp": get_kst_now_str(),
    }
    if ip_address and comments_ip_column_available():
        payload["ip_address"] = ip_address
    if session_id and comments_session_id_column_available():
        payload["session_id"] = session_id
    return execute_query(supabase.table("comments").insert(payload), fail_message="댓글 작성 실패")


def delete_comment(supabase: Client, comment_id: int, deleted_by: str = ""):
    """댓글을 소프트 삭제(보관)합니다."""
    payload = {"is_deleted": True, "deleted_at": get_kst_now_str()}
    if deleted_by:
        payload["deleted_by"] = deleted_by
    return execute_query(
        supabase.table("comments").update(payload).eq("id", comment_id),
        fail_message="댓글 삭제 실패",
    )


def restore_comment(supabase: Client, comment_id: int):
    """보관소에서 댓글을 복구합니다."""
    return execute_query(
        supabase.table("comments").update({"is_deleted": False, "deleted_at": None}).eq("id", comment_id),
        fail_message="댓글 복구 실패",
    )


def fetch_deleted_comments(supabase: Client, room_name: str) -> list:
    """방의 삭제(보관)된 댓글 목록을 조회합니다."""
    if not comments_available():
        return []
    res = execute_query(
        supabase.table("comments").select("*").eq("room_name", room_name).eq("is_deleted", True).order("deleted_at", desc=True),
        fail_message="삭제된 댓글 조회 실패",
    )
    return res.data if res and res.data else []


def permanently_delete_comment(supabase: Client, comment_id: int):
    """보관소에서 댓글을 완전히 삭제합니다 (되돌릴 수 없음)."""
    res = execute_query(
        supabase.table("comments").delete().eq("id", comment_id),
        fail_message="댓글 완전 삭제 실패",
    )
    if res is not None and comment_likes_available():
        execute_query(
            supabase.table("comment_likes").delete().eq("comment_id", comment_id),
            fail_message="연관 댓글 공감 삭제 실패",
        )
    return res


@st.cache_data(ttl=15)
def fetch_comment_likes_for_room(_supabase: Client, room_name: str) -> list:
    """방의 모든 댓글 공감 데이터를 반환합니다: [{"comment_id": ..., "student_name": ...}, ...]"""
    if not comment_likes_available():
        return []
    res = execute_query(
        _supabase.table("comment_likes").select("comment_id, student_name").eq("room_name", room_name),
        fail_message="댓글 공감 조회 실패",
    )
    return res.data if res and res.data else []


def toggle_comment_like(supabase: Client, comment_id: int, room_name: str, student_name: str) -> bool:
    """댓글 공감 토글. 이미 공감 시 취소(False 반환), 없으면 추가(True 반환)."""
    existing = execute_query(
        supabase.table("comment_likes").select("id").eq("comment_id", comment_id).eq("student_name", student_name),
        fail_message="댓글 공감 확인 실패",
    )
    if existing and existing.data:
        execute_query(
            supabase.table("comment_likes").delete().eq("comment_id", comment_id).eq("student_name", student_name),
            fail_message="댓글 공감 취소 실패",
        )
        return False
    execute_query(
        supabase.table("comment_likes").insert({"comment_id": comment_id, "room_name": room_name, "student_name": student_name}),
        fail_message="댓글 공감 추가 실패",
    )
    return True



def room_soft_destroy_available() -> bool:
    """방 삭제를 소프트 삭제(숨김 + 발언 보관)로 처리할 수 있는지 여부."""
    return topic_is_hidden_available() and debate_soft_delete_available()


def destroy_room_data(supabase: Client, room_name: str, deleted_by: str = ""):
    """방을 삭제합니다.

    소프트 삭제가 가능하면(topic.is_hidden + debate.is_deleted 컬럼 존재)
    실제로는 아무것도 영구 삭제하지 않고, 방을 숨김 처리하고 발언을
    보관소로 이동시킨다 — 필요하면 "방 공개/숨김 관리"에서 다시 보이게
    하고, 삭제 보관소에서 발언을 복구할 수 있다.
    소프트 삭제가 불가능한 구버전 스키마에서는 기존처럼 완전 삭제한다.
    """
    if room_soft_destroy_available():
        hide_res = toggle_room_visibility(supabase, room_name, True)
        if hide_res is None:
            return None
        messages = execute_query(
            supabase.table("debate")
            .select("id")
            .eq("room_name", room_name)
            .or_("is_deleted.is.null,is_deleted.eq.false"),
            fail_message="방 발언 목록 조회 실패",
        )
        for row in (messages.data if messages and messages.data else []):
            delete_opinion_message(supabase, row["id"], deleted_by=deleted_by)
        fetch_room_names.clear()
        return {"soft_deleted": True}

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
    fetch_room_names.clear()
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

@st.cache_data(ttl=10)
def fetch_opinion_change(_supabase: Client, room_name: str, student_name: str):
    if not opinion_changes_available():
        return None
    res = execute_query(
        _supabase.table("opinion_changes")
        .select("*")
        .eq("room_name", room_name)
        .eq("student_name", student_name)
        .limit(1),
        fail_message="생각 변화 조회 실패",
    )
    if not res or not res.data:
        return None
    return res.data[0]


def upsert_pre_opinion(supabase: Client, room_name: str, student_name: str, pre_opinion: str, initial_stance: str = None, ip_address: str = None, session_id: str = None):
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
    if res is not None:
        fetch_opinion_change.clear()
    # IP/세션ID는 별도 업데이트 — 컬럼 미존재 시 실패해도 메인 저장에 영향 없음
    if ip_address and res is not None:
        try:
            supabase.table("opinion_changes").update({"ip_address": ip_address}).eq("room_name", room_name).eq("student_name", student_name).execute()
        except Exception:
            pass
    if session_id and res is not None:
        try:
            supabase.table("opinion_changes").update({"session_id": session_id}).eq("room_name", room_name).eq("student_name", student_name).execute()
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
        res = execute_query(
            supabase.table("opinion_changes").update(payload).eq("room_name", room_name).eq("student_name", student_name),
            fail_message="토론 후 생각 저장 실패",
        )
    else:
        res = execute_query(
            supabase.table("opinion_changes").insert({"room_name": room_name, "student_name": student_name, **payload}),
            fail_message="토론 후 생각 저장 실패",
        )
    if res is not None:
        fetch_opinion_change.clear()
    return res


@st.cache_data(ttl=15)
def fetch_all_opinion_changes(_supabase: Client, room_name: str):
    if not opinion_changes_available():
        return pd.DataFrame()
    res = execute_query(
        _supabase.table("opinion_changes")
        .select("*")
        .eq("room_name", room_name)
        .order("student_name"),
        fail_message="학생별 생각 변화 조회 실패",
    )
    if not res or not res.data:
        return pd.DataFrame()
    return pd.DataFrame(res.data)


def save_opinion_feedback(supabase: Client, room_name: str, student_name: str, ai_feedback: str):
    if not ai_feedback_available():
        return None
    return execute_query(
        supabase.table("opinion_changes")
        .update({"ai_feedback": ai_feedback})
        .eq("room_name", room_name)
        .eq("student_name", student_name),
        fail_message="AI 피드백 저장 실패",
    )


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

@st.cache_data(ttl=20)
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

    teacher_select_cols = ["id", "teacher_id", "teacher_pw", "is_approved", "approved_at", "requested_at"]
    if teacher_is_admin_column_available():
        teacher_select_cols.append("is_admin")
    if teacher_judge_column_available():
        teacher_select_cols.append("is_judge")
    if teacher_active_column_available():
        teacher_select_cols.append("is_active")
    teacher_select = ", ".join(teacher_select_cols)

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


def fetch_judge_account(supabase: Client):
    """미리 만들어둔 심사용 계정을 조회합니다 (is_judge=true인 첫 번째 승인된 계정)."""
    if not (teacher_judge_column_available() and teacher_active_column_available()):
        return None
    res = execute_query(
        supabase.table("teacher_accounts")
        .select("id, teacher_id, is_approved, is_active")
        .eq("is_judge", True)
        .eq("is_approved", True)
        .limit(1),
        fail_message="심사용 계정 조회 실패",
    )
    return res.data[0] if res and res.data else None


def fetch_judge_accounts(supabase: Client) -> list:
    """관리자 화면에 표시할 심사용 계정 전체 목록을 조회합니다."""
    if not teacher_judge_column_available():
        return []
    res = execute_query(
        supabase.table("teacher_accounts")
        .select("id, teacher_id, is_active")
        .eq("is_judge", True)
        .order("id"),
        fail_message="심사용 계정 목록 조회 실패",
    )
    return res.data if res and res.data else []


def set_teacher_active(supabase: Client, account_id: int, active: bool):
    return execute_query(
        supabase.table("teacher_accounts").update({"is_active": active}).eq("id", account_id),
        fail_message="계정 활성화 상태 변경 실패",
    )


# ==========================================
# [공감(likes)] 관련 쿼리
# ==========================================

@st.cache_data(ttl=20)
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


# ==========================================
# [AI 유해 발언 플래깅(content_flags)] 관련 쿼리
# ==========================================

def fetch_flaggable_content(supabase: Client, room_name: str) -> list:
    """AI 유해 발언 검수 대상 전체 조회 (학생 발언 + 답글).

    반환: [{"source_table": "debate"|"comments", "source_id": int,
            "student_name": str, "content": str}, ...]
    """
    items = []
    debate_res = execute_query(
        supabase.table("debate")
        .select("id, content, student_name")
        .eq("room_name", room_name)
        .not_.ilike("student_name", "%선생님%")
        .or_("is_deleted.is.null,is_deleted.eq.false"),
        fail_message="유해 발언 검수용 발언 조회 실패",
    )
    for row in (debate_res.data if debate_res and debate_res.data else []):
        items.append({"source_table": "debate", "source_id": row["id"], "student_name": row.get("student_name", ""), "content": row.get("content", "")})

    if comments_available():
        for c in fetch_comments_for_room(supabase, room_name):
            items.append({"source_table": "comments", "source_id": c["id"], "student_name": c.get("student_name", ""), "content": c.get("content", "")})
    return items


def fetch_flagged_source_keys(supabase: Client, room_name: str) -> set:
    """이미 플래그된(검수 이력이 있는) (source_table, source_id) 집합을 반환합니다 (중복 재플래그 방지)."""
    if not content_flags_available():
        return set()
    res = execute_query(
        supabase.table("content_flags").select("source_table, source_id").eq("room_name", room_name),
        fail_message="기존 플래그 조회 실패",
    )
    return {(row["source_table"], row["source_id"]) for row in (res.data if res and res.data else [])}


def create_content_flag(supabase: Client, room_name: str, source_table: str, source_id: int, student_name: str, content: str, reason: str):
    if not content_flags_available():
        return None
    return execute_query(
        supabase.table("content_flags").insert({
            "room_name": room_name, "source_table": source_table, "source_id": source_id,
            "student_name": student_name, "content": content, "reason": reason,
            "created_at": get_kst_now_str(), "is_reviewed": False,
        }),
        fail_message="유해 발언 플래그 저장 실패",
    )


@st.cache_data(ttl=15)
def fetch_unreviewed_flags_for_room(_supabase: Client, room_name: str) -> list:
    if not content_flags_available():
        return []
    res = execute_query(
        _supabase.table("content_flags").select("*").eq("room_name", room_name).eq("is_reviewed", False).order("id"),
        fail_message="검토 대기 플래그 조회 실패",
    )
    return res.data if res and res.data else []


def mark_flag_reviewed(supabase: Client, flag_id: int, reviewed_by: str = ""):
    return execute_query(
        supabase.table("content_flags").update({
            "is_reviewed": True, "reviewed_by": reviewed_by, "reviewed_at": get_kst_now_str(),
        }).eq("id", flag_id),
        fail_message="플래그 검토 처리 실패",
    )


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
