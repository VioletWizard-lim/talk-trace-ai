from teacher_session import (
    COOKIE_NAME,
    SESSION_SECONDS,
    LoginLimiter,
    _cookie_script,
    new_token,
    token_expired,
    token_key,
)


def test_new_token_is_random_and_carries_expiry():
    a = new_token(now=1_000)
    b = new_token(now=1_000)
    assert a != b
    assert a.split(".", 1)[0] == str(1_000 + SESSION_SECONDS)


def test_token_expiry():
    token = new_token(now=1_000)
    assert not token_expired(token, now=1_000)
    assert not token_expired(token, now=1_000 + SESSION_SECONDS - 1)
    assert token_expired(token, now=1_000 + SESSION_SECONDS)


def test_malformed_tokens_are_expired():
    for bad in ["", "abc", "123", "123.short", "x1.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", None]:
        assert token_expired(bad, now=0)


def test_token_key_hides_token_and_binds_expiry():
    token = new_token(now=1_000)
    key = token_key(token)
    assert token not in key
    assert len(key) == 64
    # 만료 시각을 늘려 보면 지문이 달라져 DB에서 찾을 수 없다
    expires, rest = token.split(".", 1)
    forged = f"{int(expires) + 10**6}.{rest}"
    assert token_key(forged) != key


def test_old_url_sid_never_matches_new_keys():
    sid = "123e4567-e89b-12d3-a456-426614174000"
    assert token_expired(sid, now=0)
    assert token_key(sid) != sid


def test_login_limiter_blocks_after_max_fails_and_recovers():
    limiter = LoginLimiter(max_fails=3, window_seconds=60)
    for i in range(3):
        assert not limiter.blocked("Teacher", now=100 + i)
        limiter.record_fail("Teacher", now=100 + i)
    assert limiter.blocked("teacher", now=103)  # 대소문자 구분 없이
    assert not limiter.blocked("other", now=103)
    assert not limiter.blocked("teacher", now=100 + 2 + 60)  # 창이 지나면 풀림


def test_login_limiter_reset():
    limiter = LoginLimiter(max_fails=1, window_seconds=60)
    limiter.record_fail("t", now=0)
    assert limiter.blocked("t", now=1)
    limiter.reset("t")
    assert not limiter.blocked("t", now=1)


def test_cookie_script_sets_and_clears():
    token = new_token(now=1_000)
    set_js = _cookie_script(token)
    assert f"{COOKIE_NAME}={token}" in set_js
    assert f"Max-Age={SESSION_SECONDS}" in set_js
    assert "SameSite=Strict" in set_js
    clear_js = _cookie_script(None)
    assert f"{COOKIE_NAME}=; Max-Age=0" in clear_js
