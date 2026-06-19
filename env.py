import os


def get_secret(key: str, default: str = "") -> str:
    return os.environ.get(key, "").strip() or default
