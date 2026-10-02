import os
import unittest
from datetime import datetime
from unittest.mock import patch

from common import ZONE
from history_service import (boundary_epoch_ms, merge_series,
                             resolution_policy, unified_history)
from telemetry_storage import telemetry_incremental


METRICS = (
    "pv_power_kw", "load_power_kw", "grid_import_power_kw",
    "grid_export_power_kw", "battery_charge_power_kw",
    "battery_discharge_power_kw", "battery_soc_pct",
)


def series(stamps, base=1):
    return [{"metric": metric, "unit": "%" if metric.endswith("pct") else "kW",
             "points": [[stamp, base + index] for index, stamp in enumerate(stamps)]}
            for metric in METRICS]


def window(start, end, preset="day"):
    first = datetime.fromtimestamp(start / 1000, ZONE)
    last = datetime.fromtimestamp((end - 1) / 1000, ZONE)
    return {"preset": preset, "start_date": first.date().isoformat(),
            "end_date": last.date().isoformat(), "start_at": first.isoformat(),
            "end_at": datetime.fromtimestamp(end / 1000, ZONE).isoformat(),
            "start_ms": start, "end_ms": end, "key": f"{start}/{end}"}


class Telemetry:
    def __init__(self, raw_rows=None, rollups=None):
        self.raw_rows = raw_rows or []
        self.rollups = rollups or []
        self.queries = []

    def query(self, start, end, raw):
        self.queries.append((start, end, raw))
        rows = self.raw_rows if raw else self.rollups
        field = "source_epoch_ms" if raw else "bucket_start_ms"
        return [row for row in rows if start <= int(row[field]) < end]

    def health(self):
        stamps = [int(row["source_epoch_ms"]) for row in self.raw_rows]
        return {"healthy": True, "state": "LIVE", "connected": True,
                "first_source_epoch_ms": min(stamps) if stamps else None,
                "last_source_epoch_ms": max(stamps) if stamps else None,
                "collector_version": "0.5.0"}


def raw(stamp, value):
    return {"source_epoch_ms": stamp, **{metric: value for metric in METRICS}}


class UnifiedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.boundary = int(datetime(2026, 10, 1, tzinfo=ZONE).timestamp() * 1000)

    def test_boundary_uses_melbourne_local_midnight(self):
        with patch.dict(os.environ, {"FAST_TELEMETRY_START_DATE": "2026-10-01"}):
            self.assertEqual(boundary_epoch_ms(), self.boundary)
            self.assertEqual(datetime.fromtimestamp(boundary_epoch_ms() / 1000, ZONE).hour, 0)

    def test_september_uses_only_legacy_historian(self):
        start, end = self.boundary - 86400000, self.boundary
        calls = []
        def legacy(segment):
            calls.append(segment)
            return {"range": segment, "series": series([start + 300000]),
                    "latest": {}, "warnings": [], "collector": {}}
        result = unified_history({"range": "day"}, end / 1000,
                                 window(start, end), legacy, None)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["source_segments"][0]["source"], "rest_5m")
        self.assertIsNone(result["last_source_timestamp"])

    def test_october_uses_fast_historian(self):
        start, end = self.boundary, self.boundary + 60000
        store = Telemetry([raw(start + 5000, 2), raw(start + 10000, 3)])
        result = unified_history({"range": "day"}, end / 1000,
                                 window(start, end), lambda _: self.fail("legacy queried"), store)
        self.assertEqual(result["source_segments"][0]["source"], "ws_fast")
        self.assertEqual(result["last_source_timestamp"], start + 10000)
        self.assertEqual(result["resolution_seconds"], 5)

    def test_cross_boundary_merges_and_sorts_without_duplicates(self):
        start, end = self.boundary - 60000, self.boundary + 60000
        def legacy(segment):
            return {"range": segment, "series": series([self.boundary - 30000, self.boundary - 5000]),
                    "latest": {}, "warnings": [], "collector": {}}
        store = Telemetry([raw(self.boundary + 5000, 4), raw(self.boundary + 10000, 5)])
        result = unified_history({"range": "day"}, end / 1000,
                                 window(start, end), legacy, store)
        pv = next(row for row in result["series"] if row["metric"] == "pv_power_kw")
        self.assertEqual([point[0] for point in pv["points"]], [
            self.boundary - 30000, self.boundary - 5000,
            self.boundary + 5000, self.boundary + 10000])
        self.assertEqual([item["source"] for item in result["source_segments"]],
                         ["rest_5m", "ws_fast"])

    def test_merge_prefers_later_source_at_same_timestamp(self):
        merged = merge_series(
            [{"metric": "pv_power_kw", "unit": "kW", "points": [[1, 1], [2, 2]]}],
            [{"metric": "pv_power_kw", "unit": "kW", "points": [[2, 20], [3, 3]]}],
        )
        pv = next(row for row in merged if row["metric"] == "pv_power_kw")
        self.assertEqual(pv["points"], [[1, 1.0], [2, 20.0], [3, 3.0]])

    def test_day_week_month_resolution_is_server_controlled(self):
        day = window(self.boundary, self.boundary + 86400000, "day")
        week = window(self.boundary, self.boundary + 7 * 86400000, "week")
        month = window(self.boundary, self.boundary + 30 * 86400000, "month")
        self.assertEqual(resolution_policy({"range": "day"}, day)[0], 5)
        self.assertEqual(resolution_policy({"range": "week"}, week)[0], 60)
        self.assertEqual(resolution_policy({"range": "month"}, month)[0], 900)

    def test_unified_response_keeps_gap_quality_separate_from_presentation(self):
        start, end = self.boundary, self.boundary + 60000
        store = Telemetry([raw(start + 5000, 2), raw(start + 20000, 3)])
        result = unified_history({"range": "day"}, end / 1000,
                                 window(start, end), lambda _: None, store)
        self.assertEqual(result["data_quality"]["fast"]["largest_gap_seconds"], 15.0)
        self.assertEqual(result["data_quality"]["fast"]["missing_duration_seconds"], 10.0)
        self.assertEqual(result["max_gap_seconds"], 15.0)
        self.assertFalse(result["gap_semantics"]["synthetic_points"])


class IncrementalHistoryTests(unittest.TestCase):
    def test_since_query_returns_multiple_point_catchup(self):
        boundary = int(datetime(2026, 10, 1, tzinfo=ZONE).timestamp() * 1000)
        rows = [raw(boundary + 5000, 1), raw(boundary + 10000, 1), raw(boundary + 15000, 2)]
        store = Telemetry(rows)
        result = telemetry_incremental({"since_ms": str(boundary + 4000)},
                                       (boundary + 20000) / 1000, store, boundary)
        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(result["through_ms"], boundary + 15000)
        self.assertEqual(result["latest"]["load_power_kw"]["t"], boundary + 15000)
        self.assertTrue(store.queries[0][2])

    def test_no_new_data_keeps_cursor_and_returns_health(self):
        boundary = int(datetime(2026, 10, 1, tzinfo=ZONE).timestamp() * 1000)
        store = Telemetry()
        result = telemetry_incremental({"since_ms": str(boundary + 10000)},
                                       (boundary + 20000) / 1000, store, boundary)
        self.assertEqual(result["sample_count"], 0)
        self.assertEqual(result["through_ms"], boundary + 10000)
        self.assertEqual(result["latest"], {})

    def test_query_can_cross_melbourne_midnight(self):
        boundary = int(datetime(2026, 10, 1, tzinfo=ZONE).timestamp() * 1000)
        store = Telemetry([raw(boundary - 1000, 1), raw(boundary + 4000, 2)])
        result = telemetry_incremental({"since_ms": str(boundary - 2000)},
                                       (boundary + 5000) / 1000, store, boundary - 10000)
        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(store.queries[0][:2], (boundary - 1999, boundary + 5001))


if __name__ == "__main__":
    unittest.main()
