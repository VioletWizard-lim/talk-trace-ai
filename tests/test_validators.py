import pytest
from validators import (
    ValidationError,
    validate_opinion_content,
    validate_room_name,
    validate_student_name,
    validate_entry_code,
    validate_teacher_credential,
    normalize_user_text,
    normalize_room_name,
    mask_ip_for_teacher,
)


# ── validate_opinion_content ──────────────────────────────────────

def test_opinion_empty():
    ok, _, code, _ = validate_opinion_content("")
    assert not ok
    assert code == ValidationError.EMPTY


def test_opinion_valid():
    ok, safe, _, _ = validate_opinion_content("인공지능은 교육에 도움이 됩니다.")
    assert ok
    assert safe == "인공지능은 교육에 도움이 됩니다."


def test_opinion_special_chars_allowed():
    ok, _, _, _ = validate_opinion_content("좋아요! 이 의견 → 매우 중요합니다… 🎉")
    assert ok


def test_opinion_too_long():
    ok, _, code, _ = validate_opinion_content("a" * 701)
    assert not ok
    assert code == ValidationError.TOO_LONG


# ── validate_room_name ────────────────────────────────────────────

def test_room_name_valid():
    ok, safe, _, _ = validate_room_name("1학년 3반")
    assert ok
    assert safe == "1학년 3반"


def test_room_name_empty():
    ok, _, code, _ = validate_room_name("")
    assert not ok
    assert code == ValidationError.EMPTY


def test_room_name_forbidden():
    ok, _, code, _ = validate_room_name("관리자방")
    assert not ok
    assert code == ValidationError.FORBIDDEN


def test_room_name_collapse_spaces():
    ok, safe, _, _ = validate_room_name("1학년   3반")
    assert ok
    assert safe == "1학년 3반"


# ── validate_student_name ─────────────────────────────────────────

def test_student_name_valid():
    ok, safe, _, _ = validate_student_name("홍길동")
    assert ok
    assert safe == "홍길동"


def test_student_name_forbidden_admin():
    ok, _, code, _ = validate_student_name("admin")
    assert not ok
    assert code == ValidationError.FORBIDDEN


# ── validate_entry_code ───────────────────────────────────────────

def test_entry_code_empty_allowed():
    ok, safe, _, _ = validate_entry_code("")
    assert ok
    assert safe == ""


def test_entry_code_valid():
    ok, safe, _, _ = validate_entry_code("secret123!")
    assert ok
    assert safe == "secret123!"


# ── validate_teacher_credential ───────────────────────────────────

def test_credential_valid():
    ok, safe, _, _ = validate_teacher_credential("teacher01", field_name="교사 ID")
    assert ok
    assert safe == "teacher01"


def test_credential_empty():
    ok, _, code, _ = validate_teacher_credential("", field_name="교사 ID")
    assert not ok
    assert code == ValidationError.EMPTY


# ── normalize helpers ─────────────────────────────────────────────

def test_normalize_user_text_strips():
    assert normalize_user_text("  hello  ") == "hello"


def test_normalize_user_text_truncates():
    assert normalize_user_text("abc", max_len=2) == "ab"


def test_normalize_room_name_collapses_whitespace():
    assert normalize_room_name("a   b") == "a b"


# ── mask_ip_for_teacher ───────────────────────────────────────────

def test_mask_ipv4():
    assert mask_ip_for_teacher("1.2.3.4") == "1.XXX.XXX.4"


def test_mask_ipv6():
    result = mask_ip_for_teacher("2001:db8:85a3:0:0:8a2e:370:7334")
    assert "XXXX" in result


def test_mask_empty():
    assert mask_ip_for_teacher("") == ""
