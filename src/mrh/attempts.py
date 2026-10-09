"""Operation deadline gate. Local expiry is not remote cancellation."""
import threading
import time


class GuardedAttempts:
    def __init__(self, seconds, emit=lambda *_, **__: None):
        self.deadline = time.monotonic() + seconds
        self.emit = emit
        self._lock = threading.RLock()
        self._closed = False
        self._attempts = {}

    def remaining(self):
        return max(0.0, self.deadline - time.monotonic())

    def check(self):
        if self._closed or self.remaining() <= 0:
            raise TimeoutError()

    def requested(self, attempt_id, kind, requested_model=None):
        with self._lock:
            self.check()
            if attempt_id in self._attempts:
                old = self._attempts[attempt_id]
                if old["kind"] != kind or old["model"] != requested_model:
                    raise ValueError("conflicting_attempt")
                return
            metadata = {"requested_model": requested_model} if requested_model is not None else {}
            self.emit(attempt_id, kind, "requested", **metadata)
            self._attempts[attempt_id] = {"kind": kind, "model": requested_model, "phase": "requested"}

    def invoke(self, attempt_id, fn, *, kind, requested_model=None):
        self.requested(attempt_id, kind, requested_model)
        def enter():
            with self._lock:
                self.check()
                attempt = self._attempts[attempt_id]
                if attempt["phase"] != "requested":
                    raise ValueError("attempt_already_invoked")
                self.emit(attempt_id, kind, "started")
                attempt["phase"] = "started"
                return self.check
        with self._lock:
            self.check()
            attempt = self._attempts[attempt_id]
            if attempt["phase"] != "requested":
                raise ValueError("attempt_already_invoked")
        # Entry is the transport's first operation. Cancellation before entry
        # creates no started invocation; an entered call remains in flight.
        result = fn(enter)
        with self._lock:
            if self._attempts[attempt_id]["phase"] == "requested":
                raise ValueError("transport_entry_not_recorded")
        return result

    def finish(self, attempt_id, outcome, **metadata):
        if outcome not in ("returned", "error", "unknown"):
            raise ValueError("invalid_attempt_outcome")
        with self._lock:
            attempt = self._attempts.get(attempt_id)
            if not attempt or attempt["phase"] == "requested":
                raise ValueError("attempt_not_started")
            if self._closed or self.remaining() <= 0:
                if attempt["phase"] == "started":
                    self.emit(attempt_id, attempt["kind"], "unknown")
                    attempt["phase"] = "unknown"
                if attempt["phase"] == "unknown" and outcome != "unknown":
                    self.emit(attempt_id, attempt["kind"], "late_" + outcome, **metadata)
                    return
            self.emit(attempt_id, attempt["kind"], outcome, **metadata)
            attempt["phase"] = outcome

    def __call__(self, attempt_id, kind, outcome):
        # Backward-compatible scripted convenience: one known fake invocation,
        # not a new live retry policy.
        self.invoke(attempt_id, lambda enter: enter(), kind=kind)
        self.finish(attempt_id, outcome)

    def cancel(self):
        with self._lock:
            self._closed = True
            for attempt_id, attempt in self._attempts.items():
                if attempt["phase"] == "started":
                    self.emit(attempt_id, attempt["kind"], "unknown")
                    attempt["phase"] = "unknown"
