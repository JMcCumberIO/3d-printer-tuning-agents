import socket
import os
from pathlib import Path
from typing import Optional

import httpx


class HAClient:
    NOZZLE_TEMP_ENTITY = "sensor.flashforge_right_nozzle_temperature"
    BED_TEMP_ENTITY = "sensor.flashforge_platform_temperature"
    STATUS_ENTITY = "sensor.flashforge_status"
    PRINTING_ENTITY = "binary_sensor.flashforge_printing"
    PROGRESS_ENTITY = "sensor.flashforge_print_progress"
    SPEED_ENTITY = "sensor.flashforge_current_print_speed"
    CAMERA_ENTITY = "camera.flashforge_adventurer_5m_pro_camera"
    LAYER_ENTITY = "sensor.flashforge_current_layer"
    TOTAL_LAYERS_ENTITY = "sensor.flashforge_total_layers"
    CURRENT_FILE_ENTITY = "sensor.flashforge_current_print_file"
    SPEED_PCT_ENTITY = "sensor.flashforge_print_speed_adjustment"

    # FlashForge binary protocol constants
    _FF_PORT = 8899
    _FF_HA_DOMAIN = "flashforge_adventurer5m"

    def __init__(self, urls: list[str], token: str, verify_ssl: bool = False,
                 printer_ip: Optional[str] = None):
        self.urls = [u for u in urls if u]
        self.token = token
        self.verify_ssl = verify_ssl
        self.printer_ip = printer_ip
        self.base_url: Optional[str] = None
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def connect(self) -> str:
        for url in self.urls:
            try:
                r = httpx.get(
                    f"{url}/api/",
                    headers=self._headers,
                    verify=self.verify_ssl,
                    timeout=5.0,
                )
                if r.status_code == 200:
                    self.base_url = url
                    return url
            except (httpx.ConnectError, httpx.TimeoutException):
                continue
        raise ConnectionError(f"Could not connect to HA at any of: {self.urls}")

    def _get(self, path: str) -> httpx.Response:
        r = httpx.get(
            f"{self.base_url}{path}",
            headers=self._headers,
            verify=self.verify_ssl,
            timeout=10.0,
        )
        r.raise_for_status()
        return r

    def _post(self, path: str, data: dict) -> httpx.Response:
        r = httpx.post(
            f"{self.base_url}{path}",
            headers=self._headers,
            json=data,
            verify=self.verify_ssl,
            timeout=10.0,
        )
        r.raise_for_status()
        return r

    def get_state(self, entity_id: str) -> dict:
        return self._get(f"/api/states/{entity_id}").json()

    def get_all_states(self) -> list[dict]:
        return self._get("/api/states").json()

    def call_service(self, domain: str, service: str, data: dict) -> list:
        return self._post(f"/api/services/{domain}/{service}", data).json()

    def get_camera_snapshot(self, entity_id: str = CAMERA_ENTITY) -> bytes:
        r = httpx.get(
            f"{self.base_url}/api/camera_proxy/{entity_id}",
            headers=self._headers,
            verify=self.verify_ssl,
            timeout=15.0,
        )
        r.raise_for_status()
        return r.content

    def get_history(self, entity_ids: list[str], start_time: str) -> list:
        r = httpx.get(
            f"{self.base_url}/api/history/period/{start_time}Z",
            headers=self._headers,
            params={
                "filter_entity_id": ",".join(entity_ids),
                "minimal_response": "true",
                "no_attributes": "true",
            },
            verify=self.verify_ssl,
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json()

    # --- Unit conversions ---

    @staticmethod
    def fahrenheit_to_celsius(f: float) -> float:
        return (f - 32) * 5 / 9

    @staticmethod
    def inches_per_sec_to_mms(v: float) -> float:
        return v * 25.4

    # --- Typed state accessors ---

    def get_nozzle_temp_c(self) -> float:
        state = self.get_state(self.NOZZLE_TEMP_ENTITY)
        return self.fahrenheit_to_celsius(float(state["state"]))

    def get_bed_temp_c(self) -> float:
        state = self.get_state(self.BED_TEMP_ENTITY)
        return self.fahrenheit_to_celsius(float(state["state"]))

    def get_print_status(self) -> str:
        return self.get_state(self.STATUS_ENTITY)["state"]

    def get_print_progress(self) -> float:
        return float(self.get_state(self.PROGRESS_ENTITY)["state"])

    def is_printing(self) -> bool:
        return self.get_state(self.PRINTING_ENTITY)["state"] == "on"

    def get_print_speed_mms(self) -> float:
        state = self.get_state(self.SPEED_ENTITY)
        return self.inches_per_sec_to_mms(float(state["state"]))

    def _get_optional_state(self, entity_id: str) -> Optional[str]:
        """Return entity state string, or None if missing/unavailable/unknown."""
        try:
            state = self.get_state(entity_id)
            if state["state"] in ("unavailable", "unknown", ""):
                return None
            return state["state"]
        except Exception:
            return None

    def get_current_layer(self) -> Optional[int]:
        val = self._get_optional_state(self.LAYER_ENTITY)
        return int(float(val)) if val is not None else None

    def get_total_layers(self) -> Optional[int]:
        val = self._get_optional_state(self.TOTAL_LAYERS_ENTITY)
        return int(float(val)) if val is not None else None

    def get_current_file(self) -> Optional[str]:
        return self._get_optional_state(self.CURRENT_FILE_ENTITY)

    def get_speed_pct(self) -> Optional[int]:
        val = self._get_optional_state(self.SPEED_PCT_ENTITY)
        return int(float(val)) if val is not None else None

    async def get_camera_snapshot_async(
        self, entity_id: str = CAMERA_ENTITY
    ) -> bytes:
        """Async version of get_camera_snapshot() using httpx.AsyncClient."""
        async with httpx.AsyncClient(verify=self.verify_ssl) as client:
            r = await client.get(
                f"{self.base_url}/api/camera_proxy/{entity_id}",
                headers=self._headers,
                timeout=15.0,
            )
            r.raise_for_status()
            return r.content

    # --- Service calls ---

    def start_print(self, file_path: str) -> list:
        return self.call_service(self._FF_HA_DOMAIN, "start_print", {"file_path": file_path})

    def pause_print(self) -> list:
        return self.call_service(self._FF_HA_DOMAIN, "pause_print", {})

    def cancel_print(self) -> list:
        return self.call_service(self._FF_HA_DOMAIN, "cancel_print", {})

    # --- Direct printer file upload (FlashForge binary protocol) ---

    def upload_gcode(self, local_path: str, chunk_size: int = 4096,
                     timeout: float = 60.0) -> str:
        """
        Upload a local gcode file to the printer via the FlashForge binary protocol.

        Returns the path on the printer (e.g. '/data/model.gcode') which can be
        passed directly to start_print().

        Raises ConnectionError if printer_ip is not configured.
        Raises RuntimeError if the printer rejects the upload.
        """
        if not self.printer_ip:
            raise ConnectionError(
                "printer_ip is required for direct upload. "
                "Add 'printer_ip' to the [ha] section of config.yaml."
            )

        path = Path(local_path)
        size = path.stat().st_size
        filename = path.name

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((self.printer_ip, self._FF_PORT))

            # Handshake
            sock.sendall(b"~M601 S1\r\n")
            resp = sock.recv(256)
            if b"Control Success" not in resp:
                raise RuntimeError(f"FlashForge handshake failed: {resp!r}")

            # Start upload: printer responds with the path it will write to
            cmd = f"~M28 {size} 0:/user/{filename}\r\n".encode()
            sock.sendall(cmd)
            resp = sock.recv(256)
            if b"Writing to file:" not in resp:
                raise RuntimeError(f"FlashForge M28 rejected: {resp!r}")

            # Parse printer path from response: "Writing to file: /data/foo.gcode"
            printer_path = "/data/" + filename
            for part in resp.decode(errors="replace").split("\n"):
                if "Writing to file:" in part:
                    printer_path = part.split("Writing to file:")[-1].strip()
                    break

            # Stream file data
            with open(local_path, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    sock.sendall(chunk)

            # Finalise upload
            sock.sendall(b"~M29\r\n")
            sock.recv(256)  # consume ack

            return printer_path
        finally:
            sock.close()

    def ha_snapshot(self) -> dict[str, str]:
        """Return all HA entity states as a flat dict for logging."""
        states = self.get_all_states()
        return {s["entity_id"]: s["state"] for s in states}
