"""FoxESS WebSocket URL and connection helper."""

from urllib.parse import quote


WS_BASE_URL = "wss://www.foxesscloud.com/dew/v0/wsmaitian"


def websocket_url(plant_id: str, token: str) -> str:
    return (
        f"{WS_BASE_URL}?plantId={quote(plant_id, safe='')}"
        f"&token={quote(token, safe='')}&platform=web&lang=en"
    )


async def connect(session, plant_id: str, token: str):
    return await session.ws_connect(
        websocket_url(plant_id, token),
        origin="https://www.foxesscloud.com",
        heartbeat=20,
        receive_timeout=None,
        timeout=20,
        autoping=True,
    )

