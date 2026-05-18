from datetime import timezone
from utils import get_kst_now, compact_ai_report_output


def test_get_kst_now_is_aware():
    dt = get_kst_now()
    assert dt.tzinfo is not None
    assert dt.utcoffset().seconds == 9 * 3600


def test_compact_ai_report_output_empty():
    assert compact_ai_report_output("") == ""
    assert compact_ai_report_output(None) == ""


def test_compact_ai_report_output_no_double_newline():
    text = "핵심요약 1: A 핵심요약 2: B 핵심요약 3: C 베스트 학생: D 선정 이유: E"
    result = compact_ai_report_output(text)
    assert "\n\n" not in result
    lines = result.splitlines()
    assert len(lines) <= 5


def test_compact_ai_report_output_strips_headers():
    text = "# 제목\n핵심요약 1: 내용\n핵심요약 2: 내용2"
    result = compact_ai_report_output(text)
    assert "# 제목" not in result
