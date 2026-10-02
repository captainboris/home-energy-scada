"""FoxESS web-login and plant discovery using the portal's WASM signer."""

from __future__ import annotations

import ctypes
import time
from datetime import UTC, datetime

import aiohttp


BASE_URL = "https://www.foxesscloud.com"
LOGIN_PATH = "/basic/v0/user/login"
PLANTS_PATH = "/dew/v0/plant/droplistForWeb"


class AuthError(RuntimeError):
    pass


class ProtocolError(RuntimeError):
    pass


class WasmSigner:
    """Execute the same signature.wasm exports used by the FoxESS portal."""

    def __init__(self, wasm_path):
        try:
            from wasmtime import Engine, FuncType, Linker, Memory, Module, Store, ValType
        except ImportError as exc:
            raise RuntimeError("wasmtime is required for FoxESS web signing") from exc
        engine = Engine()
        module = Module.from_file(engine, str(wasm_path))
        linker = Linker(engine)
        self.store = Store(engine)
        self._memory_ref: list[Memory] = []
        i32 = ValType.i32()

        def memcpy_big(caller, dest: int, src: int, count: int) -> int:
            memory = self._memory_ref[0]
            base = ctypes.cast(memory.data_ptr(self.store), ctypes.c_void_p).value
            if base is None:
                raise RuntimeError("unable to access WASM memory")
            ctypes.memmove(base + dest, base + src, count)
            return dest

        linker.define_func(
            "env", "emscripten_memcpy_big",
            FuncType([i32, i32, i32], [i32]), memcpy_big, access_caller=True,
        )
        linker.define_func(
            "env", "emscripten_resize_heap", FuncType([i32], [i32]),
            lambda _size: 0,
        )
        linker.define_func(
            "env", "setTempRet0", FuncType([i32], []), lambda _value: None,
        )
        exports = linker.instantiate(self.store, module).exports(self.store)
        self.memory = exports["memory"]
        self._memory_ref.append(self.memory)
        self.begin_signature = exports["begin_signature"]
        self.end_signature = exports["end_signature"]
        self.stack_alloc = exports["stackAlloc"]
        self.stack_save = exports["stackSave"]
        self.stack_restore = exports["stackRestore"]

    def _base(self) -> int:
        base = ctypes.cast(self.memory.data_ptr(self.store), ctypes.c_void_p).value
        if base is None:
            raise RuntimeError("unable to access WASM memory")
        return base

    def _write(self, value: str) -> int:
        data = value.encode("utf-8") + b"\0"
        pointer = self.stack_alloc(self.store, len(data))
        ctypes.memmove(self._base() + pointer, data, len(data))
        return pointer

    def _read(self, pointer: int) -> str:
        data = bytearray()
        offset = 0
        while True:
            value = ctypes.c_ubyte.from_address(self._base() + pointer + offset).value
            if value == 0:
                break
            data.append(value)
            offset += 1
            if offset > 4096:
                raise RuntimeError("unexpected WASM signature length")
        return data.decode("utf-8")

    def sign(self, path: str, token: str, lang: str, timestamp_ms: str) -> str:
        stack = self.stack_save(self.store)
        try:
            result_pointer = self.begin_signature(
                self.store,
                self._write(path), self._write(token), self._write(lang),
                self._write(timestamp_ms),
            )
            result = self._read(result_pointer)
            self.end_signature(self.store, result_pointer)
            return result
        finally:
            self.stack_restore(self.store, stack)


class FoxAuth:
    def __init__(self, settings, signer=None):
        self.settings = settings
        self.signer = signer or WasmSigner(settings.signature_wasm)

    def headers(self, path: str, token: str = "") -> dict[str, str]:
        stamp = str(int(time.time() * 1000))
        utc_now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        return {
            "Content-Type": "application/json",
            "lang": "en",
            "token": token,
            "timezone": self.settings.timezone,
            "platform": "web",
            "timestamp": stamp,
            "dt": f"{self.settings.timezone}@{stamp}@{utc_now}",
            "signature": self.signer.sign(path, token, "en", stamp),
        }

    async def login(self, session) -> str:
        payload = {
            "user": self.settings.foxess_email,
            "password": self.settings.foxess_password_md5,
            "type": 1,
            "verification": 1,
        }
        async with session.post(
            BASE_URL + LOGIN_PATH,
            json=payload,
            headers=self.headers(LOGIN_PATH),
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            if response.status in (401, 403):
                raise AuthError(f"FoxESS login HTTP {response.status}")
            if response.status != 200:
                raise ProtocolError(f"FoxESS login HTTP {response.status}")
            try:
                data = await response.json(content_type=None)
            except Exception as exc:
                raise ProtocolError("FoxESS login returned invalid JSON") from exc
        if data.get("errno") != 0:
            raise AuthError(f"FoxESS login errno {str(data.get('errno'))[:20]}")
        token = (data.get("result") or {}).get("token")
        if not isinstance(token, str) or not token:
            raise ProtocolError("FoxESS login response contains no token")
        return token

    async def plant_id(self, session, token: str) -> str:
        if self.settings.foxess_plant_id:
            return self.settings.foxess_plant_id
        path = f"{PLANTS_PATH}?plantName="
        async with session.get(
            BASE_URL + path,
            headers=self.headers(path, token),
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            if response.status in (401, 403):
                raise AuthError(f"FoxESS plant discovery HTTP {response.status}")
            if response.status != 200:
                raise ProtocolError(f"FoxESS plant discovery HTTP {response.status}")
            try:
                data = await response.json(content_type=None)
            except Exception as exc:
                raise ProtocolError("FoxESS plant discovery returned invalid JSON") from exc
        if data.get("errno") != 0:
            raise ProtocolError(f"FoxESS plant discovery errno {str(data.get('errno'))[:20]}")
        result = data.get("result")
        if isinstance(result, dict):
            for key in ("data", "list", "plants"):
                if isinstance(result.get(key), list):
                    result = result[key]
                    break
        if not isinstance(result, list):
            result = []
        identifiers = []
        for plant in result:
            if not isinstance(plant, dict):
                continue
            for key in ("id", "plantId", "plantID"):
                if plant.get(key) is not None:
                    identifiers.append(str(plant[key]))
                    break
        if len(identifiers) != 1:
            raise ProtocolError(
                "set FOXESS_PLANT_ID because plant discovery did not return exactly one plant"
            )
        return identifiers[0]
