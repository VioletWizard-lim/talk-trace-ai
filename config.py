from env import get_secret

AI_MODEL_NAME = "gemini-2.5-flash"
AI_MODEL_NAME_PRO = "gemini-2.5-pro"
LIVE_BOARD_FETCH_LIMIT = 100
DASHBOARD_FETCH_LIMIT = 300
LIVE_REFRESH_INTERVAL = "20s"
AI_HINT_ENABLED = str(get_secret("AI_HINT_ENABLED", "true")).lower() not in ("false", "0", "no")
ROOM_DESTROY_ENABLED = str(get_secret("ROOM_DESTROY_ENABLED", "true")).lower() not in ("false", "0", "no")
AUTO_JOIN_ON_REFRESH = str(get_secret("AUTO_JOIN_ON_REFRESH", "false")).lower() not in ("false", "0", "no")
MAX_ROOM_NAME_LEN = 60
MAX_STUDENT_NAME_LEN = 30
MAX_TOPIC_LEN = 120
MAX_ENTRY_CODE_LEN = 60
UI_FONT_FAMILY = "sans-serif"

APP_CSS = """
    <style>
    [data-testid="stDecoration"] { display: none !important; }
    [data-testid="stStatusWidget"] { display: none !important; }
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stMainBlockContainer"],
    [data-testid="stAppViewBlockContainer"], [data-testid="stFragment"],
    [data-testid="stVerticalBlock"], [data-testid="stElementContainer"],
    [data-testid="stExpander"], details, summary,
    *[data-stale="true"], div[data-stale="true"] {
        opacity: 1 !important; transition: none !important; filter: none !important; -webkit-filter: none !important;
    }
    .stTextArea textarea, .stTextInput input, .stSelectbox, .stRadio label,
    .stMarkdown p, div[data-testid="stChatMessageContent"] { font-size: 18px !important; }
    .stAlert p { font-size: 20px !important; font-weight: bold; }
    </style>
"""

DIGITAL_ETHICS_TOPICS = [
    {
        "label": "딥페이크와 초상권",
        "title": "딥페이크 기술 사용은 법으로 전면 금지해야 한다",
        "mode": "⚔️ 찬반 토론",
        "pro": "딥페이크는 초상권·명예훼손 피해가 심각하고 범죄 악용 위험이 높아 법적 전면 금지가 필요하다.",
        "con": "기술 자체보다 악용 행위를 규제해야 하며, 예술·교육 등 합법적 활용 가능성을 막아서는 안 된다.",
    },
    {
        "label": "AI 창작물 저작권",
        "title": "AI가 만든 작품에도 저작권을 인정해야 한다",
        "mode": "⚔️ 찬반 토론",
        "pro": "AI 개발·운영에 인간의 창의적 노력이 투입되었으므로 결과물에도 저작권 보호가 필요하다.",
        "con": "저작권은 인간 창작자 보호를 위한 제도이므로, AI 생성물은 공공 영역으로 두어야 한다.",
    },
    {
        "label": "온라인 개인정보",
        "title": "서비스 이용을 위해 개인정보를 제공하는 것은 괜찮다",
        "mode": "⚔️ 찬반 토론",
        "pro": "편리한 서비스를 위한 자발적 동의이며, 적절히 관리된다면 합리적인 교환이다.",
        "con": "개인정보 유출·오남용 위험이 크고, 동의 구조가 불평등해 실질적 선택권이 보장되지 않는다.",
    },
    {
        "label": "사이버 폭력과 표현의 자유",
        "title": "사이버 폭력 방지를 위해 온라인 표현의 자유를 제한할 수 있다",
        "mode": "⚔️ 찬반 토론",
        "pro": "피해자 보호와 건전한 온라인 문화를 위해 혐오·폭력적 표현은 규제가 불가피하다.",
        "con": "표현의 자유는 민주주의의 핵심이며, 국가 검열로 이어질 수 있어 제한에 신중해야 한다.",
    },
    {
        "label": "AI 챗봇과 사고력",
        "title": "AI 챗봇 사용은 학생의 사고력 발달에 방해가 된다",
        "mode": "⚔️ 찬반 토론",
        "pro": "스스로 고민하는 과정 없이 답을 얻으면 비판적 사고·문제해결 능력이 약화될 수 있다.",
        "con": "단순 반복 학습을 줄이고 더 높은 수준의 사고에 집중할 수 있도록 돕는 도구로 활용할 수 있다.",
    },
    {
        "label": "AI 활용과 표절",
        "title": "과제에 AI를 활용하는 것, 어디까지가 표절일까?",
        "mode": "💡 자유 토의",
        "pro": None,
        "con": None,
    },
    {
        "label": "AI 알고리즘 편향",
        "title": "AI 알고리즘 편향의 책임은 개발자에게 있다",
        "mode": "⚔️ 찬반 토론",
        "pro": "편향된 데이터를 선택·설계하는 것은 개발자이므로 결과에 대한 1차 책임은 개발자에게 있다.",
        "con": "알고리즘 편향은 사회 구조적 문제를 반영하며, 기업·정부·이용자 모두 함께 책임져야 한다.",
    },
]
