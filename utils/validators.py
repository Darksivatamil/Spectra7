import re
import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ISD_FILE = os.path.join(DATA_DIR, "isdcodes.json")

_ISD_CODES = None


def _load_isdcodes():
    global _ISD_CODES
    if _ISD_CODES is not None:
        return _ISD_CODES
    try:
        with open(ISD_FILE, "r") as f:
            data = json.load(f)
        _ISD_CODES = data.get("isdcodes", {})
    except Exception:
        _ISD_CODES = {"91": "India"}
    return _ISD_CODES


def is_valid_cc(cc: str) -> bool:
    """Check if country code exists in isdcodes.json."""
    codes = _load_isdcodes()
    return cc in codes


def validate_phone(number: str, cc: str = "91") -> bool:
    """Validate phone number based on country code pattern."""
    cleaned = number.strip().lstrip("+")
    if cleaned.startswith("91") and len(cleaned) > 10:
        cleaned = cleaned[2:]
    if not cleaned.isdigit():
        return False
    if cc == "91":
        return bool(re.fullmatch(r"[6-9]\d{9}", cleaned))
    if cc == "1":  # USA/Canada
        return bool(re.fullmatch(r"\d{10}", cleaned))
    return bool(re.fullmatch(r"\d{7,15}", cleaned))


def validate_email(email: str) -> bool:
    return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email.strip()))


def validate_count(message_count: int, max_limit: int = 10000) -> int:
    if message_count < 1:
        return 1
    if message_count > max_limit:
        return max_limit
    return message_count
