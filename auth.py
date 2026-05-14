import bcrypt


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _is_hashed(stored: str) -> bool:
    return stored.startswith(("$2b$", "$2a$"))


def _verify_password(plain: str, stored: str) -> bool:
    if _is_hashed(stored):
        try:
            return bcrypt.checkpw(plain.encode(), stored.encode())
        except Exception:
            return False
    return plain == stored
