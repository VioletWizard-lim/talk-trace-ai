"""욕설/비속어 즉시 차단 필터.

제출 속도에 영향을 주지 않도록 순수 문자열 매칭만 수행한다(외부 API 호출 없음).
AI 기반 유해 발언 탐지는 별도의 비동기 배치 작업으로 처리할 예정이며,
여기서는 명백한 욕설/비속어만 즉시 차단하는 1차 방어선 역할을 한다.
"""

import re


# 일반적인 한국어 욕설/비속어 세트 (초성 축약형·변형 포함)
FORBIDDEN_WORDS = [
    "시발", "씨발", "씨발놈", "씨발년", "시발놈", "시발년", "ㅅㅂ", "ㅆㅂ",
    "개새끼", "개색기", "개색끼", "새끼", "개새기",
    "병신", "병신새끼", "ㅂㅅ",
    "지랄", "지럴", "ㅈㄹ",
    "미친놈", "미친년", "미친새끼",
    "존나", "졸라", "ㅈㄴ",
    "닥쳐", "닥치라고",
    "꺼져", "꺼지라고",
    "쌍놈", "쌍년",
    "개년", "개놈", "개자식",
    "좆같", "좆까", "좆나",
    "육시랄", "니미", "느금", "느그", "니애미", "니에미",
    "애미없", "애비없", "애미뒤진", "패드립",
    "창녀", "걸레같", "보지", "자지", "따먹",
    "죽여버", "뒤져버", "뒤질래", "죽을래",
    "fuck", "fucking", "bitch", "asshole", "shit",
]

# 흔한 우회 시도(자모 사이 공백/특수문자 삽입) 대응을 위한 정규화
_NORMALIZE_PATTERN = re.compile(r"[\s.,!?~\-_*^]+")


def _normalize(text):
    return _NORMALIZE_PATTERN.sub("", str(text or "")).lower()


def find_forbidden_word(text):
    """text에 금지어가 포함되어 있으면 매칭된 단어를, 없으면 None을 반환합니다."""
    normalized = _normalize(text)
    if not normalized:
        return None
    for word in FORBIDDEN_WORDS:
        if word in normalized:
            return word
    return None


def contains_forbidden_speech(text):
    """text에 욕설/비속어가 포함되어 있는지 여부만 반환합니다."""
    return find_forbidden_word(text) is not None
