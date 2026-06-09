"""Unit tests for Stats.py"""

from __future__ import annotations

import asyncio
import json
import math
import re
import threading
from collections.abc import Generator
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from common_libs.ansi_colors import ColorCodes
from common_libs.clients.rest_client import RestResponse
from common_libs.clients.rest_client.ext import ResponseExt
from httpx import AsyncClient, Client, ConnectError, Request
from pytest_mock import MockerFixture

from openapi_test_client.libraries.core.base import APIBase, APIClient
from openapi_test_client.libraries.core.endpoints.stats import (
    _HISTOGRAM_REL_ACCURACY,
    EndpointStat,
    Stats,
    StatsCollector,
    _active_collectors,
    _bucket_index,
    _bucket_value,
    _format_report,
    _scope_stack,
)

pytestmark = [pytest.mark.unittest]

_endpoint = "GET /v1/something"
_APP_NAME = "test"


def _make_mock_response(mocker: MockerFixture, status_code: int = 200, response_time: float = 0.1) -> MagicMock:
    """Return a mock ResponseExt configured to produce a valid RestResponse."""
    mock = mocker.MagicMock(spec=ResponseExt)
    mock.status_code = status_code
    mock.is_success = 200 <= status_code < 300
    mock.is_stream = False
    mock.elapsed.total_seconds.return_value = response_time
    mock.request.request_id = "test-request-id"
    return mock


@pytest.fixture(autouse=True)
def reset_global_stats() -> Generator[None, None, None]:
    """Reset the global Stats collector and restore enabled state before and after each test."""
    Stats.reset()
    Stats.enable()
    yield
    Stats.reset()
    Stats.enable()


class TestEndpointStat:
    """Tests for EndpointStat record operations."""

    def test_record_response_buckets_2xx(self) -> None:
        """Test that 2xx status codes increment num_2xx and num_calls."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        s.record_response(200, 0.1)
        s.record_response(201, 0.2)
        assert s.num_calls == 2
        assert s.num_2xx == 2
        assert s.num_1xx == s.num_3xx == s.num_4xx == s.num_5xx == s.num_errors == 0

    def test_record_response_buckets_status_classes(self) -> None:
        """Test that each HTTP status class increments the correct counter."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        for code, attr in [
            (100, "num_1xx"),
            (200, "num_2xx"),
            (301, "num_3xx"),
            (404, "num_4xx"),
            (503, "num_5xx"),
            (0, "num_unknown_status"),
        ]:
            s.record_response(code, 0.1)
            assert getattr(s, attr) == 1, f"{code} should increment {attr}"

    def test_record_response_updates_timing(self) -> None:
        """Test that response_time accumulates correctly and computed properties are correct."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        s.record_response(200, 0.1)
        s.record_response(200, 0.3)
        assert s._time_count == 2
        assert math.isclose(s._time_sum, 0.4)
        assert math.isclose(s.min_response_time, 0.1)
        assert math.isclose(s.max_response_time, 0.3)
        assert math.isclose(s.avg_response_time, 0.2)

    def test_record_response_none_response_time_skips_timing(self) -> None:
        """Test that a None response_time counts the call and status class but skips timing accumulators."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        s.record_response(200, None)
        assert s.num_calls == 1
        assert s.num_2xx == 1
        assert s._time_count == 0
        assert s.avg_response_time is None

    def test_record_error(self) -> None:
        """Test that record_error increments num_calls and num_errors only."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        s.record_error()
        assert s.num_calls == 1
        assert s.num_errors == 1
        assert s.num_1xx == s.num_2xx == s.num_3xx == s.num_4xx == s.num_5xx == 0
        assert s._time_count == 0

    def test_computed_properties_return_none_when_no_samples(self) -> None:
        """Test that avg/min/max response time properties return None when no timed samples exist."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        assert s.avg_response_time is None
        assert s.min_response_time is None
        assert s.max_response_time is None

    def test_to_dict_from_dict_round_trip(self) -> None:
        """Test that to_dict/from_dict is an exact round-trip."""
        s = EndpointStat(app_name="app", endpoint="POST /login")
        s.record_response(200, 0.15)
        s.record_response(404, 0.05)
        s.record_error()
        restored = EndpointStat.from_dict(s.to_dict())
        assert restored.app_name == s.app_name
        assert restored.endpoint == s.endpoint
        assert restored.num_calls == s.num_calls
        assert restored.num_2xx == s.num_2xx
        assert restored.num_4xx == s.num_4xx
        assert restored.num_errors == s.num_errors
        assert math.isclose(restored._time_sum, s._time_sum)
        assert math.isclose(restored._time_min, s._time_min)

    def test_to_dict_from_dict_inf_sentinel(self) -> None:
        """Test that math.inf is stored as None in to_dict and restored correctly from None."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        d = s.to_dict()
        assert d["_time_min"] is None  # math.inf → None in JSON
        restored = EndpointStat.from_dict(d)
        assert math.isinf(restored._time_min)

    def test_from_dict_tolerates_missing_keys(self) -> None:
        """Test that from_dict uses defaults for missing keys (cross-version compatibility)."""
        partial = {"app_name": "app", "endpoint": "GET /x"}
        stat = EndpointStat.from_dict(partial)
        assert stat.app_name == "app"
        assert stat.endpoint == "GET /x"
        assert stat.num_calls == 0
        assert math.isinf(stat._time_min)

    def test_from_dict_ignores_unknown_keys(self) -> None:
        """Test that from_dict silently ignores keys that are not dataclass fields."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        s.record_response(200, 0.1)
        d = {**s.to_dict(), "future_field": "some_value", "another_new_field": 99}
        restored = EndpointStat.from_dict(d)
        assert restored.num_calls == s.num_calls
        assert math.isclose(restored._time_sum, s._time_sum)

    def test_percentile_properties_return_none_when_no_samples(self) -> None:
        """Test that p50/p95/p99 return None when no timed samples have been recorded."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        assert s.p50_response_time is None
        assert s.p95_response_time is None
        assert s.p99_response_time is None

    def test_percentile_single_sample(self) -> None:
        """Test that all percentiles converge to approximately the single recorded response time."""
        rt = 0.05
        s = EndpointStat(app_name="app", endpoint="GET /x")
        s.record_response(200, rt)
        assert s.p50_response_time is not None
        assert math.isclose(s.p50_response_time, rt, rel_tol=_HISTOGRAM_REL_ACCURACY)
        assert math.isclose(s.p95_response_time, rt, rel_tol=_HISTOGRAM_REL_ACCURACY)
        assert math.isclose(s.p99_response_time, rt, rel_tol=_HISTOGRAM_REL_ACCURACY)

    def test_percentile_ordering(self) -> None:
        """Test that p50 <= p95 <= p99 for any non-empty distribution."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        for i in range(1, 101):
            s.record_response(200, i / 1000)
        assert s.p50_response_time <= s.p95_response_time <= s.p99_response_time

    def test_percentile_known_uniform_distribution(self) -> None:
        """Test that percentile estimates are within the guaranteed relative error for a uniform distribution."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        n = 100
        for i in range(1, n + 1):
            s.record_response(200, i / 1000)  # 0.001s … 0.100s

        # True nearest-rank values for 100 uniform samples: p50=0.050, p95=0.095, p99=0.099
        assert math.isclose(s.p50_response_time, 0.050, rel_tol=_HISTOGRAM_REL_ACCURACY * 2)
        assert math.isclose(s.p95_response_time, 0.095, rel_tol=_HISTOGRAM_REL_ACCURACY * 2)
        assert math.isclose(s.p99_response_time, 0.099, rel_tol=_HISTOGRAM_REL_ACCURACY * 2)

    def test_to_dict_from_dict_preserves_percentiles(self) -> None:
        """Test that percentile estimates survive a to_dict/from_dict round-trip."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        for i in range(1, 101):
            s.record_response(200, i / 1000)

        restored = EndpointStat.from_dict(s.to_dict())
        assert restored.p50_response_time is not None
        assert math.isclose(restored.p50_response_time, s.p50_response_time)
        assert math.isclose(restored.p95_response_time, s.p95_response_time)
        assert math.isclose(restored.p99_response_time, s.p99_response_time)

    def test_from_dict_coerces_string_bucket_keys(self) -> None:
        """Test that from_dict correctly handles string bucket keys produced by JSON serialization."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        for i in range(1, 101):
            s.record_response(200, i / 1000)

        # Simulate a JSON round-trip where int dict keys become strings
        payload = json.loads(json.dumps(s.to_dict()))
        assert all(isinstance(k, str) for k in payload["_time_buckets"])

        restored = EndpointStat.from_dict(payload)
        assert all(isinstance(k, int) for k in restored._time_buckets)
        assert math.isclose(restored.p50_response_time, s.p50_response_time)

    def test_none_response_time_does_not_contribute_to_percentiles(self) -> None:
        """Test that calls with None response time leave percentiles as None."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        s.record_response(200, None)
        assert s.p50_response_time is None
        assert s.p95_response_time is None
        assert s.p99_response_time is None

    def test_copy_returns_independent_snapshot(self) -> None:
        """Test that copy() produces an independent deep copy that does not reflect later mutations."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        s.record_response(200, 0.1)
        snapshot = s.copy()
        s.record_response(200, 0.2)
        assert snapshot.num_calls == 1
        assert snapshot._time_count == 1

    def test_percentiles_batch_matches_individual_properties(self) -> None:
        """Test that _percentiles(50, 95, 99) returns the same values as p50/p95/p99 properties."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        for i in range(1, 101):
            s.record_response(200, i / 1000)
        pcts = s._percentiles(50, 95, 99)
        assert pcts[50] == s.p50_response_time
        assert pcts[95] == s.p95_response_time
        assert pcts[99] == s.p99_response_time

    def test_percentiles_returns_none_for_all_when_no_samples(self) -> None:
        """Test that _percentiles returns None for every requested q when no samples exist."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        pcts = s._percentiles(50, 95, 99)
        assert pcts == {50: None, 95: None, 99: None}


class TestEndpointStatMerge:
    """Tests for EndpointStat.merge_in() — exact cross-process merge math."""

    def test_merge_counts_are_exact(self) -> None:
        """Test that all integer counters are summed exactly on merge."""
        a = EndpointStat(app_name="app", endpoint="GET /x")
        a.record_response(200, 0.1)
        a.record_response(500, None)
        a.record_error()

        b = EndpointStat(app_name="app", endpoint="GET /x")
        b.record_response(200, 0.3)
        b.record_response(404, None)

        a.merge_in(b)
        assert a.num_calls == 5
        assert a.num_2xx == 2
        assert a.num_4xx == 1
        assert a.num_5xx == 1
        assert a.num_errors == 1

    def test_merge_average_is_exact_not_lossy(self) -> None:
        """Test that avg_response_time after merge is exact (weighted by count), not (a+b)/2.

        Uses counts 1 and 3 so that the naive (a+b)/2 formula gives a wrong result,
        proving the raw sum/count storage is used instead.
        """
        a = EndpointStat(app_name="app", endpoint="GET /x")
        a.record_response(200, 0.1)  # count=1, sum=0.1

        b = EndpointStat(app_name="app", endpoint="GET /x")
        for _ in range(3):
            b.record_response(200, 0.5)  # count=3, sum=1.5

        a.merge_in(b)
        # Correct: (0.1 + 1.5) / 4 = 0.4
        # Naive (a+b)/2 would give: (0.1 + 0.5) / 2 = 0.3 — WRONG
        assert math.isclose(a.avg_response_time, 0.4)

    def test_merge_min_max_are_global(self) -> None:
        """Test that min/max after merge reflect the global extreme, not per-worker extremes."""
        a = EndpointStat(app_name="app", endpoint="GET /x")
        a.record_response(200, 0.5)
        a.record_response(200, 1.0)

        b = EndpointStat(app_name="app", endpoint="GET /x")
        b.record_response(200, 0.1)
        b.record_response(200, 2.0)

        a.merge_in(b)
        assert math.isclose(a.min_response_time, 0.1)
        assert math.isclose(a.max_response_time, 2.0)

    def test_merge_with_empty_other_is_identity(self) -> None:
        """Test that merging an empty EndpointStat leaves the original unchanged."""
        a = EndpointStat(app_name="app", endpoint="GET /x")
        a.record_response(200, 0.1)
        original_calls = a.num_calls
        original_sum = a._time_sum

        empty = EndpointStat(app_name="app", endpoint="GET /x")
        a.merge_in(empty)
        assert a.num_calls == original_calls
        assert math.isclose(a._time_sum, original_sum)

    def test_merge_is_commutative(self) -> None:
        """Test that merge(A, B) and merge(B, A) produce the same avg/min/max."""

        def make() -> tuple[EndpointStat, EndpointStat]:
            x = EndpointStat(app_name="app", endpoint="GET /x")
            x.record_response(200, 0.1)
            y = EndpointStat(app_name="app", endpoint="GET /x")
            y.record_response(200, 0.3)
            y.record_response(200, 0.5)
            return x, y

        a, b = make()
        a.merge_in(b)

        c, d = make()
        d.merge_in(c)

        assert math.isclose(a.avg_response_time, d.avg_response_time)
        assert math.isclose(a.min_response_time, d.min_response_time)
        assert math.isclose(a.max_response_time, d.max_response_time)

    def test_merge_percentiles_reflect_combined_distribution(self) -> None:
        """Test that percentiles after merge reflect the combined distribution within the guaranteed error."""
        # Two halves of a 1..100 uniform distribution; merged they should give the same percentiles
        # as a single stat that recorded all 100 samples
        a = EndpointStat(app_name="app", endpoint="GET /x")
        for i in range(1, 51):
            a.record_response(200, i / 1000)

        b = EndpointStat(app_name="app", endpoint="GET /x")
        for i in range(51, 101):
            b.record_response(200, i / 1000)

        a.merge_in(b)

        assert math.isclose(a.p50_response_time, 0.050, rel_tol=_HISTOGRAM_REL_ACCURACY * 2)
        assert math.isclose(a.p95_response_time, 0.095, rel_tol=_HISTOGRAM_REL_ACCURACY * 2)
        assert math.isclose(a.p99_response_time, 0.099, rel_tol=_HISTOGRAM_REL_ACCURACY * 2)

    def test_merge_percentiles_are_commutative(self) -> None:
        """Test that merge(A, B) and merge(B, A) produce the same percentile estimates."""

        def make() -> tuple[EndpointStat, EndpointStat]:
            x = EndpointStat(app_name="app", endpoint="GET /x")
            for i in range(1, 51):
                x.record_response(200, i / 1000)
            y = EndpointStat(app_name="app", endpoint="GET /x")
            for i in range(51, 101):
                y.record_response(200, i / 1000)
            return x, y

        a, b = make()
        a.merge_in(b)

        c, d = make()
        d.merge_in(c)

        assert math.isclose(a.p50_response_time, d.p50_response_time)
        assert math.isclose(a.p95_response_time, d.p95_response_time)
        assert math.isclose(a.p99_response_time, d.p99_response_time)


class TestStatsCollector:
    """Tests for StatsCollector operations."""

    def test_record_creates_endpoint_stat_on_first_call(self) -> None:
        """Test that the first _record call for an endpoint creates an EndpointStat."""
        c = StatsCollector()
        c._record("app", "GET /x", status_code=200, response_time=0.1, is_error=False)
        assert c.get("GET /x") is not None

    def test_get_by_endpoint_across_apps(self) -> None:
        """Test that get() without app_name finds a uniquely-matched endpoint and returns None when missing."""
        c = StatsCollector()
        c._record("app1", "GET /x", status_code=200, response_time=0.1, is_error=False)
        c._record("app2", "POST /y", status_code=201, response_time=0.2, is_error=False)
        assert c.get("GET /x") is not None
        assert c.get("POST /y") is not None
        assert c.get("GET /missing") is None

    def test_get_raises_when_endpoint_exists_in_multiple_apps(self) -> None:
        """Test that get() without app_name raises ValueError when the endpoint is ambiguous."""
        c = StatsCollector()
        c._record("app1", "GET /x", status_code=200, response_time=0.1, is_error=False)
        c._record("app2", "GET /x", status_code=200, response_time=0.2, is_error=False)
        with pytest.raises(ValueError, match="app_name must be provided"):
            c.get("GET /x")

    def test_get_by_endpoint_and_app_name(self) -> None:
        """Test that get() with app_name restricts the search to that app."""
        c = StatsCollector()
        c._record("app1", "GET /x", status_code=200, response_time=0.1, is_error=False)
        c._record("app2", "GET /x", status_code=404, response_time=0.2, is_error=False)
        stat1 = c.get("GET /x", app_name="app1")
        stat2 = c.get("GET /x", app_name="app2")
        assert stat1 is not None and stat1.num_2xx == 1
        assert stat2 is not None and stat2.num_4xx == 1

    def test_reset_clears_all_stats(self) -> None:
        """Test that reset() removes all recorded stats."""
        c = StatsCollector()
        c._record("app", "GET /x", status_code=200, response_time=0.1, is_error=False)
        assert len(c.all()) == 1
        c.reset()
        assert len(c.all()) == 0
        assert c.get("GET /x") is None

    def test_to_dict_from_dict_round_trip(self) -> None:
        """Test that StatsCollector to_dict/from_dict is an exact round-trip."""
        c = StatsCollector("test-collector")
        c._record("app", "GET /x", status_code=200, response_time=0.1, is_error=False)
        c._record("app", "POST /y", status_code=500, response_time=None, is_error=False)
        restored = StatsCollector.from_dict(c.to_dict())
        assert restored._name == "test-collector"
        assert restored.get("GET /x").num_calls == 1
        assert restored.get("POST /y").num_5xx == 1

    def test_merge_from_dict_payload(self) -> None:
        """Test that merge() with a dict payload combines stats exactly."""
        a = StatsCollector()
        a._record("app", "GET /x", status_code=200, response_time=0.1, is_error=False)

        b = StatsCollector()
        b._record("app", "GET /x", status_code=200, response_time=0.3, is_error=False)

        a.merge(b.to_dict())
        stat = a.get("GET /x")
        assert stat.num_calls == 2
        assert math.isclose(stat.avg_response_time, 0.2)

    def test_merge_from_another_collector(self) -> None:
        """Test that merge() with a StatsCollector instance works correctly."""
        a = StatsCollector()
        a._record("app", "GET /x", status_code=200, response_time=0.2, is_error=False)

        b = StatsCollector()
        b._record("app", "GET /x", status_code=404, response_time=None, is_error=False)

        a.merge(b)
        stat = a.get("GET /x")
        assert stat.num_calls == 2
        assert stat.num_2xx == 1
        assert stat.num_4xx == 1

    def test_from_dict_empty_payload_returns_empty_collector(self) -> None:
        """Test that StatsCollector.from_dict with an empty dict produces an empty collector."""
        c = StatsCollector.from_dict({})
        assert len(c.all()) == 0

    def test_from_dict_null_stats_value_returns_empty_collector(self) -> None:
        """Test that StatsCollector.from_dict tolerates a null stats value."""
        c = StatsCollector.from_dict({"name": "test", "stats": None})
        assert len(c.all()) == 0

    def test_get_returns_independent_copy(self) -> None:
        """Test that get() returns an independent snapshot that is not mutated by later records."""
        c = StatsCollector()
        c._record("app", "GET /x", status_code=200, response_time=0.1, is_error=False)
        snapshot = c.get("GET /x")
        c._record("app", "GET /x", status_code=200, response_time=0.2, is_error=False)
        assert snapshot.num_calls == 1

    def test_all_returns_independent_copies(self) -> None:
        """Test that all() returns independent snapshots that are not mutated by later records."""
        c = StatsCollector()
        c._record("app", "GET /x", status_code=200, response_time=0.1, is_error=False)
        snapshots = c.all()
        c._record("app", "GET /x", status_code=200, response_time=0.2, is_error=False)
        assert snapshots[0].num_calls == 1

    def test_dump_writes_json_reloadable_via_from_dict(self, tmp_path: Any) -> None:
        """Test that dump() writes a pretty-printed JSON file reloadable via from_dict."""
        c = StatsCollector("test-dump")
        c._record("app", "GET /x", status_code=200, response_time=0.1, is_error=False)
        path = tmp_path / "dump.json"
        c.dump(path)
        assert path.exists()
        reloaded = StatsCollector.from_dict(json.loads(path.read_text()))
        assert reloaded.get("GET /x").num_calls == 1


class TestStatsCollectorThreadSafety:
    """Tests for thread-safe concurrent writes."""

    def test_concurrent_writes_no_data_loss(self) -> None:
        """Test that N concurrent threads recording to one collector produce exactly N calls."""
        c = StatsCollector()
        num_threads = 32
        calls_per_thread = 50

        def record_many() -> None:
            for _ in range(calls_per_thread):
                c._record("app", "GET /x", status_code=200, response_time=0.01, is_error=False)

        with ThreadPoolExecutor(max_workers=num_threads) as pool:
            futures = [pool.submit(record_many) for _ in range(num_threads)]
            for f in futures:
                f.result()

        assert c.get("GET /x").num_calls == num_threads * calls_per_thread


class TestCollectStatsScope:
    """Tests for the Stats.collect() context manager."""

    def _direct_record(self, app: str = _APP_NAME, key: str = _endpoint) -> None:
        """Record directly into the active collectors without going through EndpointFunc."""
        for c in _active_collectors():
            c._record(app, key, status_code=200, response_time=0.1, is_error=False)

    def test_scope_sees_only_calls_within_block(self) -> None:
        """Test that the scoped collector records only calls made inside its block."""
        # Call outside scope
        self._direct_record()

        with Stats.collect() as stats:
            self._direct_record()
            self._direct_record()

        # Scope: 2 calls; global: 3 calls
        assert stats.get(_endpoint).num_calls == 2
        assert Stats.get(_endpoint).num_calls == 3

    def test_global_rolls_up_all_scoped_calls(self) -> None:
        """Test that every call inside a scope also increments the global collector."""
        with Stats.collect() as stats:
            self._direct_record()

        assert stats.get(_endpoint).num_calls == 1
        assert Stats.get(_endpoint).num_calls == 1

    def test_nested_scopes(self) -> None:
        """Test that inner scope sees only its calls, outer sees inner + outer calls."""
        with Stats.collect("outer") as outer:
            self._direct_record()  # only outer sees this
            with Stats.collect("inner") as inner:
                self._direct_record()  # both outer and inner see this
                self._direct_record()

        assert inner.get(_endpoint).num_calls == 2
        assert outer.get(_endpoint).num_calls == 3
        assert Stats.get(_endpoint).num_calls == 3

    def test_stats_collect_creates_scoped_collector(self) -> None:
        """Test that Stats.collect() yields a scoped collector that records its calls."""
        with Stats.collect() as stats:
            self._direct_record()

        assert stats.get(_endpoint).num_calls == 1

    async def test_asyncio_gather_propagates_scope(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that asyncio.gather tasks inherit the enclosing Stats.collect() scope."""
        mocker.patch.object(AsyncClient, "request", side_effect=lambda *a, **k: _make_mock_response(mocker))
        instance = api_class_async(api_client_async)

        with Stats.collect() as stats:
            await asyncio.gather(*[instance.get_something() for _ in range(5)])

        assert stats.get(_endpoint).num_calls == 5
        assert Stats.get(_endpoint).num_calls == 5

    def test_raw_thread_bypasses_scope_but_hits_global(self) -> None:
        """Test that raw threads spawned inside a scope don't see the scope but still hit global."""
        recorded_in_scope: list[bool] = []

        def thread_func() -> None:
            recorded_in_scope.append(len(_scope_stack.get()) > 0)
            # Record directly into whichever collectors are visible to this thread

            for c in _active_collectors():
                c._record(_APP_NAME, _endpoint, status_code=200, response_time=0.1, is_error=False)

        with Stats.collect() as stats:
            t = threading.Thread(target=thread_func)
            t.start()
            t.join()

        # The thread does NOT see the scope (ContextVar not inherited by raw threads)
        assert recorded_in_scope == [False]
        # The thread still hits the global
        assert Stats.get(_endpoint).num_calls == 1
        # But NOT the scoped collector
        assert stats.get(_endpoint) is None


class TestCollectStatsDecorator:
    """Tests for the collect_stats decorator on EndpointFunc.__call__."""

    def test_sync_call_records_2xx_stats(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that a successful sync API call is recorded with correct status and timing."""
        mocker.patch.object(Client, "request", side_effect=lambda *a, **k: _make_mock_response(mocker, 200, 0.1))
        instance = api_class(api_client)
        instance.get_something()

        stat = Stats.get(_endpoint)
        assert stat is not None
        assert stat.num_calls == 1
        assert stat.num_2xx == 1
        assert stat.num_errors == 0
        assert stat.avg_response_time is not None

    def test_sync_call_records_5xx_stats(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that a 5xx sync API call increments num_5xx."""
        mocker.patch.object(Client, "request", side_effect=lambda *a, **k: _make_mock_response(mocker, 503, 0.2))
        instance = api_class(api_client)
        instance.get_something()

        stat = Stats.get(_endpoint)
        assert stat.num_calls == 1
        assert stat.num_5xx == 1
        assert stat.num_2xx == 0

    def test_sync_call_error_records_num_errors(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that an HTTPError during a sync call records num_errors and re-raises."""
        mock_request = mocker.MagicMock(spec=Request)
        err = ConnectError("timeout")
        err.request = mock_request
        mocker.patch.object(Client, "request", side_effect=err)
        instance = api_class(api_client)

        with pytest.raises(ConnectError):
            instance.get_something()

        stat = Stats.get(_endpoint)
        assert stat is not None
        assert stat.num_calls == 1
        assert stat.num_errors == 1
        assert stat.avg_response_time is None

    def test_stats_recording_failure_is_swallowed(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that a bug in StatsCollector.record never propagates to the caller."""
        mocker.patch.object(Client, "request", side_effect=lambda *a, **k: _make_mock_response(mocker))
        mocker.patch.object(
            StatsCollector,
            "record",
            side_effect=RuntimeError("stats bug"),
        )
        instance = api_class(api_client)
        # The call must succeed even though stats recording raises internally
        r = instance.get_something()
        assert isinstance(r, RestResponse)

    def test_with_repeat_counts_each_attempt(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_repeat(num=N) records N individual calls in Stats."""
        mocker.patch.object(Client, "request", side_effect=lambda *a, **k: _make_mock_response(mocker))
        instance = api_class(api_client)
        instance.get_something.with_repeat(num=3)()

        stat = Stats.get(_endpoint)
        assert stat.num_calls == 3

    def test_with_concurrency_propagates_scope(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that with_concurrency(num=N) propagates the Stats.collect() scope to worker threads."""
        mocker.patch.object(Client, "request", side_effect=lambda *a, **k: _make_mock_response(mocker))
        instance = api_class(api_client)

        with Stats.collect() as stats:
            instance.get_something.with_concurrency(num=4)()

        assert stats.get(_endpoint).num_calls == 4
        assert Stats.get(_endpoint).num_calls == 4

    async def test_async_call_records_stats(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that a successful async API call is recorded in Stats."""
        mocker.patch.object(AsyncClient, "request", side_effect=lambda *a, **k: _make_mock_response(mocker))
        instance = api_class_async(api_client_async)
        await instance.get_something()

        stat = Stats.get(_endpoint)
        assert stat is not None
        assert stat.num_calls == 1
        assert stat.num_2xx == 1

    async def test_scoped_and_global_both_record_on_async_call(
        self, mocker: MockerFixture, api_client_async: APIClient, api_class_async: type[APIBase]
    ) -> None:
        """Test that an async call within a scope records to both the scope and global."""
        mocker.patch.object(AsyncClient, "request", side_effect=lambda *a, **k: _make_mock_response(mocker))
        instance = api_class_async(api_client_async)

        with Stats.collect() as stats:
            await instance.get_something()

        assert stats.get(_endpoint).num_calls == 1
        assert Stats.get(_endpoint).num_calls == 1


class TestStatsAggregate:
    """Tests for file-backed cross-process aggregation."""

    def test_aggregate_creates_file_on_first_call(self, tmp_path: Any) -> None:
        """Test that aggregate() creates the shared file when it does not exist."""
        c = StatsCollector()
        c._record("app", "GET /x", status_code=200, response_time=0.1, is_error=False)
        path = tmp_path / "stats.json"
        c.aggregate(path)
        assert path.exists()

    def test_aggregate_leaves_no_temp_files(self, tmp_path: Any) -> None:
        """Test that aggregate() leaves no leftover .tmp files in the target directory."""
        c = StatsCollector()
        c._record("app", "GET /x", status_code=200, response_time=0.1, is_error=False)
        path = tmp_path / "stats.json"
        c.aggregate(path)
        leftover = list(tmp_path.glob("*.tmp"))
        assert leftover == [], f"Unexpected temp files: {leftover}"

    def test_aggregate_preserves_existing_on_repeated_calls(self, tmp_path: Any) -> None:
        """Test that repeated aggregate() calls accumulate totals without corrupting the file."""
        path = tmp_path / "stats.json"

        c = StatsCollector()
        c._record("app", "GET /x", status_code=200, response_time=0.1, is_error=False)
        c.aggregate(path)

        c2 = StatsCollector()
        c2._record("app", "GET /x", status_code=200, response_time=0.3, is_error=False)
        c2.aggregate(path)

        result = Stats.from_dict(json.loads(path.read_text()))
        stat = result.get("GET /x")
        assert stat is not None
        assert stat.num_calls == 2
        assert math.isclose(stat.avg_response_time, 0.2)

    def test_aggregate_merges_multiple_collectors_exactly(self, tmp_path: Any) -> None:
        """Test that aggregating two collectors into the same file produces exact merged totals."""
        path = tmp_path / "stats.json"

        a = StatsCollector()
        a._record("app", "GET /x", status_code=200, response_time=0.1, is_error=False)
        a.aggregate(path)

        b = StatsCollector()
        b._record("app", "GET /x", status_code=200, response_time=0.3, is_error=False)
        b.aggregate(path)

        result = Stats.from_dict(__import__("json").loads(path.read_text()))
        stat = result.get("GET /x")
        assert stat.num_calls == 2
        # Exact average: (0.1 + 0.3) / 2 = 0.2
        assert math.isclose(stat.avg_response_time, 0.2)
        assert math.isclose(stat.min_response_time, 0.1)
        assert math.isclose(stat.max_response_time, 0.3)


class TestFormatReport:
    """Tests for the _format_report table builder."""

    def _make_stat(self, endpoint: str = "GET /x", calls: int = 5, rt: float = 0.1) -> EndpointStat:
        s = EndpointStat(app_name="app", endpoint=endpoint)
        for _ in range(calls):
            s.record_response(200, rt)
        return s

    def test_format_report_contains_all_column_headers(self) -> None:
        """Test that all expected column headers appear in the formatted report."""
        output = _format_report([self._make_stat()], sort_by="calls", reverse=True)
        for header in (
            "Endpoint",
            "Calls",
            "1xx",
            "2xx",
            "3xx",
            "4xx",
            "5xx",
            "Error",
            "Latency (ms)",
            "min",
            "avg",
            "max",
            "p50",
            "p95",
            "p99",
        ):
            assert header in output

    def test_format_report_contains_endpoint(self) -> None:
        """Test that the endpoint key appears in the formatted output."""
        output = _format_report([self._make_stat("POST /login")], sort_by="calls", reverse=True)
        assert "POST /login" in output

    def test_format_report_sort_by_calls_descending(self) -> None:
        """Test that sort_by='calls' places the highest-call endpoint first."""
        busy = self._make_stat("POST /busy", calls=10)
        idle = self._make_stat("GET /idle", calls=1)
        output = _format_report([idle, busy], sort_by="calls", reverse=True)
        assert output.index("POST /busy") < output.index("GET /idle")

    def test_format_report_sort_by_endpoint_ascending(self) -> None:
        """Test that sort_by='endpoint' sorts alphabetically when reverse=False."""
        b_stat = self._make_stat("POST /beta")
        a_stat = self._make_stat("GET /alpha")
        output = _format_report([b_stat, a_stat], sort_by="endpoint", reverse=False)
        assert output.index("GET /alpha") < output.index("POST /beta")

    def test_format_report_shows_dash_for_missing_timing(self) -> None:
        """Test that '-' appears in timing columns when all calls are errors."""
        s = EndpointStat(app_name="app", endpoint="GET /x")
        s.record_error()
        output = _format_report([s], sort_by="calls", reverse=True)
        assert "-" in output

    def test_format_report_percentile_columns_show_values_when_timed(self) -> None:
        """Test that p50/p95/p99 columns show numeric values when timed calls exist."""
        output = _format_report([self._make_stat(calls=10, rt=0.1)], sort_by="calls", reverse=True)
        # Each cell is formatted as a 2-decimal ms string; just confirm non-dash values appear
        assert "p50" in output
        assert "p95" in output
        assert "p99" in output
        # The data row should not have "-" for those columns (there are timed samples)
        data_line = output.splitlines()[-1]
        # There are 14 columns; all timing cols have values so "-" should appear 0 times in data row
        assert "-" not in data_line

    def test_format_report_colors_only_related_columns(self) -> None:
        """Test that Yellow and Red are applied only to the 4xx, 5xx, and Error cells."""
        s = EndpointStat(app_name="app", endpoint="GET /mixed")
        s.record_response(200, 0.1)
        s.record_response(404, 0.2)
        s.record_response(503, 0.3)
        s.record_error()
        output = _format_report([s], sort_by="calls", reverse=True)

        # Skip the header and separator; the data row is the last line
        data_line = output.splitlines()[-1]

        # Each color() call appends one DEFAULT reset code; exactly 3 cells are colored
        # (4xx=yellow, 5xx=red, Error=red)
        assert data_line.count(ColorCodes.DEFAULT) == 3
        # 5xx and Error cells are red; the 4xx cell is yellow
        assert data_line.count(ColorCodes.RED) == 2
        assert data_line.count(ColorCodes.YELLOW) == 1

    def test_format_report_no_color_when_all_success(self) -> None:
        """Test that no color codes appear in the data row when all calls are 2xx."""
        s = EndpointStat(app_name="app", endpoint="GET /ok")
        s.record_response(200, 0.1)
        output = _format_report([s], sort_by="calls", reverse=True)

        data_line = output.splitlines()[-1]

        assert ColorCodes.RED not in data_line
        assert ColorCodes.YELLOW not in data_line
        assert ColorCodes.DEFAULT not in data_line

    def test_sort_by_invalid_raises_value_error(self) -> None:
        """Test that an invalid sort_by raises ValueError in StatsCollector.report."""
        c = StatsCollector()
        c._record("app", "GET /x", status_code=200, response_time=0.1, is_error=False)
        with pytest.raises(ValueError, match="sort_by must be one of"):
            c.show(sort_by="invalid")

    def test_format_report_empty_stats_does_not_raise(self) -> None:
        """Test that _format_report([]) returns a string without raising TypeError."""
        output = _format_report([], sort_by="calls", reverse=True)
        assert isinstance(output, str)
        assert "Endpoint" in output  # header is present even with no data rows

    def test_format_report_multiple_app_stats(self) -> None:
        """Test that stats from multiple apps all appear in the output table."""
        stat_a = EndpointStat(app_name="app-a", endpoint="GET /alpha")
        stat_a.record_response(200, 0.1)
        stat_b = EndpointStat(app_name="app-b", endpoint="POST /beta")
        stat_b.record_response(200, 0.2)
        output = _format_report([stat_a, stat_b], sort_by="calls", reverse=True)
        assert "GET /alpha" in output
        assert "POST /beta" in output

    def test_format_report_hide_endpoint_col_omits_endpoint(self) -> None:
        """Test that hide_endpoint_col=True omits both the Endpoint header and the endpoint value."""
        output = _format_report([self._make_stat("POST /login")], sort_by="calls", reverse=True, hide_endpoint_col=True)
        assert "Endpoint" not in output
        assert "POST /login" not in output
        assert "Calls" in output

    def test_format_report_hide_endpoint_col_colors_only_related_columns(self) -> None:
        """Test that with hide_endpoint_col=True, colors land on the shifted 4xx, 5xx, and Error cells."""
        s = EndpointStat(app_name="app", endpoint="GET /mixed")
        s.record_response(200, 0.1)
        s.record_response(404, 0.2)
        s.record_response(404, 0.2)
        s.record_response(503, 0.3)
        s.record_error()
        s.record_error()
        s.record_error()
        output = _format_report([s], sort_by="calls", reverse=True, hide_endpoint_col=True)

        data_line = output.splitlines()[-1]

        # Distinct counts (4xx=2, 5xx=1, Error=3) prove each color is applied to the correct shifted cell
        yellow_cells = re.findall(re.escape(ColorCodes.YELLOW) + r"([^\x1b]*)", data_line)
        red_cells = re.findall(re.escape(ColorCodes.RED) + r"([^\x1b]*)", data_line)
        assert [c.strip() for c in yellow_cells] == ["2"]
        assert sorted(c.strip() for c in red_cells) == ["1", "3"]


class TestShowStats:
    """Tests for StatsCollector.show() output."""

    def test_show_single_app_omits_app_name_separator(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that a single-app report does not print an app-name separator line."""
        c = StatsCollector()
        c._record("my-app", "GET /x", status_code=200, response_time=0.1, is_error=False)
        c.show()
        output = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
        assert "my-app" not in output

    def test_show_multiple_apps_includes_app_name_separator(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that a multi-app report prints a '--- app_name ---' separator for each app."""
        c = StatsCollector()
        c._record("alpha", "GET /a", status_code=200, response_time=0.1, is_error=False)
        c._record("beta", "GET /b", status_code=200, response_time=0.2, is_error=False)
        c.show()
        output = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
        for app in ("alpha", "beta"):
            assert re.search(rf"-+ {app} -+", output)

    def test_show_filter_by_endpoint_hides_endpoint_column(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that show(endpoint=...) restricts the report to that endpoint and omits the Endpoint column."""
        c = StatsCollector()
        c._record("my-app", "GET /a", status_code=200, response_time=0.1, is_error=False)
        c._record("my-app", "GET /b", status_code=200, response_time=0.2, is_error=False)
        c.show(endpoint="GET /a")
        output = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
        assert "Calls" in output
        assert "Endpoint" not in output
        assert "GET /a" not in output
        assert "GET /b" not in output

    def test_show_filter_by_app_name(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that show(app_name=...) restricts the report to endpoints of that app."""
        c = StatsCollector()
        c._record("alpha", "GET /a", status_code=200, response_time=0.1, is_error=False)
        c._record("beta", "GET /b", status_code=200, response_time=0.2, is_error=False)
        c.show(app_name="alpha")
        output = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
        assert "GET /a" in output
        assert "GET /b" not in output

    def test_show_filter_no_match_prints_message_with_filters(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that show() prints a message including the filters when they match no recorded stats."""
        c = StatsCollector()
        c._record("my-app", "GET /a", status_code=200, response_time=0.1, is_error=False)
        c.show(endpoint="GET /nope", app_name="other-app")
        output = capsys.readouterr().out
        assert "No stats recorded matching endpoint='GET /nope', app_name='other-app'" in output

    def test_show_no_stats_prints_plain_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that show() on an empty collector prints the plain no-stats message without filter info."""
        c = StatsCollector()
        c.show()
        output = capsys.readouterr().out
        assert "No stats recorded" in output
        assert "matching" not in output


class TestStatsMultiprocessAggregation:
    """Tests for file-backed cross-process stats aggregation."""

    def test_three_workers_aggregate_exactly(self, tmp_path: Any) -> None:
        """Test that three concurrent workers produce an exactly merged result.

        Each worker records a known number of calls with a known response time.
        The final aggregated file must reflect exact totals across all workers.
        """
        shared_path = str(tmp_path / "stats.json")
        app = "test-app"
        endpoint = "GET /v1/resource"

        # Worker configuration: (num_calls, response_time_seconds)
        workers = [
            (5, 0.1),  # sum=0.5, count=5
            (3, 0.3),  # sum=0.9, count=3
            (2, 0.5),  # sum=1.0, count=2
        ]
        # Expected totals: count=10, sum=2.4, avg=0.24, min=0.1, max=0.5

        with ProcessPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(self._worker, shared_path, app, endpoint, n, rt) for n, rt in workers]
            for f in as_completed(futures):
                f.result()  # re-raise any worker exception

        result_dict = json.loads(Path(shared_path).read_text())

        aggregated = Stats.from_dict(result_dict)
        stat = aggregated.get(endpoint, app_name=app)

        assert stat is not None
        assert stat.num_calls == 10
        assert stat.num_2xx == 10
        assert stat.num_errors == 0
        assert math.isclose(stat.avg_response_time, 0.24, rel_tol=1e-9)
        assert math.isclose(stat.min_response_time, 0.1, rel_tol=1e-9)
        assert math.isclose(stat.max_response_time, 0.5, rel_tol=1e-9)
        # Sorted distribution: [0.1x5, 0.3x3, 0.5x2]; p50=rank5->0.1s, p95/p99=rank10->0.5s
        assert math.isclose(stat.p50_response_time, 0.1, rel_tol=_HISTOGRAM_REL_ACCURACY * 2)
        assert math.isclose(stat.p95_response_time, 0.5, rel_tol=_HISTOGRAM_REL_ACCURACY * 2)
        assert math.isclose(stat.p99_response_time, 0.5, rel_tol=_HISTOGRAM_REL_ACCURACY * 2)

    def test_serialization_primitives_enable_any_channel(self, tmp_path: Any) -> None:
        """Test the to_dict/merge primitive workflow for tool-agnostic cross-process aggregation.

        Simulates a pattern where each process returns its snapshot via a return value
        (e.g. ProcessPoolExecutor.submit(...).result()) and the coordinator merges them.
        """
        with ProcessPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(self._worker_snapshot, 4, 0.1)
            f2 = pool.submit(self._worker_snapshot, 6, 0.2)
            payload1 = f1.result()
            payload2 = f2.result()

        Stats.merge(payload1)
        Stats.merge(payload2)

        stat = Stats.get("GET /x")
        assert stat.num_calls == 10
        # Exact avg: (4*0.1 + 6*0.2) / 10 = (0.4 + 1.2) / 10 = 0.16
        assert math.isclose(stat.avg_response_time, 0.16, rel_tol=1e-9)

    @staticmethod
    def _worker_snapshot(num_calls: int, rt: float) -> dict[str, Any]:
        """Worker function: record known stats and return a serialized snapshot dict."""

        c = StatsCollector("worker")
        for _ in range(num_calls):
            c._record("app", "GET /x", status_code=200, response_time=rt, is_error=False)
        return c.to_dict()

    @staticmethod
    def _worker(shared_path: str, app: str, endpoint: str, num_calls: int, response_time: float) -> None:
        """Worker function: record known stats and aggregate to a shared file."""
        c = StatsCollector("worker")
        for _ in range(num_calls):
            c._record(app, endpoint, status_code=200, response_time=response_time, is_error=False)
        c.aggregate(shared_path)


class TestStatsDisable:
    """Tests for Stats.enable() / Stats.disable() / Stats.is_enabled()."""

    def test_is_enabled_by_default(self) -> None:
        """Test that collection is enabled by default."""
        assert Stats.is_enabled() is True

    def test_disable_stops_automatic_recording(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that disabling Stats prevents API calls from being recorded."""
        mocker.patch.object(Client, "request", side_effect=lambda *a, **k: _make_mock_response(mocker))
        instance = api_class(api_client)

        Stats.disable()
        instance.get_something()

        assert Stats.get(_endpoint) is None

    def test_enable_resumes_recording(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that re-enabling Stats after disable() resumes recording."""
        mocker.patch.object(Client, "request", side_effect=lambda *a, **k: _make_mock_response(mocker))
        instance = api_class(api_client)

        Stats.disable()
        instance.get_something()
        assert Stats.get(_endpoint) is None

        Stats.enable()
        instance.get_something()
        assert Stats.get(_endpoint).num_calls == 1

    def test_is_enabled_reflects_toggle(self) -> None:
        """Test that is_enabled() reflects the current enable/disable state."""
        assert Stats.is_enabled() is True
        Stats.disable()
        assert Stats.is_enabled() is False
        Stats.enable()
        assert Stats.is_enabled() is True

    def test_disable_retains_existing_data(
        self, mocker: MockerFixture, api_client: APIClient, api_class: type[APIBase]
    ) -> None:
        """Test that disabling does not clear already-recorded stats."""
        mocker.patch.object(Client, "request", side_effect=lambda *a, **k: _make_mock_response(mocker))
        instance = api_class(api_client)

        instance.get_something()
        assert Stats.get(_endpoint).num_calls == 1

        Stats.disable()
        assert Stats.get(_endpoint).num_calls == 1


class TestHistogramBuckets:
    """Tests for the DDSketch bucket math underlying latency percentiles."""

    def test_bucket_round_trip_rel_error_within_alpha(self) -> None:
        """Test that _bucket_value(_bucket_index(rt)) is within alpha of rt for a wide range of latencies."""
        test_values = [1e-4, 1e-3, 0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
        for rt in test_values:
            idx = _bucket_index(rt)
            representative = _bucket_value(idx)
            rel_error = abs(representative - rt) / rt
            assert rel_error <= _HISTOGRAM_REL_ACCURACY, (
                f"rel_error {rel_error:.4f} > alpha={_HISTOGRAM_REL_ACCURACY} for rt={rt}s"
            )

    def test_bucket_value_increases_monotonically_with_index(self) -> None:
        """Test that higher bucket indices map to larger representative values."""
        indices = [_bucket_index(rt) for rt in [0.001, 0.01, 0.1, 1.0, 10.0]]
        values = [_bucket_value(i) for i in indices]
        assert indices == sorted(indices), "bucket indices should increase with response time"
        assert values == sorted(values), "bucket values should increase with bucket index"

    def test_zero_response_time_does_not_raise(self) -> None:
        """Test that _bucket_index handles a zero response time via the floor constant."""
        idx = _bucket_index(0.0)
        assert isinstance(idx, int)
        assert _bucket_value(idx) > 0
