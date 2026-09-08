from services.ai import parse_moderation_flags


def test_parse_moderation_flags_key_with_colon():
    # source_table:source_id 형태(예: "comments:37")처럼 key 자체에 콜론이
    # 들어있는 실제 포맷을 정확히 파싱해야 한다. 과거 정규식은 콜론을 key에서
    # 제외해버려 "comments"만 캡처되고 실제 key 집합과 매칭되지 않아, AI가
    # 문제 발언을 정확히 찾아내도 결과가 전부 버려지는 문제가 있었다.
    response = "key=comments:37: 외모비하 조롱\nkey=debate:5: 욕설 우회"
    keys = {"comments:37", "debate:5"}
    result = parse_moderation_flags(response, keys)
    assert result == {"comments:37": "외모비하 조롱", "debate:5": "욕설 우회"}


def test_parse_moderation_flags_none():
    assert parse_moderation_flags("NONE", {"comments:1"}) == {}
    assert parse_moderation_flags("", {"comments:1"}) == {}


def test_parse_moderation_flags_ignores_unknown_keys():
    response = "key=comments:99: 모욕"
    result = parse_moderation_flags(response, {"comments:37"})
    assert result == {}
