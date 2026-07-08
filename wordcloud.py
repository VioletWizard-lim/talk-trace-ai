import html
import math
import re
from collections import Counter


def build_word_frequencies(text_series):
    tokens = []
    stopwords = {
        "그리고", "하지만", "그래서", "정말", "제가", "저는", "너무", "이번", "지금",
        "그냥", "대한", "대한해", "같은", "합니다", "입니다", "있는", "없는", "수업",
        "토론", "토의", "의견", "생각", "내용", "때문", "하면", "하면요", "입니다요", "있다", "않으면", "많은",
        "것을", "것은", "것이", "것도", "것만", "것과", "것으로", "것에", "것이다", "것같다",
        "이미", "이제", "이런", "이렇게", "이것", "이것은", "이것이", "이것을",
        "때문입니다", "때문에", "때문이다",
        "있습니다", "없습니다", "합니다만", "했습니다", "됩니다", "되었습니다",
        "라고", "라는", "라서", "라면서", "라도",
        "그것", "그것은", "그것이", "그것을", "그런", "그렇게", "그래도", "그러나", "그러면", "그러므로",
        "모든", "어떤", "어떻게", "왜냐하면", "따라서", "또한", "또는", "하지만", "그리고",
        "통해", "통하여", "위해", "위하여", "대해", "대하여",
        "더욱", "매우", "아주", "조금", "많이", "항상", "절대", "결국", "사실",
        # 대명사·일반 명사
        "우리", "사람", "자신", "누구", "여기", "거기", "저기",
        # 조동사·존재사 활용형
        "있어", "있기", "있을", "없어", "없기", "됩니다", "된다", "한다",
        # 잘린 동사 어간
        "만들", "나타", "보여", "하기",
        # 부사
        "서로", "수도", "바로", "함께", "계속", "오히려", "빠르게", "쉽게", "단순히",
        # 동사 어간 단독 노출 방지
        "공유하", "막는", "배우고", "나타나", "이루어",
        # 기능어·조사 단독
        "들어", "그렇기", "둘째", "셋째", "넷째", "떠난", "일으킬",
        # 동사 활용형 잔재
        "있습니", "없습니", "보여줄", "무너뜨리고", "금지해야",
        # 추가 불용어 (워드클라우드 스크린샷 기반)
        "굳이", "한다고", "없다고", "있다고", "생각한", "달라질까", "그러기",
        "하지", "해야", "해서", "하는", "하는데", "하는지", "제한하",
        "경우", "정도", "방식", "측면", "부분", "상황", "문제", "필요",
        # 접속사·부사·감탄사
        "비록", "아니라", "아니", "동조", "다만", "단지", "물론", "오직",
        "다시", "여전히", "결코", "마치", "더욱더", "하물며",
        # 지시어·대명사 보완
        "이는", "이를", "이에", "여기서", "거기서", "저기서", "이곳", "저곳",
        # 원인·이유 표현
        "인해", "인하여", "덕분", "탓에",
        # 동사 활용형 잔재 추가
        "되었", "됐", "됩", "했", "보면", "생길", "일어",
        # 관형사 및 형용사 어미 잔재
        "원천적인", "근본적인", "전반적인", "다양한", "여러", "이런",
        # 글자 수 의미 없는 조각
        "수있", "수없", "되어야", "해야지",
        # 추가 불용어 (2차 스크린샷 기반 — 짧아서 조사 스트리핑을 통과하는 잔재)
        "쓰는", "바람직", "사용하되", "생각해보면서", "모든것", "같다", "맡기고",
        "전부", "어느", "하는것", "쓸때", "있을것", "말고", "사용했는지",
        "좋다고", "결론적", "않고", "글의", "나는", "내가", "그대", "글을",
        "만든", "직접", "가장", "없이",
        # 추가 불용어 (3차 스크린샷 기반 — "-ㅂ니다"류 잔재, 짧은 활용형 조각)
        "생각합니", "사라집니", "도구입니", "다듬고", "있어야",
    }
    particle_suffixes = [
        "에게서", "으로는", "이라고", "라면", "처럼", "까지는", "으로도", "에서", "에게", "으로", "로써",
        "로서", "보다", "까지", "부터", "만큼", "이나", "라도", "이며", "이고", "에서", "으로", "이라",
        "라고", "의", "와", "과", "을", "를", "이", "가", "은", "는", "에", "도", "만", "로", "랑", "나",
        # 목적격·주격 추가
        "에게도", "에서도", "로도",
        # 관형형 어미·복수 접미사
        "할", "한", "된", "들",
        # 동사 어간 어미 (공유하→공유, 개발하→개발)
        "하",
        # 서술격 조사 (규제다→규제)
        "다",
    ]
    # 동사 활용형 어미
    verb_endings = (
        "하고", "하면", "하며", "하여", "하기", "한다", "하는", "하게", "하지",
        "해서", "해야", "해도", "하여서", "하여도", "하는데", "하는지",
        "되고", "되며", "되어", "되기", "된다", "되는", "되게", "되어서",
        "이고", "이며", "이기", "인다", "이는",
        "한다고", "해야한다고", "해야한다",
        "습니다", "습니까", "ㅂ니다", "ㅂ니까", "니다", "니까",
        "발견하고", "공유하면", "배우고", "생각하기", "부여한다",
        # 추가 동사 활용 패턴
        "없다고", "있다고", "한다면", "된다면", "되는데", "하는것",
        "해야만", "해야지", "해야할",
        # 복합 어미 (개선해나가야 → 개선, 막을려면 → 막)
        "해나가야", "해나가고", "해나가는", "해나가며",
        "을려면", "를려면", "려면", "으려면",
        "되는것", "하는것이", "할수있", "할수없",
        # 명사형 어미
        "망입니", "망입니다", "이라는것", "라는것",
    )

    def normalize_token(token):
        cleaned = re.sub(r"^[^\w가-힣]+|[^\w가-힣]+$", "", token)
        if len(cleaned) < 2:
            return ""
        normalized = cleaned
        # 최대 3회 반복 strip — "제한하는" → "제한하" → "제한"
        for _ in range(3):
            prev = normalized
            for suffix in particle_suffixes:
                if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
                    normalized = normalized[: -len(suffix)]
                    break
            for ending in verb_endings:
                if normalized.endswith(ending) and len(normalized) > len(ending) + 1:
                    normalized = normalized[: -len(ending)]
                    break
            if normalized == prev:
                break
        # 특수문자 잔재 제거
        normalized = re.sub(r"[^\w가-힣]", "", normalized)
        if len(normalized) < 2:
            return ""
        return normalized

    for content in text_series.fillna("").astype(str):
        for token in content.replace("\n", " ").split():
            cleaned = normalize_token(token)
            if len(cleaned) < 2:
                continue
            if cleaned in stopwords:
                continue
            tokens.append(cleaned)
    return Counter(tokens)


def build_circular_wordcloud_html(frequencies, max_words=40, width=760, height=520, palette=None):
    if not frequencies:
        return ""
    sorted_words = sorted(frequencies.items(), key=lambda item: (-item[1], item[0]))[:max_words]
    max_count = sorted_words[0][1]
    min_count = sorted_words[-1][1]
    if palette is None:
        palette = ["#00695C", "#0077B6", "#0B3D91", "#1F8EFA", "#A3CFE2"]
    cx, cy = width / 2, height / 2
    placed_rects = []
    svg_text_nodes = []

    def estimate_text_units(word):
        units = 0.0
        for ch in word:
            code = ord(ch)
            if 0xAC00 <= code <= 0xD7A3: units += 1.0
            elif 0x3130 <= code <= 0x318F: units += 0.95
            elif 0x4E00 <= code <= 0x9FFF: units += 1.0
            elif ch.isascii() and (ch.isalpha() or ch.isdigit()): units += 0.62
            else: units += 0.75
        return max(units, 1.0)

    def overlaps(rect):
        x, y, w, h = rect
        padding = 2
        for ox, oy, ow, oh in placed_rects:
            if not (x + w + padding < ox or ox + ow + padding < x or y + h + padding < oy or oy + oh + padding < y):
                return True
        return False

    def is_inside_canvas(x, y, w, h):
        margin = 10
        return x >= margin and y >= margin and (x + w) <= (width - margin) and (y + h) <= (height - margin)

    for index, (word, count) in enumerate(sorted_words):
        if max_count == min_count:
            font_size = 28
        else:
            ratio = (count - min_count) / (max_count - min_count)
            eased_ratio = ratio ** 0.85
            font_size = int(18 + eased_ratio * 86)
        font_size = min(font_size, 140)
        color = palette[index % len(palette)]
        text_units = estimate_text_units(word)
        text_width = max(32, font_size * (text_units + 0.62))
        text_height = max(24, font_size * 1.22)
        placed = False
        for step in range(1, 3200):
            angle = step * 0.4 + index * 0.18
            spiral_radius = 2 + step * 0.42
            x = cx + spiral_radius * math.cos(angle) - text_width / 2
            y = cy + spiral_radius * math.sin(angle) - text_height / 2
            rect = (x, y, text_width, text_height)
            if not is_inside_canvas(x, y, text_width, text_height):
                continue
            if overlaps(rect):
                continue
            placed_rects.append(rect)
            safe_word = html.escape(word)
            tx, ty = x + 1.5, y + text_height * 0.84
            svg_text_nodes.append(
                f"<text x='{tx:.1f}' y='{ty:.1f}' fill='{color}' font-size='{font_size}' "
                f"font-weight='800' letter-spacing='-0.01em'>{safe_word}</text>"
            )
            placed = True
            break
        if not placed:
            continue
    return (
        "<div style='padding:10px; border:1px solid #e9e9e9; border-radius:10px; background:#f3f5f7;'>"
        f"<svg viewBox='0 0 {width} {height}' style='width:100%; height:auto; display:block;' "
        "xmlns='http://www.w3.org/2000/svg'>"
        "<rect x='0' y='0' width='100%' height='100%' fill='#f3f5f7' />"
        + "".join(svg_text_nodes)
        + "</svg></div>"
    )
