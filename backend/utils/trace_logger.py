import json, logging, time, uuid
from typing import Any, Optional

_trace = logging.getLogger("trace")

class TraceLogger:
    def __init__(self, session_id: str, trace_id: str | None = None):
        self.session_id = session_id
        self.trace_id = trace_id or str(uuid.uuid4())[:12]
        self._timers: dict[str, float] = {}

    def log(self, event: str, data: Any = None, elapsed_ms: Optional[float] = None):
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "trace_id": self.trace_id,
                  "session_id": self.session_id, "event": event,
                  "elapsed_ms": round(elapsed_ms, 2) if elapsed_ms is not None else None,
                  "data": self._ser(data)}
        _trace.debug(json.dumps(record, ensure_ascii=False, default=str))

    def start_timer(self, n): self._timers[n] = time.perf_counter()
    def stop_timer(self, n): s = self._timers.pop(n, None); return (time.perf_counter() - s) * 1000 if s else 0.0
    def log_timed(self, event, timer, data=None): self.log(event, data=data, elapsed_ms=self.stop_timer(timer))
    def child(self, prefix): return ScopedTraceLogger(self, prefix)

    @staticmethod
    def _ser(d):
        if d is None: return None
        if isinstance(d, (str, int, float, bool)): return d
        if isinstance(d, (list, tuple)): return [TraceLogger._ser(i) for i in d]
        if isinstance(d, dict): return {k: TraceLogger._ser(v) for k, v in d.items()}
        if hasattr(d, "__dict__"): return TraceLogger._ser(vars(d))
        return str(d)

class ScopedTraceLogger:
    def __init__(self, parent, prefix): self._p, self._pfx = parent, prefix
    def log(self, e, data=None, elapsed_ms=None): self._p.log(f"{self._pfx}.{e}", data=data, elapsed_ms=elapsed_ms)
    def start_timer(self, n): self._p.start_timer(f"{self._pfx}.{n}")
    def stop_timer(self, n): return self._p.stop_timer(f"{self._pfx}.{n}")
    def log_timed(self, e, t, data=None): self.log(e, data=data, elapsed_ms=self.stop_timer(t))
