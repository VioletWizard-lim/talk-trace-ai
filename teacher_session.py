"""교사 로그인 유지(새로고침해도 로그인 상태 유지)와 로그인 시도 제한.

예전에는 주소창의 sid(학생 구분용 값)를 그대로 교사 로그인 열쇠로 썼다.
그래서 교사 화면 주소가 화면 공유·링크 전달·방문 기록으로 새면 그 주소를 연
사람이 교사(관리자)가 되었고, 학생이 미리 정한 sid 링크로 교사가 로그인하게
만들면 학생도 같은 주소로 교사가 될 수 있었다.

지금은 이렇게 한다.
- 로그인에 성공할 때마다 서버가 새 무작위 열쇠를 만든다(학생이 정할 수 없음).
- 열쇠는 주소창이 아니라 이 브라우저의 쿠키에만 둔다.
- DB(teacher_sessions.session_id)에는 열쇠 자체가 아니라 SHA-256 지문만 저장한다.
- 열쇠 앞부분에 만료 시각을 넣는다. 지문이 열쇠 전체로 만들어지므로 만료 시각을
  고치면 DB에서 찾을 수 없다. (표에 새 칸을 만들지 않아도 됨)
- 로그인을 되살릴 때 관리자 여부는 저장된 값이 아니라 교사 계정에서 다시 읽는다.
"""

import hashlib
import json
import secrets
import threading
import time

import streamlit as st

COOKIE_NAME = "tt_teacher"
# 로그인 유지 시간: 하루 수업 동안은 새로고침해도 유지되고, 다음 날에는 다시 로그인한다.
SESSION_SECONDS = 12 * 60 * 60

# 같은 교사 ID로 5분 안에 5번 틀리면 5분 동안 로그인을 막는다.
LOGIN_MAX_FAILS = 5
LOGIN_WINDOW_SECONDS = 5 * 60

_STATE_TOKEN = "teacher_token"
_STATE_COOKIE_ACTION = "_teacher_cookie_action"
# 쿠키를 쓰는 스크립트를 몇 번의 화면 갱신 동안 다시 내보낼지.
# 같은 실행 안에서 st.rerun()이 일어나면 브라우저가 스크립트를 실행하기 전에
# 화면이 바뀔 수 있어서, 한 번 더 내보낸다(같은 값을 두 번 써도 문제없음).
_COOKIE_ACTION_RUNS = 2


# ──────────────────────────────────────────────
# 열쇠 만들기·확인 (화면과 무관한 순수 함수, 단위 테스트 대상)
# ──────────────────────────────────────────────

def new_token(now: float | None = None) -> str:
    """'만료시각(초).무작위값' 모양의 새 열쇠."""
    now = time.time() if now is None else now
    return f"{int(now) + SESSION_SECONDS}.{secrets.token_urlsafe(32)}"


def token_key(token: str) -> str:
    """DB에 저장·조회할 열쇠 지문."""
    return hashlib.sha256(f"teacher-session:{token}".encode()).hexdigest()


def token_expired(token: str, now: float | None = None) -> bool:
    """만료됐거나 모양이 이상한 열쇠면 True."""
    now = time.time() if now is None else now
    expires, sep, rest = str(token or "").partition(".")
    if not sep or not expires.isdigit() or len(rest) < 32:
        return True
    return int(expires) <= now


class LoginLimiter:
    """교사 ID별 로그인 실패 횟수(서버 메모리). 서버가 다시 시작되면 초기화된다."""

    def __init__(self, max_fails: int = LOGIN_MAX_FAILS, window_seconds: int = LOGIN_WINDOW_SECONDS):
        self.max_fails = max_fails
        self.window_seconds = window_seconds
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(teacher_id: str) -> str:
        return str(teacher_id or "").strip().lower()

    def _recent(self, key: str, now: float) -> list[float]:
        recent = [t for t in self._fails.get(key, []) if now - t < self.window_seconds]
        if recent:
            self._fails[key] = recent
        else:
            self._fails.pop(key, None)
        return recent

    def blocked(self, teacher_id: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self._lock:
            return len(self._recent(self._key(teacher_id), now)) >= self.max_fails

    def record_fail(self, teacher_id: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        key = self._key(teacher_id)
        with self._lock:
            self._recent(key, now)
            self._fails.setdefault(key, []).append(now)

    def reset(self, teacher_id: str) -> None:
        with self._lock:
            self._fails.pop(self._key(teacher_id), None)


@st.cache_resource
def login_limiter() -> LoginLimiter:
    """모든 접속(세션)이 함께 쓰는 로그인 실패 기록."""
    return LoginLimiter()


# ──────────────────────────────────────────────
# 쿠키 읽기·쓰기
# ──────────────────────────────────────────────

def read_cookie_token() -> str:
    """이 브라우저가 처음 접속할 때 보낸 교사 로그인 쿠키(없으면 빈 글자)."""
    try:
        return str(st.context.cookies.get(COOKIE_NAME) or "")
    except Exception:
        return ""


def _cookie_script(token: str | None) -> str:
    if token:
        value = json.dumps(f"{COOKIE_NAME}={token}; Max-Age={SESSION_SECONDS}; Path=/; SameSite=Strict")
    else:
        value = json.dumps(f"{COOKIE_NAME}=; Max-Age=0; Path=/; SameSite=Strict")
    return f"""
        <script>
        (function() {{
            const win = window.parent;
            const secure = win.location.protocol === 'https:' ? '; Secure' : '';
            win.document.cookie = {value} + secure;
        }})();
        </script>
    """


def _queue_cookie(token: str | None) -> None:
    st.session_state[_STATE_COOKIE_ACTION] = {"token": token, "runs": _COOKIE_ACTION_RUNS}


def flush_cookie_action() -> None:
    """미뤄 둔 쿠키 쓰기·지우기를 화면에 내보낸다. app.py가 매 실행 맨 앞에서 부른다."""
    action = st.session_state.get(_STATE_COOKIE_ACTION)
    if not action:
        return
    import streamlit.components.v1 as components

    components.html(_cookie_script(action.get("token")), height=0)
    action["runs"] = int(action.get("runs", 1)) - 1
    if action["runs"] <= 0:
        st.session_state.pop(_STATE_COOKIE_ACTION, None)


# ──────────────────────────────────────────────
# 로그인·복원·로그아웃
# ──────────────────────────────────────────────

def start_teacher_session(supabase, teacher_id: str, is_admin: bool) -> None:
    """로그인 성공 직후: 새 열쇠를 만들어 DB에 지문을 저장하고 쿠키를 쓴다."""
    from db import delete_teacher_session, save_teacher_session

    old = st.session_state.get(_STATE_TOKEN)
    if old:
        delete_teacher_session(supabase, token_key(old))
    token = new_token()
    save_teacher_session(supabase, token_key(token), teacher_id, is_admin)
    st.session_state[_STATE_TOKEN] = token
    _queue_cookie(token)


def end_teacher_session(supabase) -> None:
    """로그아웃: DB의 지문을 지우고 쿠키도 지운다(화면 상태 초기화는 부르는 쪽에서)."""
    from db import delete_teacher_session

    token = st.session_state.pop(_STATE_TOKEN, None) or read_cookie_token()
    if token:
        delete_teacher_session(supabase, token_key(token))
    _queue_cookie(None)


def restore_teacher_session(supabase, is_account_usable) -> dict | None:
    """쿠키의 열쇠로 교사 로그인을 되살린다. 되살리면 교사 계정 정보를, 아니면 None.

    is_account_usable(account) -> bool: 승인·활성 상태 확인 (app.py가 넘김)
    """
    from db import delete_teacher_session, fetch_teacher_account, fetch_teacher_session

    token = read_cookie_token()
    if not token:
        return None
    key = token_key(token)
    if token_expired(token):
        delete_teacher_session(supabase, key)
        _queue_cookie(None)
        return None
    saved = fetch_teacher_session(supabase, key)
    if not saved:
        _queue_cookie(None)
        return None
    account = fetch_teacher_account(supabase, saved.get("teacher_id", ""))
    if not isinstance(account, dict) or account.get("_query_failed"):
        # DB 조회가 잠깐 실패한 것일 수 있으니 열쇠는 지우지 않는다(다음 접속 때 다시 시도)
        return None
    if not is_account_usable(account):
        delete_teacher_session(supabase, key)
        _queue_cookie(None)
        return None
    st.session_state[_STATE_TOKEN] = token
    return account
