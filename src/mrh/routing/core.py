"""Shared safe provider failures and bounded execution."""
import queue
import threading

class ClassifierUnavailable(Exception):
    pass

class ClassifierFailure(Exception):
    """Safe typed provider failure; telemetry may contain only validated scalars."""
    def __init__(self, reason, telemetry=None):
        self.reason = reason
        self.telemetry = telemetry or {}
        super().__init__(reason)

def bounded_call(fn, timeout):
    results = queue.Queue(maxsize=1)

    def work():
        try:
            results.put((True, fn()))
        except Exception as exc:
            # Exception stays in memory only; caller exposes a fixed reason code.
            results.put((False, exc))

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    try:
        ok, result = results.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError() from None
    if not ok:
        raise result
    return result
