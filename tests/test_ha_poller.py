import asyncio
import pytest
from unittest.mock import MagicMock
from server.ha_poller import poll_ha
from server.sse import SSEBroker


async def _one_event(broker, client, interval=0):
    async with broker.subscribe() as q:
        task = asyncio.create_task(poll_ha(broker, client, interval=interval))
        try:
            return await asyncio.wait_for(q.get(), timeout=1.0)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


async def test_poll_publishes_ha_state_event():
    broker = SSEBroker()
    client = MagicMock()
    client.get_print_status.return_value = "printing"
    client.get_nozzle_temp_c.return_value = 225.0
    client.get_bed_temp_c.return_value = 60.0
    client.get_print_progress.return_value = 42.0
    client.get_current_layer.return_value = None
    client.get_total_layers.return_value = None
    client.get_current_file.return_value = None
    client.get_speed_pct.return_value = None

    event = await _one_event(broker, client)

    assert event["type"] == "ha_state"
    assert event["print_status"] == "printing"
    assert event["nozzle_temp"] == 225.0
    assert event["current_layer"] is None


async def test_poll_returns_none_for_sensor_that_raises():
    broker = SSEBroker()
    client = MagicMock()
    client.get_print_status.side_effect = Exception("timeout")
    client.get_nozzle_temp_c.return_value = 225.0
    client.get_bed_temp_c.return_value = 60.0
    client.get_print_progress.return_value = 0.0
    client.get_current_layer.return_value = None
    client.get_total_layers.return_value = None
    client.get_current_file.return_value = None
    client.get_speed_pct.return_value = None

    event = await _one_event(broker, client)

    assert event["print_status"] is None
    assert event["nozzle_temp"] == 225.0


async def test_poll_continues_after_full_cycle_exception():
    broker = SSEBroker()
    client = MagicMock()
    call_count = 0

    def status():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("HA offline")
        return "idle"

    client.get_print_status.side_effect = status
    for attr in (
        "get_nozzle_temp_c", "get_bed_temp_c", "get_print_progress",
        "get_current_layer", "get_total_layers", "get_current_file", "get_speed_pct",
    ):
        getattr(client, attr).return_value = None

    async with broker.subscribe() as q:
        task = asyncio.create_task(poll_ha(broker, client, interval=0))
        try:
            e1 = await asyncio.wait_for(q.get(), timeout=1.0)
            e2 = await asyncio.wait_for(q.get(), timeout=1.0)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    assert e1["print_status"] is None
    assert e2["print_status"] == "idle"
