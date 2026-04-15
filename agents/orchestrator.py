# agents/orchestrator.py
from pathlib import Path
from typing import Callable, Optional

import anthropic

from agents.calibration_agent import CalibrationAgent
from agents.filament_research_agent import FilamentResearchAgent
from agents.profile_advisor import ProfileAdvisorAgent
from agents.speed_optimizer import SpeedOptimizerAgent
from agents.vision_agent import VisionAgent
from tools.calibration_db import CalibrationDB
from tools.config import get_config
from tools.ha_client import HAClient
from tools.ha_history_bootstrap import HAHistoryBootstrap
from tools.orca_profiles import OrcaProfiles
from tools.print_logger import PrintLogger


class Orchestrator:
    """
    Coordinates all agents. The from_config() factory method wires everything from .env + config.yaml.
    Individual methods (add_filament, calibrate, advise, speed_push, rollback) are the entry points
    called by CLI commands.
    """

    def __init__(
        self,
        db: CalibrationDB,
        profiles: OrcaProfiles,
        ha: HAClient,
        filament_research_agent: FilamentResearchAgent,
        calibration_agent: CalibrationAgent,
        profile_advisor: ProfileAdvisorAgent,
        speed_optimizer: SpeedOptimizerAgent,
        confirm_fn: Callable[[str], bool] = lambda msg: True,
        ask_fn: Callable[[str], str] = input,
        ha_bootstrap: Optional[HAHistoryBootstrap] = None,
    ):
        self.db = db
        self.profiles = profiles
        self.ha = ha
        self.research = filament_research_agent
        self.calibration = calibration_agent
        self.advisor = profile_advisor
        self.optimizer = speed_optimizer
        self.confirm_fn = confirm_fn
        self.ask_fn = ask_fn
        self.ha_bootstrap = ha_bootstrap

    @classmethod
    def from_config(
        cls,
        db_path: Path = Path("calibration_db.json"),
        confirm_fn: Callable[[str], bool] = lambda msg: True,
        ask_fn: Callable[[str], str] = input,
    ) -> "Orchestrator":
        """Build a fully-wired Orchestrator from .env + config.yaml."""
        config = get_config()
        ha = HAClient(
            urls=config["ha"]["urls"],
            token=config["ha"]["token"],
            verify_ssl=config["ha"]["verify_ssl"],
        )
        ha.connect()

        db = CalibrationDB(
            db_path,
            tier2_min=config["calibration"]["tier2_min_runs"],
            tier3_min=config["calibration"]["tier3_min_runs"],
        )
        profiles = OrcaProfiles(config["orca_profile_dir"])
        logger = PrintLogger()
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

        vision = VisionAgent(client, ha)
        research = FilamentResearchAgent(client)
        gcode_export_dir = config.get("orca", {}).get("gcode_output_dir", "~/projects/3D Printing")
        calibration = CalibrationAgent(
            client=client, db=db, ha=ha, vision=vision, logger=logger,
            confirm_fn=confirm_fn, ask_fn=ask_fn,
            poll_interval_seconds=15,
            gcode_export_dir=gcode_export_dir,
        )
        advisor = ProfileAdvisorAgent(client, db)
        optimizer = SpeedOptimizerAgent(
            db=db, ha=ha, vision=vision, logger=logger,
            quality_threshold=config["calibration"]["speed_quality_threshold"],
            step_percent=config["calibration"]["speed_step_percent"],
            confirm_fn=confirm_fn, ask_fn=ask_fn,
            poll_interval_seconds=15,
        )
        ha_bootstrap = HAHistoryBootstrap(ha)

        return cls(
            db=db, profiles=profiles, ha=ha,
            filament_research_agent=research,
            calibration_agent=calibration,
            profile_advisor=advisor,
            speed_optimizer=optimizer,
            confirm_fn=confirm_fn, ask_fn=ask_fn,
            ha_bootstrap=ha_bootstrap,
        )

    def add_filament(self, filament: str, nozzle: str) -> dict:
        """
        Phase 0: Research filament + bootstrap from HA history.
        Returns summary dict. Saves research_baseline to CalibrationDB.
        """
        research_data = self.research.research(filament, nozzle)
        self.db.set_research_baseline(filament, nozzle, research_data)

        # Optionally bootstrap from HA history
        ha_data = None
        if self.ha_bootstrap:
            try:
                ha_data = self.ha_bootstrap.run(start_date="2024-01-01")
            except Exception:
                pass

        # Pre-populate baseline from HA history bootstrap if available
        if ha_data:
            baseline_kwargs = {}
            if ha_data.get("nozzle_temp"):
                baseline_kwargs["nozzle_temp"] = round(ha_data["nozzle_temp"]["median_c"])
            if ha_data.get("bed_temp"):
                baseline_kwargs["bed_temp"] = round(ha_data["bed_temp"]["median_c"])
            if baseline_kwargs:
                self.db.set_baseline(filament, nozzle, **baseline_kwargs)

        return {
            "filament": filament,
            "nozzle": nozzle,
            "research": research_data,
            "ha_bootstrap": ha_data,
        }

    def calibrate(self, filament: str, nozzle: str) -> dict:
        """Phase 1: Run calibration sequence via CalibrationAgent."""
        return self.calibration.run(filament, nozzle)

    def advise(self, model_path: Path, filament: str, nozzle: str) -> dict:
        """Phase 2: Produce profile recommendations for a .3mf model."""
        return self.advisor.advise(model_path, filament, nozzle)

    def speed_push(self, filament: str, nozzle: str, quality_threshold: Optional[float] = None) -> dict:
        """Phase 3: Run speed optimization. Uses config threshold if quality_threshold not given."""
        if quality_threshold is not None:
            self.optimizer.quality_threshold = quality_threshold
        return self.optimizer.run(filament, nozzle)

    def rollback(self, filament: str, nozzle: str) -> None:
        """Restore the most recent .bak backup for the filament profile."""
        self.profiles.rollback_filament(filament)
