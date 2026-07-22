"""Factory — returns the best available dispatcher.

Priority chain: Threaded (default) -> Sequential
"""
from core.dispatch.base import BaseDispatcher
from core.dispatch.threaded import ThreadedDispatcher


def get_dispatcher(cc: str, target: str, count: int, api_pool: list,
                   on_progress=None, attack_id=None, delay=2, threads=5,
                   smart=False, ai_messages=None,
                   engine_mode="auto") -> BaseDispatcher:
    """Factory: returns dispatcher based on engine_mode.

    engine_mode options:
      - "auto"      : Threaded (default)
      - "threaded"  : ThreadPoolExecutor
      - "sequential": single-threaded (threads=1)
    """
    kwargs = dict(
        cc=cc, target=target, count=count, api_pool=api_pool,
        on_progress=on_progress, attack_id=attack_id,
        delay=delay, threads=threads, smart=smart,
        ai_messages=ai_messages,
    )

    mode = engine_mode.lower().strip()
    if mode == "sequential":
        kwargs["threads"] = 1
        return ThreadedDispatcher(**kwargs)

    return ThreadedDispatcher(**kwargs)
