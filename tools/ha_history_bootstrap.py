import statistics
from typing import Optional
from tools.ha_client import HAClient


class HAHistoryBootstrap:
    # Minimum °C to be considered "printing" (not idle/cooling)
    NOZZLE_PRINT_MIN_C = 150.0
    BED_PRINT_MIN_C = 45.0

    def __init__(self, ha_client: HAClient):
        self.ha = ha_client

    def run(self, start_date: str) -> dict:
        """
        Query HA history from start_date, extract print-time sensor values.
        Returns dict with bootstrapped parameter stats.
        """
        entity_ids = [
            HAClient.NOZZLE_TEMP_ENTITY,
            HAClient.BED_TEMP_ENTITY,
            HAClient.SPEED_ENTITY,
        ]
        history = self.ha.get_history(entity_ids, start_date + "T00:00:00")

        result = {
            "nozzle_temp": None,
            "bed_temp": None,
            "print_speed": None,
            "source": "ha_history",
            "start_date": start_date,
        }

        nozzle_c = []
        bed_c = []
        speed_mms = []

        for entity_data in history:
            if not entity_data:
                continue
            entity_id = entity_data[0].get("entity_id", "")

            for reading in entity_data:
                state = reading.get("state", "")
                try:
                    v = float(state)
                except (ValueError, TypeError):
                    continue

                if entity_id == HAClient.NOZZLE_TEMP_ENTITY:
                    c = HAClient.fahrenheit_to_celsius(v)
                    if c >= self.NOZZLE_PRINT_MIN_C:
                        nozzle_c.append(c)

                elif entity_id == HAClient.BED_TEMP_ENTITY:
                    c = HAClient.fahrenheit_to_celsius(v)
                    if c >= self.BED_PRINT_MIN_C:
                        bed_c.append(c)

                elif entity_id == HAClient.SPEED_ENTITY:
                    mms = HAClient.inches_per_sec_to_mms(v)
                    if mms > 5:
                        speed_mms.append(mms)

        if nozzle_c:
            result["nozzle_temp"] = {
                "median_c": statistics.median(nozzle_c),
                "mean_c": statistics.mean(nozzle_c),
                "min_c": min(nozzle_c),
                "max_c": max(nozzle_c),
                "sample_count": len(nozzle_c),
            }

        if bed_c:
            result["bed_temp"] = {
                "median_c": statistics.median(bed_c),
                "mean_c": statistics.mean(bed_c),
                "sample_count": len(bed_c),
            }

        if speed_mms:
            result["print_speed"] = {
                "median_mms": statistics.median(speed_mms),
                "max_mms": max(speed_mms),
                "sample_count": len(speed_mms),
            }

        return result
