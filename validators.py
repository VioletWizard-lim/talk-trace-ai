import re


def normalize_user_text(raw_text, max_len=500):
    text = (raw_text or "").strip()
    return text[:max_len] if text else ""


def normalize_room_name(raw_text, max_len=60):
    text = normalize_user_text(raw_text, max_len=max_len)
    return re.sub(r"\s+", " ", text).strip() if text else ""


def mask_ip_for_teacher(ip_text):
    ip = str(ip_text or "").strip()
    if not ip:
        return ""

    ipv4_parts = ip.split(".")
    if len(ipv4_parts) == 4 and all(part.isdigit() for part in ipv4_parts):
        return f"{ipv4_parts[0]}.XXX.XXX.{ipv4_parts[3]}"

    if ":" in ip:
        ipv6_parts = ip.split(":")
        if len(ipv6_parts) >= 3:
            return f"{ipv6_parts[0]}:{ipv6_parts[1]}:XXXX:XXXX:{ipv6_parts[-1]}"
    return ip


def with_fallback_author_role(df):
    if df.empty:
        return df

    fixed = df.copy()
    if "author_role" not in fixed.columns:
        fixed["author_role"] = "학생"
        return fixed

    fixed["author_role"] = fixed["author_role"].fillna("").astype(str).str.strip()
    teacher_name_hint = fixed["student_name"].fillna("").astype(str).str.contains("교사|선생님", regex=True)
    fixed.loc[(fixed["author_role"] == "") & teacher_name_hint, "author_role"] = "교사"
    fixed.loc[fixed["author_role"] == "", "author_role"] = "학생"
    return fixed
