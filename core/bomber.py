import re
import threading
from core.dispatch import get_dispatcher

AVAILABLE_MODES = ["direct"]

_CANCEL_EVENTS = {}
_CANCEL_LOCK = threading.Lock()


def cancel_attack(attack_id):
    with _CANCEL_LOCK:
        entry = _CANCEL_EVENTS.get(attack_id)
        if entry:
            dispatcher, _ = entry
            dispatcher.cancel()
            return True
        return False


def is_valid_phone(number, cc="91"):
    if cc == "91":
        return bool(re.fullmatch(r"[6-9]\d{9}", number))
    return bool(re.fullmatch(r"\d{7,15}", number))


def bomber(cc, target, count, api_pool,
           delay=1, mode="direct", ai_gen=None, category=None,
           on_progress=None, threads=5, attack_id=None,
           use_smart=False, engine_mode="auto"):
    ai_messages = [None] * count

    dispatcher = get_dispatcher(
        cc=cc, target=target, count=count, api_pool=api_pool,
        on_progress=on_progress, attack_id=attack_id,
        delay=delay, threads=threads, smart=use_smart,
        ai_messages=ai_messages, engine_mode=engine_mode,
    )

    if attack_id is not None:
        done_ev = threading.Event()
        with _CANCEL_LOCK:
            _CANCEL_EVENTS[attack_id] = (dispatcher, done_ev)

    try:
        result = dispatcher.run()
        return result.as_dict()
    finally:
        if attack_id is not None:
            with _CANCEL_LOCK:
                _CANCEL_EVENTS.pop(attack_id, None)
