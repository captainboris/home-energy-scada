# Home Energy persistent FoxESS telemetry collector v0.5.0

This is an independent, long-running Lightsail service. It complements the
existing REST Collector Lambda; it does not replace, invoke, configure, or
share runtime state with that Lambda.

## What it accepts

The service authenticates to the FoxESS web portal, opens the proven
`wsmaitian` WebSocket, sends one initial `getdata`, and then consumes
server-originated frames. A frame becomes a historian point only when all of
the following are true:

- the frame and `result.node` have the expected structure;
- `errno == 0`;
- `result.timeDiff` is numeric and no greater than
  `FRESH_TIMEDIFF_MAX` (30 seconds by default);
- `result.consumeTs` is a plausible, non-zero millisecond timestamp;
- that source timestamp has not already been accepted.

Cached responses (`consumeTs == 0`), stale frames, malformed frames, and
duplicate source timestamps are counted in health but never written as raw
history. Missing intervals remain missing; the service does not fabricate
interpolated samples.

## Process boundary

```text
FoxESS web portal/WebSocket
        ↓
parser + freshness gate + in-memory duplicate filter
        ↓
bounded asyncio queue
        ↓
DynamoDB conditional raw write + one-minute rollup + health item
```

DynamoDB's conditional raw write is the durable duplicate authority. The
in-memory filter only avoids unnecessary requests. After a restart, the last
ten minutes of one-minute rollups are rebuilt from raw points.

## Runtime state machine

- `CONNECTING`: authenticating or opening a socket.
- `RECOVERING`: connected but waiting for a fresh server sample, reconnecting,
  or in bounded backoff.
- `LIVE`: fresh samples and successful writes are current.
- `STALE`: no new source timestamp for 35 seconds. A lightweight `getdata`
  recovery probe is allowed every 30 seconds.
- reconnect after 90 seconds without a fresh sample;
- planned socket refresh after 480 seconds;
- `STOPPING`: SIGTERM/SIGINT received; the write queue is drained before exit.

The service never polls every five seconds. The initial request and infrequent
stale-recovery probe are control messages; only frames passing the source-time
gate are persisted.

## Files

- `app/`: collector, parser, writer, health, and protocol adapters.
- `systemd/home-energy-ws-collector.service`: hardened service unit.
- `scripts/install.sh`: installs v0.5.0 without starting it by default.
- `scripts/install-signature-wasm.sh`: installs a local WASM file or downloads
  one from a pinned immutable interoperability commit.
- `scripts/healthcheck.sh`: checks systemd and persisted DynamoDB health.
- `tests/`: offline tests and a sanitized frame fixture; no credentials or
  production capture is included.

Use the root release documentation for installation, deployment, operations,
testing, and rollback. Do not put real credentials in this directory or ZIP.
