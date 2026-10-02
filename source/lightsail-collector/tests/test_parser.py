from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.dedupe import RecentTimestamps
from app.model import TelemetrySample
from app.parser import parse_frame


HERE = Path(__file__).parent
RECEIVED = 1790683312000


def settings():
    return SimpleNamespace(
        fresh_timediff_max=30,
        grid_import_code=1,
        grid_export_code=-1,
        battery_charge_code=1,
        battery_discharge_code=2,
    )


def fixture():
    return json.loads((HERE / "fixtures/fresh_frame.json").read_text())


class ParserTests(unittest.TestCase):
    def test_fresh_frame_uses_consume_ts_and_normalises_watts(self):
        parsed = parse_frame(fixture(), RECEIVED, settings())
        self.assertEqual(parsed.reason, "fresh")
        sample = parsed.sample
        self.assertEqual(sample.source_epoch_ms, 1790683311398)
        self.assertAlmostEqual(sample.load_power_kw, 0.418)
        self.assertAlmostEqual(sample.grid_import_power_kw, 0.017)
        self.assertEqual(sample.grid_export_power_kw, 0)
        self.assertAlmostEqual(sample.grid_power_kw, 0.017)
        self.assertEqual(sample.battery_charge_power_kw, 0)
        self.assertAlmostEqual(sample.battery_discharge_power_kw, 0.401)
        self.assertAlmostEqual(sample.battery_power_kw, -0.401)
        self.assertEqual(sample.battery_soc_pct, 92)

    def test_cached_current_response_is_not_a_sample(self):
        frame = fixture()
        frame["result"]["consumeTs"] = 0
        parsed = parse_frame(frame, RECEIVED, settings())
        self.assertIsNone(parsed.sample)
        self.assertEqual(parsed.reason, "cached")

    def test_stale_frame_is_not_a_sample(self):
        frame = fixture()
        frame["result"]["timeDiff"] = 61
        parsed = parse_frame(frame, RECEIVED, settings())
        self.assertIsNone(parsed.sample)
        self.assertEqual(parsed.reason, "stale")

    def test_future_or_second_timestamp_is_rejected(self):
        frame = fixture()
        frame["result"]["consumeTs"] = 1790683311
        self.assertEqual(parse_frame(frame, RECEIVED, settings()).reason,
                         "invalid_source_timestamp")

    def test_export_and_battery_charge_direction(self):
        frame = fixture()
        frame["result"]["node"]["grid"]["gridToHidden"] = -1
        frame["result"]["node"]["bat"]["charge"] = 1
        sample = parse_frame(frame, RECEIVED, settings()).sample
        self.assertAlmostEqual(sample.grid_power_kw, -0.017)
        self.assertAlmostEqual(sample.grid_export_power_kw, 0.017)
        self.assertAlmostEqual(sample.battery_power_kw, 0.401)
        self.assertAlmostEqual(sample.battery_charge_power_kw, 0.401)

    def test_unknown_direction_never_invents_import_or_charge(self):
        frame = fixture()
        frame["result"]["node"]["grid"]["gridToHidden"] = 9
        frame["result"]["node"]["bat"]["charge"] = 9
        sample = parse_frame(frame, RECEIVED, settings()).sample
        self.assertIsNone(sample.grid_power_kw)
        self.assertIsNone(sample.grid_import_power_kw)
        self.assertIsNone(sample.battery_power_kw)
        self.assertIsNone(sample.battery_discharge_power_kw)

    def test_kw_payload_is_not_scaled_twice(self):
        frame = fixture()
        frame["result"]["node"]["load"]["power"] = {"value": "1.25", "unit": "kW"}
        self.assertEqual(parse_frame(frame, RECEIVED, settings()).sample.load_power_kw, 1.25)

    def test_duplicate_identity_is_source_timestamp(self):
        recent = RecentTimestamps(2)
        self.assertTrue(recent.add(1000))
        self.assertFalse(recent.add(1000))
        self.assertTrue(recent.add(2000))
        self.assertTrue(recent.add(3000))
        self.assertTrue(recent.add(1000))

    def test_melbourne_dst_fold_keeps_two_distinct_sort_keys(self):
        zone = ZoneInfo("Australia/Melbourne")
        first = int(datetime(2026, 4, 5, 2, 30, tzinfo=zone, fold=0).timestamp() * 1000)
        second = int(datetime(2026, 4, 5, 2, 30, tzinfo=zone, fold=1).timestamp() * 1000)
        base = dict(received_at_ms=second, time_diff_seconds=5,
                    pv_power_kw=1, load_power_kw=1, grid_power_kw=0,
                    grid_import_power_kw=0, grid_export_power_kw=0,
                    battery_power_kw=0, battery_charge_power_kw=0,
                    battery_discharge_power_kw=0, battery_soc_pct=50,
                    grid_direction_code=0, battery_direction_code=0)
        a = TelemetrySample(source_epoch_ms=first, **base).item("home", zone.key)
        b = TelemetrySample(source_epoch_ms=second, **base).item("home", zone.key)
        self.assertEqual(a["pk"], "SITE#home#DAY#2026-04-05")
        self.assertEqual(a["pk"], b["pk"])
        self.assertNotEqual(a["sk"], b["sk"])
        self.assertNotEqual(a["timestamp_local"], b["timestamp_local"])


if __name__ == "__main__":
    unittest.main()

