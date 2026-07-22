"""Abstract dispatcher base class and result types."""
import time
import threading
from abc import ABC, abstractmethod
from typing import Callable, Optional

ProgressCallback = Callable[[int, int, int, int, str, str], None]


class DispatcherResult:
    """Standard result returned by all dispatchers."""
    def __init__(self, sent=0, success=0, failed=0, errors=None):
        self.sent = sent
        self.success = success
        self.failed = failed
        self.errors = errors or []

    def as_dict(self):
        return {"sent": self.sent, "success": self.success, "failed": self.failed, "errors": self.errors[:10]}


class BaseDispatcher(ABC):
    """ABC for concurrency backends.

    Each dispatcher takes the same input and produces the same result.
    """

    def __init__(self, cc: str, target: str, count: int, api_pool: list,
                 on_progress: Optional[ProgressCallback] = None,
                 attack_id=None, delay=2, threads=5, smart=False,
                 ai_messages=None):
        self.cc = cc
        self.target = target
        self.count = count
        self.api_pool = list(api_pool)
        self.on_progress = on_progress
        self.attack_id = attack_id
        self.delay = delay
        self.threads = max(1, threads or 1)
        self.smart = smart
        self.ai_messages = ai_messages or [None] * count

        # Cancel support
        self._cancel_ev = threading.Event()

    def cancel(self):
        self._cancel_ev.set()

    @property
    def cancelled(self):
        return self._cancel_ev.is_set()

    @abstractmethod
    def run(self) -> DispatcherResult:
        ...

    def _report(self, sent, success, failed, total, api_name="", last_msg=""):
        if self.on_progress:
            self.on_progress(sent, success, failed, total, api_name, last_msg)
