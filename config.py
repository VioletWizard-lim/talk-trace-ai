from env import get_secret

AI_MODEL_NAME = "gemini-2.5-flash"
LIVE_BOARD_FETCH_LIMIT = 300
DASHBOARD_FETCH_LIMIT = 2000
LIVE_REFRESH_INTERVAL = "5s"
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
