from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, Concatenate, Literal, ParamSpec, get_args

from common_libs.ansi_colors import ColorCodes, color
from common_libs.lock import Lock
from common_libs.logging import get_logger

from ..types import RestResponse

if TYPE_CHECKING:
    from .endpoint_func import EndpointFunc

__all__ = ["Stats"]


logger = get_logger(__name__)

P = ParamSpec("P")

SortBy = Literal["calls", "slowest", "errors", "endpoint"]
_INF_JSON = None
_SORT_KEYS = frozenset(get_args(SortBy))
_COL_HEADERS = (
    "Endpoint",
    "Calls",
    "1xx",
    "2xx",
    "3xx",
    "4xx",
    "5xx",
    "Error",
    "min",
    "avg",
    "max",
    "p50",
    "p95",
    "p99",
)
_COL_4XX = _COL_HEADERS.index("4xx")
_COL_5XX = _COL_HEADERS.index("5xx")
_COL_ERROR = _COL_HEADERS.index("Error")
_LATENCY_COL_START = _COL_HEADERS.index("min")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Histogram constants for latency percentile estimation (DDSketch logarithmic mapping).
# alpha = 1%: guaranteed relative error on all percentile VALUES; rank selection is exact.
# gamma MUST remain constant — merging histograms requires identical bucket boundaries.
_HISTOGRAM_REL_ACCURACY = 0.01
_HISTOGRAM_GAMMA = (1 + _HISTOGRAM_REL_ACCURACY) / (1 - _HISTOGRAM_REL_ACCURACY)
_HISTOGRAM_LOG_GAMMA = math.log(_HISTOGRAM_GAMMA)
_MIN_RESPONSE_TIME = 1e-9  # floor to keep log() safe for zero / near-zero timings


@dataclass(slots=True)
class EndpointStat:
    """Per-endpoint statistics record.

    :param app_name: Name of the app this endpoint belongs to.
    :param endpoint: String representation of the endpoint, e.g. `"POST /v1/auth/login"`.
    """

    app_name: str
    endpoint: str
    num_calls: int = field(default=0, init=False)
    num_1xx: int = field(default=0, init=False)
    num_2xx: int = field(default=0, init=False)
    num_3xx: int = field(default=0, init=False)
    num_4xx: int = field(default=0, init=False)
    num_5xx: int = field(default=0, init=False)
    num_unknown_status: int = field(default=0, init=False)
    num_errors: int = field(default=0, init=False)

    # Private response-time accumulators — excluded from repr to keep debug output clean.
    # Stored as raw (count, sum, min, max) so merges across workers stay exact.
    # _time_buckets holds log-scale histogram counts for percentile estimation (DDSketch, alpha=1%).
    _time_count: int = field(default=0, init=False, repr=False)
    _time_sum: float = field(default=0.0, init=False, repr=False)
    _time_min: float = field(default=math.inf, init=False, repr=False)
    _time_max: float = field(default=0.0, init=False, repr=False)
    _time_buckets: dict[int, int] = field(default_factory=dict, init=False, repr=False)

    @property
    def avg_response_time(self) -> float | None:
        """Average response time in seconds, or `None` when no timed samples exist."""
        return self._time_sum / self._time_count if self._time_count > 0 else None

    @property
    def min_response_time(self) -> float | None:
        """Minimum response time in seconds, or `None` when no timed samples exist."""
        return self._time_min if self._time_count > 0 else None

    @property
    def max_response_time(self) -> float | None:
        """Maximum response time in seconds, or `None` when no timed samples exist."""
        return self._time_max if self._time_count > 0 else None

    @property
    def p50_response_time(self) -> float | None:
        """Estimated 50th-percentile response time in seconds, or `None` when no timed samples exist.

        Uses a log-scale histogram (DDSketch, alpha=1%): rank selection is exact; the returned value is within 1% of
        the true percentile value.
        """
        return self._percentile(50)

    @property
    def p95_response_time(self) -> float | None:
        """Estimated 95th-percentile response time in seconds, or `None` when no timed samples exist.

        Uses a log-scale histogram (DDSketch, alpha=1%): rank selection is exact; the returned value is within 1% of
        the true percentile value.
        """
        return self._percentile(95)

    @property
    def p99_response_time(self) -> float | None:
        """Estimated 99th-percentile response time in seconds, or `None` when no timed samples exist.

        Uses a log-scale histogram (DDSketch, alpha=1%): rank selection is exact; the returned value is within 1% of
        the true percentile value.
        """
        return self._percentile(99)

    def record_response(self, status_code: int, response_time: float | None) -> None:
        """Record a completed HTTP response.

        :param status_code: HTTP status code of the response.
        :param response_time: Elapsed seconds, or `None` when timing is unavailable.
        """
        self.num_calls += 1
        status_class = status_code // 100
        if status_class == 1:
            self.num_1xx += 1
        elif status_class == 2:
            self.num_2xx += 1
        elif status_class == 3:
            self.num_3xx += 1
        elif status_class == 4:
            self.num_4xx += 1
        elif status_class == 5:
            self.num_5xx += 1
        else:
            self.num_unknown_status += 1

        if response_time is not None:
            self._time_count += 1
            self._time_sum += response_time
            self._time_min = min(self._time_min, response_time)
            self._time_max = max(self._time_max, response_time)
            idx = _bucket_index(response_time)
            self._time_buckets[idx] = self._time_buckets.get(idx, 0) + 1

    def record_error(self) -> None:
        """Record a call that raised an exception (no HTTP response received)."""
        self.num_calls += 1
        self.num_errors += 1

    def copy(self) -> EndpointStat:
        """Return an independent snapshot of this stat record."""
        return deepcopy(self)

    def merge_in(self, other: EndpointStat) -> None:
        """Merge another stat record into this one.

        Count fields merge exactly. Response-time aggregates (`_time_sum`, `_time_min`, `_time_max`) are floating-point
        sums and may accumulate rounding error across many merges.

        :param other: The stat record to merge from.
        """
        self.num_calls += other.num_calls
        self.num_1xx += other.num_1xx
        self.num_2xx += other.num_2xx
        self.num_3xx += other.num_3xx
        self.num_4xx += other.num_4xx
        self.num_5xx += other.num_5xx
        self.num_unknown_status += other.num_unknown_status
        self.num_errors += other.num_errors
        self._time_count += other._time_count
        self._time_sum += other._time_sum
        # math.inf as sentinel for "no samples" means min/max work correctly on merge
        self._time_min = min(self._time_min, other._time_min)
        self._time_max = max(self._time_max, other._time_max)
        for idx, count in other._time_buckets.items():
            self._time_buckets[idx] = self._time_buckets.get(idx, 0) + count

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict.

        `_time_min` is stored as `None` when no timed samples exist (math.inf is not valid JSON).
        """
        d = asdict(self)
        if math.isinf(d["_time_min"]):
            d["_time_min"] = _INF_JSON
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EndpointStat:
        """Reconstruct from a `to_dict()` payload.

        Missing keys keep their dataclass defaults; unknown keys are ignored. Tolerates payloads written by a
        different version of the library.

        :param d: Dict produced by `to_dict()`.
        """
        stat = cls(app_name=d.get("app_name", "unknown"), endpoint=d.get("endpoint", ""))
        for f in fields(stat):
            if f.init or f.name not in d:
                continue
            value = d[f.name]
            if f.name == "_time_min" and value is None:
                value = math.inf
            elif f.name == "_time_buckets" and isinstance(value, dict):
                # JSON round-trip stringifies int keys; coerce them back
                value = {int(k): v for k, v in value.items()}
            setattr(stat, f.name, value)
        return stat

    def _percentiles(self, *qs: float) -> dict[float, float | None]:
        """Return estimated percentiles for all `qs` in a single bucket-sort pass.

        Sorts `_time_buckets` once and resolves each percentile by iterating the pre-sorted list, avoiding repeated
        `sorted()` calls when multiple percentiles are needed. Returns a dict mapping each `q` to its estimated
        value (or `None` when no timed samples exist).

        :param qs: Percentiles to compute, e.g. `50`, `95`, `99`.
        """
        if not self._time_buckets:
            return {q: None for q in qs}
        sorted_buckets = sorted(self._time_buckets.items())
        last_idx = sorted_buckets[-1][0]
        result: dict[float, float | None] = {}
        for q in qs:
            rank = max(1, math.ceil(q / 100 * self._time_count))
            cumulative = 0
            for idx, count in sorted_buckets:
                cumulative += count
                if cumulative >= rank:
                    result[q] = min(max(_bucket_value(idx), self._time_min), self._time_max)
                    break
            else:
                result[q] = min(max(_bucket_value(last_idx), self._time_min), self._time_max)
        return result

    def _percentile(self, q: float) -> float | None:
        """Return the estimated q-th percentile of response times in seconds.

        Uses the log-scale histogram buckets (DDSketch, alpha=1%). Rank selection is exact. The returned value is
        within 1% of the true percentile value. Returns `None` when no timed samples exist.

        :param q: Percentile to compute, e.g. `50`, `95`, or `99`.
        """
        return self._percentiles(q)[q]


class StatsCollector:
    """Thread-safe per-process API statistics collector.

    Maintains a dict of `EndpointStat` records keyed by `"{app_name}|{endpoint}"`

    :param name: A label for this collector (used in logs and serialized output).
    """

    def __init__(self, name: str = "global") -> None:
        self._name = name
        self._lock = threading.RLock()
        self._stats: dict[str, EndpointStat] = {}

    def get(self, endpoint: str, app_name: str | None = None) -> EndpointStat | None:
        """Return an independent snapshot of the stat record for the given endpoint key.

        :param endpoint: Endpoint string, e.g. `"POST /v1/auth/login"`.
        :param app_name: Restrict search to a specific app. When `None`, the endpoint is looked up across all apps.
                         If the same endpoint exists in multiple apps, `app_name` must be provided.
        """
        with self._lock:
            if app_name is not None:
                stat = self._stats.get(f"{app_name}|{endpoint}")
                return stat.copy() if stat is not None else None
            matches = [stat for stat in self._stats.values() if stat.endpoint == endpoint]
            if len(matches) > 1:
                app_names = ", ".join(repr(s.app_name) for s in matches)
                raise ValueError(
                    f"Endpoint {endpoint!r} exists in multiple apps ({app_names}). app_name must be provided to locate "
                    f"the correct stats."
                )
            return matches[0].copy() if matches else None

    def all(self) -> list[EndpointStat]:
        """Return a snapshot list of independent copies of all recorded endpoint stats."""
        with self._lock:
            return [stat.copy() for stat in self._stats.values()]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the collector's current state as a dictionary"""
        with self._lock:
            return {
                "name": self._name,
                "stats": {k: v.to_dict() for k, v in self._stats.items()},
            }

    def merge(self, other: StatsCollector | dict[str, Any]) -> None:
        """Merge another collector's stats into this one.

        Accepts either a `StatsCollector` instance or a dictionary.

        :param other: A `StatsCollector` or the dict from `to_dict()`.
        """
        other_dict = other.to_dict() if isinstance(other, StatsCollector) else other
        with self._lock:
            for key, stat_dict in (other_dict.get("stats") or {}).items():
                if key in self._stats:
                    self._stats[key].merge_in(EndpointStat.from_dict(stat_dict))
                else:
                    self._stats[key] = EndpointStat.from_dict(stat_dict)

    def reset(self) -> None:
        """Clear all recorded stats."""
        with self._lock:
            self._stats.clear()

    def dump(self, path: str | Path, indent: int = 2) -> None:
        """Write the collector's current state to a JSON file.

        :param path: Destination file path (created or overwritten).
        :param indent: Indent level for JSON output.
        """
        Path(path).write_text(json.dumps(self.to_dict(), indent=indent))

    def aggregate(self, path: str | Path) -> None:
        """Merge this collector's snapshot into a shared JSON file (cross-process safe).

        Uses a file lock so that multiple processes can safely aggregate into the same file.

        :param path: Path to the shared JSON file (created if it does not exist).
        """
        path = Path(path)
        lock_name = f"api-stats-{path.stem}"
        with Lock(lock_name):
            existing: dict[str, Any]
            if path.exists():
                try:
                    existing = json.loads(path.read_text())
                except json.JSONDecodeError:
                    logger.warning(f"Corrupted stats file at {path!r}")
                    existing = {"name": "aggregated", "stats": {}}
            else:
                existing = {"name": "aggregated", "stats": {}}
            aggregated = StatsCollector.from_dict(existing)
            aggregated.merge(self)
            _atomic_write(path, json.dumps(aggregated.to_dict()))

    def show(
        self,
        sort_by: SortBy = "calls",
        reverse: bool = True,
        endpoint: str | None = None,
        app_name: str | None = None,
    ) -> None:
        """Print a formatted, colored statistics table grouped by app.

        :param sort_by: Column to sort by. One of `"calls"`, `"slowest"`, `"errors"`, or `"endpoint"`.
                        When `"slowest"`, endpoints with no timing data (error-only calls) sort below all timed
                        entries in descending order and above them in ascending order.
        :param reverse: When `True`, sort in descending order.
        :param endpoint: When given, restrict the report to this endpoint and hide the Endpoint column.
        :param app_name: When given, restrict the report to this app.
        """
        if sort_by not in _SORT_KEYS:
            raise ValueError(f"sort_by must be one of {sorted(_SORT_KEYS)!r}, got {sort_by!r}")

        all_stats = self.all()
        filters = {"endpoint": endpoint, "app_name": app_name}
        if app_name is not None:
            all_stats = [s for s in all_stats if s.app_name == app_name]
        if endpoint is not None:
            all_stats = [s for s in all_stats if s.endpoint == endpoint]
        if not all_stats:
            applied = ", ".join(f"{k}={v!r}" for k, v in filters.items() if v is not None)
            print(f"No stats recorded matching {applied}" if applied else "No stats recorded")  # noqa: T201
            return

        hide_endpoint_col = endpoint is not None
        by_app: dict[str, list[EndpointStat]] = {}
        for stat in all_stats:
            by_app.setdefault(stat.app_name, []).append(stat)

        try:
            terminal_width = os.get_terminal_size().columns
        except OSError:
            terminal_width = 130
        formatted = [
            (app, _format_report(stats, sort_by=sort_by, reverse=reverse, hide_endpoint_col=hide_endpoint_col))
            for app, stats in sorted(by_app.items())
        ]
        # The separator line (index 3) gives the visual table width; strip ANSI before measuring
        table_width = max(len(_ANSI_RE.sub("", rep.splitlines()[3])) for _, rep in formatted)
        width = min(table_width, terminal_width)
        for app, report_str in formatted:
            if len(by_app) > 1:
                filler = "-" * ((width - len(app) - 2) // 2)
                print(color(f"\n{filler} {app} {filler}", ColorCodes.GREEN))  # noqa: T201
            print(report_str)  # noqa: T201

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StatsCollector:
        """Reconstruct a `StatsCollector` from a `to_dict()` payload.

        :param data: Dict produced by `to_dict()` or `Stats.to_dict()`.
        """
        collector = cls(name=data.get("name", "unknown"))
        for key, stat_dict in (data.get("stats") or {}).items():
            collector._stats[key] = EndpointStat.from_dict(stat_dict)
        return collector

    @staticmethod
    def record(endpoint_func: EndpointFunc[Any], response: RestResponse | None, exception: Exception | None) -> None:
        if not _collection_state.enabled:
            return
        api_class = endpoint_func.endpoint.api_class
        app_name = (api_class.app_name or "unknown") if api_class else "unknown"
        endpoint = str(endpoint_func.endpoint)
        is_error = exception is not None or response is None

        if is_error:
            for collector in _active_collectors():
                collector._record(app_name, endpoint, status_code=0, response_time=None, is_error=True)
        else:
            status_code = response.status_code
            response_time = response.response_time
            for collector in _active_collectors():
                collector._record(
                    app_name, endpoint, status_code=status_code, response_time=response_time, is_error=False
                )

    def _record(
        self, app_name: str, endpoint: str, *, status_code: int, response_time: float | None, is_error: bool
    ) -> None:
        key = f"{app_name}|{endpoint}"
        with self._lock:
            if key not in self._stats:
                self._stats[key] = EndpointStat(app_name=app_name, endpoint=endpoint)
            stat = self._stats[key]
            if is_error:
                stat.record_error()
            else:
                stat.record_response(status_code, response_time)


_global = StatsCollector("global")

# Stack of active scoped collectors for the current execution context.
_scope_stack: ContextVar[tuple[StatsCollector, ...]] = ContextVar("_scope_stack", default=())

_ENV_STATS_DISABLED = "API_CLIENT_STATS_DISABLED"


class _CollectionState:
    """Mutable holder for the collection-enabled flag (avoids module-level `global`)."""

    enabled: bool = os.environ.get(_ENV_STATS_DISABLED, "").lower() not in ("1", "true", "yes")


_collection_state = _CollectionState()


def _active_collectors() -> tuple[StatsCollector, ...]:
    return (_global, *_scope_stack.get())


class Stats:
    """Process-wide API call statistics, always collected automatically.

    Two access modes:

    1. **Global (always-on):** Every API call routed through `EndpointFunc.__call__` is automatically counted here.
       Access via `Stats.report()`, `Stats.get()`, `Stats.reset()`, etc.

    2. **Scoped:** `Stats.collect()` creates a scoped collector for a code block.
       Stats inside the block roll up to both the scoped collector and the global total.

    For cross-process aggregation, use `Stats.aggregate(shared_path)` (file-locked merge) or the serialization
    primitives (`to_dict` / `from_dict` / `merge`).

    **Disabling automatic collection:** Set the `API_CLIENT_STATS_DISABLED` environment variable to `1` or `true`
    before import to disable collection process-wide, or call `Stats.disable()` at runtime.
    Existing data is retained; call `Stats.reset()` to clear it.
    Manual operations (`StatsCollector._record`, `merge`, `aggregate`) are unaffected.
    """

    @staticmethod
    @contextmanager
    def collect(name: str = "scope") -> Generator[StatsCollector, None, None]:
        """Context manager that creates a scoped statistics collector.

        All API calls made within the block are counted towards **both** the scoped collector (yielded as `stats`) and
        the global `Stats` total.

        Scopes propagate correctly into `asyncio.gather` / `TaskGroup` tasks (they copy the execution context at
        creation). Raw `threading.Thread` instances spawned inside the block do **not** inherit the scope — their calls
        still count in `Stats`.

        Scopes nest: an inner `collect()` block sees only its own calls, while the outer scope sees the union of the
        inner scope's calls plus any direct outer calls.

        :param name: Label for the scoped collector (used in logs/reports).

        Example::

            with Stats.collect("login-flow") as stats:
                client.Auth.login(username="foo", password="bar")

            stats.report()  # Only the login call
            Stats.report()  # All calls ever made
        """
        collector = StatsCollector(name)
        token = _scope_stack.set((*_scope_stack.get(), collector))
        try:
            yield collector
        finally:
            _scope_stack.reset(token)

    @classmethod
    def get(cls, endpoint: str, app_name: str | None = None) -> EndpointStat | None:
        """Return the stat record for the given endpoint key from the global collector.

        :param endpoint: Endpoint string, e.g. `"POST /v1/auth/login"`.
        :param app_name: Restrict search to a specific app. When `None`, the endpoint is looked up across all apps.
                         If the same endpoint exists in multiple apps, `app_name` must be provided.
        """
        return _global.get(endpoint, app_name)

    @classmethod
    def all(cls) -> list[EndpointStat]:
        """Return a snapshot list of all recorded endpoint stats from the global collector."""
        return _global.all()

    @classmethod
    def reset(cls) -> None:
        """Clear all globally recorded stats."""
        _global.reset()

    @classmethod
    def to_dict(cls) -> dict[str, Any]:
        """Serialize the global collector's state to a JSON-safe dict."""
        return _global.to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StatsCollector:
        """Reconstruct a `StatsCollector` from a `to_dict()` payload.

        :param data: Dict produced by `to_dict()` or `Stats.to_dict()`.
        """
        return StatsCollector.from_dict(data)

    @classmethod
    def merge(cls, other: StatsCollector | dict[str, Any]) -> None:
        """Merge another collector's stats into the global total.

        Accepts either a `StatsCollector` instance or a `to_dict()` payload. Count fields merge exactly.
        Response-time aggregates are floating-point sums.

        :param other: A `StatsCollector` or the dict from `to_dict()`.
        """
        _global.merge(other)

    @classmethod
    def aggregate(cls, path: str | Path) -> None:
        """Merge the global snapshot into a shared JSON file (cross-process safe).

        Uses a file lock so multiple processes writing to the same file do not corrupt it.

        :param path: Path to the shared JSON file (created if it does not exist).
        """
        _global.aggregate(path)

    @classmethod
    def dump(cls, path: str | Path, indent: int = 2) -> None:
        """Write the global collector's state to a JSON file.

        :param path: Destination file path (created or overwritten).
        :param indent: Indent level for JSON output.
        """
        _global.dump(path, indent=indent)

    @classmethod
    def show(
        cls, sort_by: SortBy = "calls", reverse: bool = True, endpoint: str | None = None, app_name: str | None = None
    ) -> None:
        """Print a formatted, colored statistics table from the global collector.

        :param sort_by: Column to sort by. One of `"calls"`, `"slowest"`, `"errors"`, or `"endpoint"`.
                        When `"slowest"`, endpoints with no timing data (error-only calls) sort below all timed
                        entries in descending order and above them in ascending order.
        :param reverse: When `True`, sort in descending order.
        :param endpoint: When given, restrict the report to this endpoint and hide the Endpoint column.
        :param app_name: When given, restrict the report to this app.
        """
        _global.show(sort_by=sort_by, reverse=reverse, endpoint=endpoint, app_name=app_name)

    @classmethod
    def enable(cls) -> None:
        """Enable automatic statistics collection (the default state).

        Re-enables collection after a `disable()` call. Existing data is preserved.
        """
        _collection_state.enabled = True

    @classmethod
    def disable(cls) -> None:
        """Disable automatic statistics collection.

        While disabled, API calls made through `EndpointFunc.__call__` are not counted. Existing data is retained.
        Call `Stats.reset()` to clear it. Manual operations (`StatsCollector._record`, `merge`, `aggregate`) are not
        affected.
        """
        _collection_state.enabled = False

    @classmethod
    def is_enabled(cls) -> bool:
        """Return `True` when automatic statistics collection is active."""
        return _collection_state.enabled


def collect_stats(
    f: Callable[Concatenate[EndpointFunc[P], P], RestResponse],
) -> Callable[Concatenate[EndpointFunc[P], P], RestResponse]:
    """Wrap `EndpointFunc.__call__` to record per-endpoint Stats."""

    @wraps(f)
    async def wrapper(self: EndpointFunc[P], *args: P.args, **kwargs: P.kwargs) -> RestResponse:
        response: RestResponse | None = None
        exception: Exception | None = None
        called = False
        try:
            called = True
            response = await f(self, *args, **kwargs)
            return response
        except Exception as e:
            exception = e
            raise
        finally:
            if called:
                try:
                    StatsCollector.record(self, response, exception)
                except Exception as rec_err:
                    logger.warning(f"Failed to record API statistics: {rec_err}")

    return wrapper


def _bucket_index(response_time: float) -> int:
    """Map a response time (seconds) to a DDSketch bucket index."""
    return math.ceil(math.log(max(response_time, _MIN_RESPONSE_TIME)) / _HISTOGRAM_LOG_GAMMA)


def _bucket_value(index: int) -> float:
    """Return the representative value for a bucket index.

    Uses the geometric-center formula so the error is at most `alpha` on both sides of the true value,
    guaranteeing `|representative - v| <= alpha * v` for any `v` in the bucket.
    """
    return 2 * _HISTOGRAM_GAMMA**index / (_HISTOGRAM_GAMMA + 1)


def _atomic_write(path: Path, data: str, encoding: str = "utf-8") -> None:
    """Write `data` to `path` atomically using a temp file and `os.replace`.

    Prevents a partial write from clobbering existing content on crash.

    :param path: Destination file path.
    :param data: Text content to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
    )

    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, path)

    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _ms(seconds: float | None) -> str:
    """Format seconds as a millisecond string, or `"-"` when absent."""
    return f"{seconds * 1000:.2f}" if seconds is not None else "-"


def _format_report(stats: list[EndpointStat], sort_by: SortBy, reverse: bool, hide_endpoint_col: bool = False) -> str:
    """Build a fixed-width, ANSI-colored table for a single app's stats.

    This is a pure string-building function (no I/O) so it can be unit-tested directly.

    :param stats: List of `EndpointStat` records for one app.
    :param sort_by: Sort key — one of `"calls"`, `"slowest"`, `"errors"`, `"endpoint"`.
    :param reverse: Descending order when `True`.
    :param hide_endpoint_col: When `True`, omit the Endpoint column from the output.
    """

    def sort_key(s: EndpointStat) -> Any:
        if sort_by == "calls":
            return s.num_calls
        if sort_by == "slowest":
            return s.avg_response_time if s.avg_response_time is not None else -1.0
        if sort_by == "errors":
            return s.num_errors + s.num_5xx
        return s.endpoint  # "endpoint"

    sorted_stats = sorted(stats, key=sort_key, reverse=reverse)

    col_start = 1 if hide_endpoint_col else 0
    col_headers = _COL_HEADERS[col_start:]
    col_4xx = _COL_4XX - col_start
    col_5xx = _COL_5XX - col_start
    col_error = _COL_ERROR - col_start
    lat_col_start = _LATENCY_COL_START - col_start

    # Build raw cell values first so we can measure column widths
    rows: list[tuple[str, ...]] = []
    for s in sorted_stats:
        pcts = s._percentiles(50, 95, 99)
        full_row: tuple[str, ...] = (
            s.endpoint,
            str(s.num_calls),
            str(s.num_1xx),
            str(s.num_2xx),
            str(s.num_3xx),
            str(s.num_4xx),
            str(s.num_5xx),
            str(s.num_errors),
            _ms(s.min_response_time),
            _ms(s.avg_response_time),
            _ms(s.max_response_time),
            _ms(pcts[50]),
            _ms(pcts[95]),
            _ms(pcts[99]),
        )
        rows.append(full_row[col_start:])

    # Column widths: max of header and all data values
    widths = [max([len(h), *(len(row[i]) for row in rows)]) for i, h in enumerate(col_headers)]

    def _row(cells: tuple[str, ...], cell_colors: dict[int, str] | None = None) -> str:
        parts: list[str] = []
        for i, (cell, w) in enumerate(zip(cells, widths)):
            # Left-align the endpoint column (only present when not hidden); right-align all others
            aligned = cell.ljust(w) if (i == 0 and not hide_endpoint_col) else cell.rjust(w)
            if cell_colors and i in cell_colors:
                aligned = color(aligned, cell_colors[i])
            parts.append(aligned)
        return " | ".join(parts)

    sep = "-+-".join("-" * w for w in widths)

    non_lat_widths = widths[:lat_col_start]
    lat_widths = widths[lat_col_start:]
    non_lat_content_len = sum(non_lat_widths) + (len(non_lat_widths) - 1) * 3
    lat_content_len = sum(lat_widths) + (len(lat_widths) - 1) * 3

    # "Latency (ms)" label centered above the latency columns
    latency_label_row = " " * (non_lat_content_len + 3) + "Latency (ms)".center(lat_content_len)
    # Continuous dash line spanning the latency section (absorbs the trailing "-" of the "-+-" connector)
    latency_sep_row = " " * (non_lat_content_len + 2) + "-" * (lat_content_len + 1)

    non_lat_header_parts = [
        col_headers[i].ljust(w) if (i == 0 and not hide_endpoint_col) else col_headers[i].rjust(w)
        for i, w in enumerate(non_lat_widths)
    ]
    lat_header_parts = [h.center(w) for h, w in zip(col_headers[lat_col_start:], lat_widths)]
    header = " | ".join(non_lat_header_parts + lat_header_parts)
    lines = [
        color(latency_label_row, ColorCodes.CYAN, bold=True),
        color(latency_sep_row, ColorCodes.CYAN, bold=True),
        color(header, ColorCodes.CYAN, bold=True),
        color(sep, ColorCodes.CYAN, bold=True),
    ]
    for s, cells in zip(sorted_stats, rows):
        cell_colors: dict[int, str] = {}
        if s.num_4xx > 0:
            cell_colors[col_4xx] = ColorCodes.YELLOW
        if s.num_5xx > 0:
            cell_colors[col_5xx] = ColorCodes.RED
        if s.num_errors > 0:
            cell_colors[col_error] = ColorCodes.RED
        lines.append(_row(cells, cell_colors))

    return "\n".join(lines)
