from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.dynamodb_writer import DynamoWriter
from app.health import Health
from app.model import TelemetrySample


class ConditionalFailure(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    def __init__(self, fail_puts=0):
        self.items = {}
        self.fail_puts = fail_puts

    def put_item(self, Item, ConditionExpression=None):
        if self.fail_puts:
            self.fail_puts -= 1
            raise OSError("temporary write failure")
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and key in self.items:
            raise ConditionalFailure()
        self.items[key] = Item
        return {}

    def get_item(self, Key, **_kwargs):
        return {"Item": self.items.get((Key["pk"], Key["sk"]))}

    def query(self, **kwargs):
        values = kwargs["ExpressionAttributeValues"]
        rows = [item for (pk, sk), item in self.items.items()
                if pk == values[":pk"] and values[":lo"] <= sk <= values[":hi"]]
        return {"Items": rows}


def config(queue_size=8):
    return SimpleNamespace(
        queue_size=queue_size, site_id="home", timezone="Australia/Melbourne",
        aws_region="ap-southeast-2", table_name="test",
        health_write_seconds=60,
    )


def sample(stamp=1790683311398):
    return TelemetrySample(
        source_epoch_ms=stamp, received_at_ms=stamp + 100,
        time_diff_seconds=5, pv_power_kw=0, load_power_kw=.418,
        grid_power_kw=.017, grid_import_power_kw=.017,
        grid_export_power_kw=0, battery_power_kw=-.401,
        battery_charge_power_kw=0, battery_discharge_power_kw=.401,
        battery_soc_pct=92, grid_direction_code=1,
        battery_direction_code=2, work_mode="SelfUse",
    )


async def no_sleep(_seconds):
    return None


class WriterTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_and_minute_rollup_written(self):
        table, health = FakeTable(), Health()
        writer = DynamoWriter(config(), health, table=table, sleep=no_sleep)
        await writer.write_sample(sample())
        keys = [key[1] for key in table.items]
        self.assertEqual(sum(key.startswith("TS#") for key in keys), 1)
        self.assertEqual(sum(key.startswith("ROLLUP#60#") for key in keys), 1)
        rollup = next(item for item in table.items.values()
                      if item["sk"].startswith("ROLLUP#"))
        self.assertEqual(int(rollup["sample_count"]), 1)
        self.assertEqual(float(rollup["metrics"]["load_power_kw"]["max"]), .418)

    async def test_temporary_failure_is_retried(self):
        table, health = FakeTable(fail_puts=1), Health()
        writer = DynamoWriter(config(), health, table=table, sleep=no_sleep)
        await writer.write_sample(sample())
        self.assertEqual(health.write_errors, 0)
        self.assertEqual(health.writes, 1)

    async def test_duplicate_raw_timestamp_does_not_duplicate_rollup_count(self):
        table, health = FakeTable(), Health()
        writer = DynamoWriter(config(), health, table=table, sleep=no_sleep)
        await writer.write_sample(sample())
        await writer.write_sample(sample())
        rollup = next(item for item in table.items.values()
                      if item["sk"].startswith("ROLLUP#"))
        self.assertEqual(int(rollup["sample_count"]), 1)

    async def test_bounded_queue_overflow_is_reported(self):
        health = Health()
        writer = DynamoWriter(config(queue_size=1), health, table=FakeTable())
        self.assertTrue(writer.enqueue(sample()))
        self.assertFalse(writer.enqueue(sample(1790683316398)))
        self.assertEqual(health.queue_overflows, 1)
        self.assertEqual(health.last_error_code, "WRITE_QUEUE_OVERFLOW")

    async def test_recent_rollup_rebuild_after_restart(self):
        table, first_health = FakeTable(), Health()
        first = DynamoWriter(config(), first_health, table=table, sleep=no_sleep)
        point = sample()
        await first.write_sample(point)
        # Simulate a damaged/missing rollup while raw remains durable.
        for key in list(table.items):
            if key[1].startswith("ROLLUP#"):
                del table.items[key]
        second = DynamoWriter(config(), Health(), table=table, sleep=no_sleep)
        count = await second.rebuild_recent_rollups(point.source_epoch_ms + 1000)
        self.assertEqual(count, 1)
        self.assertTrue(any(key[1].startswith("ROLLUP#") for key in table.items))


if __name__ == "__main__":
    unittest.main()

