def parse_bool(text: str) -> bool:
    return str(text).strip().lower() in ("1","true","yes","y")
