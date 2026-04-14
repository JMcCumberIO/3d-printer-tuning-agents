import pytest
from unittest.mock import AsyncMock, MagicMock
from server.camera_relay import camera_frames


async def test_camera_frames_yields_multipart_mjpeg_frame():
    client = MagicMock()
    client.get_camera_snapshot_async = AsyncMock(return_value=b"FAKEJPEG")

    gen = camera_frames(client, interval=0)
    frame = await anext(gen)
    await gen.aclose()

    assert b"--frame" in frame
    assert b"Content-Type: image/jpeg" in frame
    assert b"FAKEJPEG" in frame


async def test_camera_frames_retries_after_snapshot_error():
    client = MagicMock()
    call_count = 0

    async def snapshot(_entity_id=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("camera offline")
        return b"RECOVERED"

    client.get_camera_snapshot_async = snapshot

    gen = camera_frames(client, interval=0)
    frame = await anext(gen)
    await gen.aclose()

    assert b"RECOVERED" in frame
    assert call_count == 2


async def test_camera_frames_yields_consecutive_frames():
    client = MagicMock()
    payloads = [b"FRAME_A", b"FRAME_B"]
    idx = 0

    async def snapshot(_entity_id=None):
        nonlocal idx
        data = payloads[idx % len(payloads)]
        idx += 1
        return data

    client.get_camera_snapshot_async = snapshot

    gen = camera_frames(client, interval=0)
    f1 = await anext(gen)
    f2 = await anext(gen)
    await gen.aclose()

    assert b"FRAME_A" in f1
    assert b"FRAME_B" in f2
