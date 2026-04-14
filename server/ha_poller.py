import asyncio
import logging
from tools.ha_client import HAClient
from server.sse import SSEBroker

logger = logging.getLogger(__name__)


def _safe(fn):
    """Call fn(), return None on any exception."""
    try:
        return fn()
    except Exception:
        return None


async def poll_ha(
    broker: SSEBroker,
    client: HAClient,
    interval: float = 1.0,
) -> None:
    """Background coroutine: poll HA every `interval` seconds, publish to broker."""
    while True:
        try:
            event = {
                "type": "ha_state",
                "print_status": _safe(client.get_print_status),
                "nozzle_temp": _safe(client.get_nozzle_temp_c),
                "bed_temp": _safe(client.get_bed_temp_c),
                "progress": _safe(client.get_print_progress),
                "current_layer": _safe(client.get_current_layer),
                "total_layers": _safe(client.get_total_layers),
                "current_file": _safe(client.get_current_file),
                "speed_pct": _safe(client.get_speed_pct),
            }
            await broker.publish(event)
        except Exception as e:
            logger.warning("HA poll cycle error: %s", e)
        await asyncio.sleep(interval)
