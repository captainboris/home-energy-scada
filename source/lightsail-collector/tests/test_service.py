from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp

from app.health import Health
from app.main import Service


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/fresh_frame.json").read_text()
)


def settings():
    return SimpleNamespace(
        dedupe_capacity=100, stale_after_seconds=35,
        reconnect_after_seconds=90, recovery_probe_seconds=30,
        max_session_seconds=480, debug_frames=False,
        fresh_timediff_max=30, grid_import_code=1, grid_export_code=-1,
        battery_charge_code=1, battery_discharge_code=2,
    )


class FakeWriter:
    def __init__(self):
        self.samples = []

    def enqueue(self, value):
        self.samples.append(value)
        return True


class FakeSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []
        self.closed = False

    async def send_str(self, value):
        self.sent.append(value)

    async def receive(self):
        return self.messages.pop(0)

    async def close(self):
        self.closed = True


class FirstThenTimeoutSocket(FakeSocket):
    async def receive(self):
        if self.messages:
            return self.messages.pop(0)
        raise asyncio.TimeoutError


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_getdata_then_persist_unique_server_sample(self):
        writer, health = FakeWriter(), Health()
        service = Service(settings(), health=health, writer=writer)
        service.token, service.plant_id = "secret-token", "private-plant"
        socket = FakeSocket([
            SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(FIXTURE)),
            SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(FIXTURE)),
            SimpleNamespace(type=aiohttp.WSMsgType.CLOSED, data=""),
        ])
        with patch("app.main.connect", new=AsyncMock(return_value=socket)):
            useful = await service.consume_connection(SimpleNamespace())
        self.assertTrue(useful)
        self.assertEqual(socket.sent, ["getdata"])
        self.assertEqual(len(writer.samples), 1)
        self.assertEqual(health.duplicate_frames, 1)
        self.assertTrue(socket.closed)

    async def test_cached_and_stale_frames_never_reach_writer(self):
        writer, health = FakeWriter(), Health()
        service = Service(settings(), health=health, writer=writer)
        service.token, service.plant_id = "secret-token", "private-plant"
        cached = json.loads(json.dumps(FIXTURE)); cached["result"]["consumeTs"] = 0
        stale = json.loads(json.dumps(FIXTURE)); stale["result"]["timeDiff"] = 61
        socket = FakeSocket([
            SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(cached)),
            SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(stale)),
            SimpleNamespace(type=aiohttp.WSMsgType.CLOSED, data=""),
        ])
        with patch("app.main.connect", new=AsyncMock(return_value=socket)):
            useful = await service.consume_connection(SimpleNamespace())
        self.assertFalse(useful)
        self.assertEqual(writer.samples, [])
        self.assertEqual(health.cached_frames, 1)
        self.assertEqual(health.stale_frames, 1)

    async def test_live_to_stale_probe_then_reconnect_threshold(self):
        ticks=iter([0,1,2,38,93])
        writer,health=FakeWriter(),Health()
        service=Service(settings(),health=health,writer=writer,
                        clock=lambda:next(ticks))
        service.token,service.plant_id="secret-token","private-plant"
        socket=FirstThenTimeoutSocket([
            SimpleNamespace(type=aiohttp.WSMsgType.TEXT,data=json.dumps(FIXTURE)),
        ])
        with patch("app.main.connect",new=AsyncMock(return_value=socket)):
            useful=await service.consume_connection(SimpleNamespace())
        self.assertTrue(useful)
        self.assertEqual(socket.sent,["getdata","getdata"])
        self.assertEqual(health.state,"RECOVERING")
        self.assertEqual(len(writer.samples),1)
        self.assertTrue(socket.closed)

    async def test_authentication_is_cached_and_force_refreshable(self):
        writer = FakeWriter()
        service = Service(settings(), health=Health(), writer=writer)
        auth = SimpleNamespace(
            login=AsyncMock(side_effect=["token-one", "token-two"]),
            plant_id=AsyncMock(return_value="plant"),
        )
        await service.authenticate(SimpleNamespace(), auth)
        await service.authenticate(SimpleNamespace(), auth)
        self.assertEqual(auth.login.await_count, 1)
        await service.authenticate(SimpleNamespace(), auth, force=True)
        self.assertEqual(auth.login.await_count, 2)
        self.assertEqual(service.token, "token-two")

    async def test_stop_event_closes_socket_gracefully(self):
        writer = FakeWriter()
        service = Service(settings(), health=Health(), writer=writer)
        service.token, service.plant_id = "token", "plant"
        service.request_stop()
        socket = FakeSocket([])
        with patch("app.main.connect", new=AsyncMock(return_value=socket)):
            useful = await service.consume_connection(SimpleNamespace())
        self.assertFalse(useful)
        self.assertTrue(socket.closed)


if __name__ == "__main__":
    unittest.main()
