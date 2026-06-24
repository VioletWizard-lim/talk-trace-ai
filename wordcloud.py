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
        "서로", "수도", "바로", "함께", "계속", "오히려", "빠르게",
    }
    particle_suffixes = [
        "에게서", "으로는", "이라고", "라면", "처럼", "까지는", "으로도", "에서", "에게", "으로", "로써",
        "로서", "보다", "까지", "부터", "만큼", "이나", "라도", "이며", "이고", "에서", "으로", "이라",
        "라고", "와", "과", "을", "를", "이", "가", "은", "는", "에", "도", "만", "로", "랑", "나",
        # 목적격·주격 추가 (사람을 → 사람)
        "에게도", "에서도", "로도",
    ]
    # 동사 활용형 어미 — 이 어미로 끝나는 토큰은 제거
    verb_endings = (
        "하고", "하면", "하며", "하여", "하기", "한다", "하는", "하게", "하지",
        "되고", "되며", "되어", "되기", "된다", "되는", "되게",
        "이고", "이며", "이기", "인다", "이는",
        "발견하고", "공유하면", "배우고", "생각하기", "부여한다",
    )

    def normalize_token(token):
        cleaned = re.sub(r"^[^\w가-힣]+|[^\w가-힣]+$", "", token)
        if len(cleaned) < 2:
            return ""
        normalized = cleaned
        for suffix in particle_suffixes:
            if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
                normalized = normalized[: -len(suffix)]
                break
        # 동사 활용형 어미로 끝나면 제거
        for ending in verb_endings:
            if normalized.endswith(ending) and len(normalized) > len(ending) + 1:
                normalized = normalized[: -len(ending)]
                break
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


def build_circular_wordcloud_html(frequencies, max_words=40, width=760, height=520):
    if not frequencies:
        return ""
    sorted_words = sorted(frequencies.items(), key=lambda item: (-item[1], item[0]))[:max_words]
    max_count = sorted_words[0][1]
    min_count = sorted_words[-1][1]
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
