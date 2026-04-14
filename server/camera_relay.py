import asyncio
from typing import AsyncIterator
from tools.ha_client import HAClient


async def camera_frames(
    client: HAClient,
    interval: float = 1.0,
) -> AsyncIterator[bytes]:
    """
    Async generator yielding multipart MJPEG frames.
    Polls HA camera snapshot once per `interval` seconds.
    On error, skips the frame and retries next tick.
    """
    while True:
        try:
            frame = await client.get_camera_snapshot_async()
        except Exception:
            await asyncio.sleep(interval)
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame
            + b"\r\n"
        )
        await asyncio.sleep(interval)
