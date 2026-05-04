import html
import math
import re
from collections import Counter


def build_word_frequencies(text_series):
    tokens = []
    stopwords = {
        "그리고", "하지만", "그래서", "정말", "제가", "저는", "너무", "이번", "지금",
        "그냥", "대한", "대한해", "같은", "합니다", "입니다", "있는", "없는", "수업",
        "토론", "토의", "의견", "생각", "내용", "때문", "하면", "하면요", "입니다요", "있다", "않으면", "많은"
    }
    particle_suffixes = [
        "에게서", "으로는", "이라고", "라면", "처럼", "까지는", "으로도", "에서", "에게", "으로", "로써",
        "로서", "보다", "까지", "부터", "만큼", "이나", "라도", "이며", "이고", "에서", "으로", "이라",
        "라고", "와", "과", "을", "를", "이", "가", "은", "는", "에", "도", "만", "로", "랑", "나"
    ]

    def normalize_token(token):
        cleaned = re.sub(r"^[^\w가-힣]+|[^\w가-힣]+$", "", token)
        if len(cleaned) < 2:
            return ""
        normalized = cleaned
        for suffix in particle_suffixes:
            if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
                normalized = normalized[: -len(suffix)]
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


def build_circular_wordcloud_html(frequencies, max_words=75, width=760, height=520):
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
