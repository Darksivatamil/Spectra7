"""ThreadPoolExecutor dispatcher — round-robin concurrency."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.api_aggregator import send_request
from core.dispatch.base import BaseDispatcher, DispatcherResult


class ThreadedDispatcher(BaseDispatcher):
    """Threaded dispatcher using Python ThreadPoolExecutor.

    Workers = min(threads, remaining_count). Each call is a separate future.
    APIs are cycled round-robin — always put back into pool regardless of
    success/failure so the attack never stalls.
    """

    def run(self) -> DispatcherResult:
        success = 0
        failed = 0
        sent = 0
        pool = list(self.api_pool)
        errors = []
        to_send = list(range(self.count))

        while to_send and not self.cancelled:
            batch = to_send[:self.threads]
            to_send = to_send[self.threads:]
            if not pool:
                # All APIs exhausted — nothing more we can do
                dropped = len(batch)
                failed += dropped
                sent += dropped
                self._report(sent, success, failed, self.count, "NO-APIS", "")
                continue
            with ThreadPoolExecutor(max_workers=min(self.threads, len(batch), len(pool))) as exec:
                futures = {}
                for idx in batch:
                    if not pool:
                        break
                    api = pool.pop(0)
                    msg = self.ai_messages[idx] if idx < len(self.ai_messages) else None
                    delay_sec = self.delay if idx > 0 and not self.smart else 0
                    fut = exec.submit(send_request, api, self.cc, self.target,
                                      delay=delay_sec, message=msg,
                                      attack_id=self.attack_id)
                    futures[fut] = (api, msg)

                for fut in as_completed(futures):
                    api, msg = futures[fut]
                    try:
                        result = fut.result()
                    except Exception as e:
                        result = {"status": "fail", "error": str(e), "api": api.get("name", "?")}
                    sent += 1
                    if result["status"] == "success":
                        success += 1
                    else:
                        failed += 1
                        if result.get("error"):
                            errors.append(result["error"])
                    # Always recycle the API so the pool never empties
                    pool.append(api)
                    self._report(sent, success, failed, self.count,
                                 result.get("api", "?"), msg or "")

        return DispatcherResult(sent, success, failed, errors)
