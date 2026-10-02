"""Exit non-zero unless the persisted collector health is recent and healthy."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime


def parse_time(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def main() -> int:
    import boto3

    table_name = os.environ.get("TELEMETRY_TABLE_NAME", "").strip()
    site_id = os.environ.get("SITE_ID", "home").strip()
    if not table_name:
        print(json.dumps({"ok": False, "error_code": "TABLE_NOT_CONFIGURED"}))
        return 2
    table = boto3.resource(
        "dynamodb", region_name=os.environ.get("AWS_REGION", "ap-southeast-2")
    ).Table(table_name)
    item = table.get_item(
        Key={"pk": f"SITE#{site_id}", "sk": "STATE#ws_collector"},
        ConsistentRead=True,
    ).get("Item")
    if not item:
        print(json.dumps({"ok": False, "error_code": "HEALTH_NOT_FOUND"}))
        return 1
    now = datetime.now(UTC).timestamp()
    fresh = parse_time(item.get("last_fresh_sample_at"))
    written = parse_time(item.get("last_write_at"))
    ok = bool(
        item.get("healthy")
        and fresh and now - fresh <= 90
        and written and now - written <= 90
    )
    print(json.dumps({
        "ok": ok,
        "state": item.get("state"),
        "connected": bool(item.get("connected")),
        "last_fresh_age_seconds": round(now - fresh, 1) if fresh else None,
        "last_write_age_seconds": round(now - written, 1) if written else None,
        "writes": int(item.get("writes", 0)),
        "write_errors": int(item.get("write_errors", 0)),
        "reconnect_count": int(item.get("reconnect_count", 0)),
    }, separators=(",", ":")))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

