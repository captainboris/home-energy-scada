import time
import unittest

from app.health import Health


class HealthTests(unittest.TestCase):
    def test_process_is_not_healthy_without_fresh_write(self):
        health = Health()
        health.connected = True
        health.transition("LIVE")
        self.assertFalse(health.snapshot("home", 0)["healthy"])

    def test_recent_live_sample_and_write_are_healthy(self):
        now = int(time.time() * 1000)
        health = Health(started_at_ms=now - 5000)
        health.connected = True
        health.transition("LIVE")
        health.fresh(now - 1000, now - 500, 5)
        health.wrote(now - 1000)
        snapshot = health.snapshot("home", 0, now_ms=now)
        self.assertTrue(snapshot["healthy"])
        self.assertEqual(snapshot["first_source_epoch_ms"], now - 1000)

    def test_queue_overflow_makes_health_explicit(self):
        now = int(time.time() * 1000)
        health = Health()
        health.connected = True
        health.transition("LIVE")
        health.fresh(now, now, 5)
        health.wrote(now)
        health.queue_overflow()
        self.assertFalse(health.snapshot("home", 512, now)["healthy"])

    def test_successful_write_recovers_from_a_transient_error(self):
        now = int(time.time() * 1000)
        health = Health()
        health.connected = True
        health.transition("LIVE")
        health.fresh(now, now, 5)
        health.write_failed("ProvisionedThroughputExceededException", "temporary")
        self.assertFalse(health.snapshot("home", 0, now)["healthy"])
        health.wrote(now)
        snapshot = health.snapshot("home", 0, now)
        self.assertTrue(snapshot["healthy"])
        self.assertEqual(snapshot["write_errors"], 1)


if __name__ == "__main__":
    unittest.main()
