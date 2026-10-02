import unittest

from common import AppError
from telemetry_storage import (aggregate_rollups, choose_resolution,
                               telemetry_history, telemetry_incremental,
                               telemetry_peaks)


START = 1790683200000


class FakeStore:
    def __init__(self, raw=None, rollups=None, health=None):
        self.raw = raw or []
        self.rollups = rollups or []
        self._health = health or {}

    def query(self, start, end, raw):
        rows = self.raw if raw else self.rollups
        field = "source_epoch_ms" if raw else "bucket_start_ms"
        return [row for row in rows if start <= int(row[field]) < end]

    def health(self):
        return self._health


def window(start=START, end=START + 60_000):
    return {"start_ms": start, "end_ms": end, "key": f"{start}/{end}",
            "start_date": "2026-09-29", "end_date": "2026-09-29"}


def raw(stamp, value):
    return {"source_epoch_ms": stamp, "pv_power_kw": value,
            "load_power_kw": value + .1, "grid_import_power_kw": 0,
            "grid_export_power_kw": 0, "battery_charge_power_kw": 0,
            "battery_discharge_power_kw": .2, "battery_soc_pct": 80}


def minute(stamp, minimum=1, maximum=3, average=2, count=12):
    stat = {"count": count, "min": minimum, "max": maximum,
            "avg": average, "last": average, "min_ts": stamp + 5000,
            "max_ts": stamp + 45000, "last_ts": stamp + 55000}
    return {"bucket_start_ms": stamp, "sample_count": count,
            "source_first_ms": stamp + 5000,
            "source_last_ms": stamp + 55000,
            "metrics": {name: dict(stat) for name in (
                "pv_power_kw", "load_power_kw", "grid_import_power_kw",
                "grid_export_power_kw", "battery_charge_power_kw",
                "battery_discharge_power_kw", "battery_soc_pct")}}


class TelemetryApiTests(unittest.TestCase):
    def test_day_uses_raw_and_preserves_real_gap(self):
        rows = [raw(START + 5000, 1), raw(START + 10000, 2),
                raw(START + 40000, 3)]
        data = telemetry_history(
            {"resolution": "auto"}, (START + 60_000) / 1000,
            window(), FakeStore(raw=rows,
                health={"first_source_epoch_ms": START + 5000, "healthy": True}))
        self.assertTrue(data["available"])
        self.assertEqual(data["resolution"], "5s_raw")
        self.assertEqual(data["coverage"]["fresh_samples"], 3)
        self.assertEqual(data["coverage"]["largest_gap_seconds"], 30)
        pv = next(row for row in data["series"] if row["metric"] == "pv_power_kw")
        self.assertEqual(len(pv["points"]), 3)

    def test_week_uses_minute_rollups_and_keeps_min_max_last(self):
        seven_days = 7 * 86400 * 1000
        rows = [minute(START), minute(START + 60_000, 2, 8, 4)]
        data = telemetry_history(
            {"resolution": "auto"}, (START + seven_days) / 1000,
            window(START, START + seven_days), FakeStore(rollups=rows))
        self.assertEqual(data["resolution"], "60s_rollup")
        pv = next(row for row in data["series"] if row["metric"] == "pv_power_kw")
        self.assertEqual(pv["plot_strategy"], "min_max_last")
        self.assertTrue(any(point[1] == 8 for point in pv["points"]))
        self.assertEqual(len(pv["envelope"]), 2)

    def test_month_aggregates_to_fifteen_minutes(self):
        rows = [minute(START + index * 60_000, minimum=index,
                       maximum=index + 10, average=index + 5)
                for index in range(15)]
        duration = 30 * 86400 * 1000
        data = telemetry_history(
            {"resolution": "auto"}, (START + duration) / 1000,
            window(START, START + duration), FakeStore(rollups=rows))
        self.assertEqual(data["resolution"], "900s_rollup")
        pv = next(row for row in data["series"] if row["metric"] == "pv_power_kw")
        self.assertEqual(len(pv["envelope"]), 1)
        self.assertEqual(pv["envelope"][0][1], 0)
        self.assertEqual(pv["envelope"][0][2], 24)

    def test_day_peak_uses_real_raw_sample_timestamp(self):
        rows = [raw(START + 5000, 2), raw(START + 10000, 9), raw(START + 15000, 4)]
        peaks = telemetry_peaks(
            START, START + 60_000, ("load_power_kw",), FakeStore(raw=rows))
        self.assertEqual(peaks["load_power_kw"]["kw"], 9.1)
        self.assertEqual(peaks["load_power_kw"]["source"], "fast_telemetry_raw")
        self.assertIn("T", peaks["load_power_kw"]["time"])

    def test_week_peak_uses_rollup_max_not_average(self):
        seven_days = 7 * 86400 * 1000
        rows = [minute(START, maximum=5, average=2),
                minute(START + 60_000, maximum=12, average=3)]
        peaks = telemetry_peaks(
            START, START + seven_days, ("load_power_kw",), FakeStore(rollups=rows))
        self.assertEqual(peaks["load_power_kw"]["kw"], 12)
        self.assertEqual(peaks["load_power_kw"]["source"], "fast_telemetry_rollup_max")
        self.assertEqual(peaks["load_power_kw"]["sample_resolution_seconds"], 60)

    def test_incremental_returns_current_latest_even_when_cursor_has_no_new_points(self):
        stamp = START + 5000
        store = FakeStore(raw=[raw(stamp, 4)], health={
            "last_source_epoch_ms": stamp, "healthy": True, "state": "LIVE"
        })
        data = telemetry_incremental(
            {"since_ms": str(START + 30_000)}, (START + 60_000) / 1000,
            store, minimum_ms=START)
        self.assertEqual(data["sample_count"], 0)
        self.assertEqual(data["latest"]["load_power_kw"]["t"], stamp)
        self.assertEqual(data["latest"]["load_power_kw"]["value"], 4.1)

    def test_incremental_new_rows_win_when_health_write_lags(self):
        health_stamp = START + 5000
        new_stamp = START + 40000
        store = FakeStore(raw=[raw(health_stamp, 1), raw(new_stamp, 7)], health={
            "last_source_epoch_ms": health_stamp, "healthy": True, "state": "LIVE"
        })
        data = telemetry_incremental(
            {"since_ms": str(START + 30000)}, (START + 60_000) / 1000,
            store, minimum_ms=START)
        self.assertEqual(data["latest"]["load_power_kw"]["t"], new_stamp)
        self.assertEqual(data["latest"]["load_power_kw"]["value"], 7.1)

    def test_no_fast_history_falls_back_cleanly(self):
        data = telemetry_history({}, (START + 60_000) / 1000,
                                 window(), FakeStore())
        self.assertFalse(data["available"])
        self.assertEqual(data["reason"], "no_fast_telemetry_for_range")

    def test_raw_query_cannot_cover_a_week(self):
        with self.assertRaises(AppError) as caught:
            choose_resolution({"resolution": "raw"}, 7 * 86400 * 1000)
        self.assertEqual(caught.exception.code, "RAW_RANGE_TOO_LONG")


if __name__ == "__main__":
    unittest.main()
