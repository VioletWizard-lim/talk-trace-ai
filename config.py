from env import get_secret

AI_MODEL_NAME = "gemini-2.5-flash"
LIVE_BOARD_FETCH_LIMIT = 150
DASHBOARD_FETCH_LIMIT = 500
LIVE_REFRESH_INTERVAL = "15s"
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
    {"label": "딥페이크와 초상권", "title": "딥페이크 기술 사용은 법으로 전면 금지해야 한다", "mode": "⚔️ 찬반 토론"},
    {"label": "AI 창작물 저작권", "title": "AI가 만든 작품에도 저작권을 인정해야 한다", "mode": "⚔️ 찬반 토론"},
    {"label": "온라인 개인정보", "title": "서비스 이용을 위해 개인정보를 제공하는 것은 괜찮다", "mode": "⚔️ 찬반 토론"},
    {"label": "사이버 폭력과 표현의 자유", "title": "사이버 폭력 방지를 위해 온라인 표현의 자유를 제한할 수 있다", "mode": "⚔️ 찬반 토론"},
    {"label": "AI 챗봇과 사고력", "title": "AI 챗봇 사용은 학생의 사고력 발달에 방해가 된다", "mode": "⚔️ 찬반 토론"},
    {"label": "AI 활용과 표절", "title": "과제에 AI를 활용하는 것, 어디까지가 표절일까?", "mode": "💡 자유 토의"},
    {"label": "AI 알고리즘 편향", "title": "AI 알고리즘 편향의 책임은 개발자에게 있다", "mode": "⚔️ 찬반 토론"},
]
