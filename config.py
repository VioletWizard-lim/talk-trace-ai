from db import _get_secret

AI_MODEL_NAME = "gemini-2.5-flash"
LIVE_BOARD_FETCH_LIMIT = 300
DASHBOARD_FETCH_LIMIT = 2000
RECORDS_FETCH_LIMIT = 500
LIVE_REFRESH_INTERVAL = "5s"
AI_HINT_ENABLED = str(_get_secret("AI_HINT_ENABLED", "true")).lower() not in ("false", "0", "no")
ROOM_DESTROY_ENABLED = str(_get_secret("ROOM_DESTROY_ENABLED", "true")).lower() not in ("false", "0", "no")
AUTO_JOIN_ON_REFRESH = str(_get_secret("AUTO_JOIN_ON_REFRESH", "false")).lower() not in ("false", "0", "no")
MAX_ROOM_NAME_LEN = 60
MAX_STUDENT_NAME_LEN = 30
MAX_TOPIC_LEN = 120
MAX_ENTRY_CODE_LEN = 60
UI_FONT_FAMILY = "sans-serif"

APP_CSS = """
    <style>
    .records-db-table-wrap { overflow-x: auto; border: 1px solid #e6e6e6; border-radius: 10px; background: #fff; }
    .records-db-table-wrap table { width: 100%; border-collapse: collapse; table-layout: fixed; }
    .records-db-table-wrap th, .records-db-table-wrap td { border-bottom: 1px solid #efefef; border-right: 1px solid #efefef; padding: 10px 12px; text-align: left; vertical-align: top; }
    .records-db-table-wrap th:last-child, .records-db-table-wrap td:last-child { border-right: none; }
    .records-db-table-wrap th { white-space: nowrap; font-weight: 700; }
    .records-db-table-wrap th:nth-child(1), .records-db-table-wrap td:nth-child(1) { width: 5%; white-space: nowrap; }
    .records-db-table-wrap th:nth-child(2), .records-db-table-wrap td:nth-child(2) { width: 15%; white-space: nowrap; }
    .records-db-table-wrap th:nth-child(3), .records-db-table-wrap td:nth-child(3) { width: 12%; white-space: nowrap; }
    .records-db-table-wrap th:nth-child(4), .records-db-table-wrap td:nth-child(4) { width: 68%; white-space: pre-wrap; word-break: break-word; }
    [data-testid="stDecoration"] { display: none !important; }
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
