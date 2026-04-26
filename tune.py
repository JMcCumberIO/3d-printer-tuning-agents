import sys
from pathlib import Path
import click
import os
import signal
import subprocess

import uvicorn
from tools.config import get_config
from tools.ha_client import HAClient
from tools.calibration_db import CalibrationDB
from agents.orchestrator import Orchestrator

DB_PATH = Path("calibration_db.json")


def build_ha_client() -> HAClient:
    config = get_config()
    return HAClient(
        urls=config["ha"]["urls"],
        token=config["ha"]["token"],
        verify_ssl=config["ha"]["verify_ssl"],
    )


@click.group()
def cli():
    """Tune3D — 3D printer calibration agent CLI."""
    pass


@cli.command()
def status():
    """Show printer and HA connection status."""
    client = build_ha_client()
    try:
        url = client.connect()
        click.echo(f"Connected to HA: {url}")
        status_val = client.get_print_status()
        nozzle = client.get_nozzle_temp_c()
        bed = client.get_bed_temp_c()
        printing = client.is_printing()
        click.echo(f"Printer status : {status_val}")
        click.echo(f"Nozzle temp    : {nozzle:.1f}°C")
        click.echo(f"Bed temp       : {bed:.1f}°C")
        click.echo(f"Printing       : {'yes' if printing else 'no'}")
    except ConnectionError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command(name="list-filaments")
def list_filaments():
    """List all filament × nozzle entries in the calibration database."""
    db = CalibrationDB(DB_PATH)
    filaments = db.list_filaments()
    if not filaments:
        click.echo("No filaments registered. Run: tune add-filament --filament <name> --nozzle <size>")
        return
    for key in filaments:
        entry = db._data[key]
        tier = entry.get("confidence_tier", 1)
        runs = len(entry.get("run_history", []))
        click.echo(f"  {key}  |  Tier {tier}  |  {runs} runs")


@cli.command(name="add-filament")
@click.option("--filament", default=None, help="Filament name (e.g. 'ELEGOO PLA+'); falls back to active_filament in config.yaml")
@click.option("--nozzle", default=None, help="Nozzle size (e.g. '0.4mm'); falls back to active_nozzle in config.yaml")
def add_filament(filament: str, nozzle: str):
    """Phase 0: Research a new filament and bootstrap from HA history."""
    config = get_config()
    filament = filament or config.get("active_filament", "")
    nozzle = nozzle or config.get("active_nozzle", "0.4mm")
    if not filament:
        raise click.UsageError("--filament is required (or set active_filament in config.yaml)")
    orch = Orchestrator.from_config(
        db_path=DB_PATH,
        confirm_fn=lambda msg: click.confirm(msg),
        ask_fn=lambda prompt: click.prompt(prompt, default="", show_default=False),
    )
    click.echo(f"Researching {filament} ({nozzle})...")
    result = orch.add_filament(filament, nozzle)

    research = result.get("research", {})
    click.echo("\n── Research Summary ──────────────────────")
    for param in ["nozzle_temp", "bed_temp", "flow_rate", "max_speed", "cooling_fan"]:
        data = research.get(param, {})
        rec = data.get("recommended", "?")
        r = data.get("range", [])
        sources = data.get("source_count", 0)
        click.echo(f"  {param:15s}: {rec}  (range {r}, {sources} sources)")

    ha = result.get("ha_bootstrap")
    if ha and ha.get("nozzle_temp"):
        click.echo(f"\nHA history bootstrap: nozzle_temp={ha['nozzle_temp']['median_c']:.1f}°C  bed_temp={ha['bed_temp']['median_c']:.1f}°C")

    click.echo(f"\n✓ {filament} | {nozzle} registered. Run 'tune calibrate' to begin test prints.")


@cli.command()
@click.option("--filament", default=None, help="Filament name (defaults to ACTIVE_FILAMENT in .env)")
@click.option("--nozzle", default=None, help="Nozzle size (defaults to ACTIVE_NOZZLE in .env)")
def calibrate(filament: str, nozzle: str):
    """Phase 1: Run calibration test prints for a filament × nozzle pair."""
    config = get_config()
    filament = filament or config.get("active_filament", "")
    nozzle = nozzle or config.get("active_nozzle", "0.4mm")
    if not filament:
        click.echo("Error: specify --filament or set ACTIVE_FILAMENT in .env", err=True)
        sys.exit(1)

    orch = Orchestrator.from_config(
        db_path=DB_PATH,
        confirm_fn=lambda msg: click.confirm(msg),
        ask_fn=lambda prompt: click.prompt(prompt, default="", show_default=False),
    )
    click.echo(f"Calibrating {filament} | {nozzle}...")
    result = orch.calibrate(filament, nozzle)

    click.echo(f"\n── Calibration Summary ────────────────────")
    click.echo(f"  Tier        : {result.get('tier', '?')}")
    click.echo(f"  Tested      : {', '.join(result.get('tested', [])) or 'none'}")
    click.echo(f"  Skipped     : {result.get('skipped_count', 0)} (already calibrated)")
    click.echo(f"  Declined    : {result.get('declined_count', 0)}")
    for r in result.get("results", []):
        click.echo(f"  {r['param']:15s}: {r.get('value')}  → overall={r.get('overall', 0):.2f}")


@cli.command()
@click.argument("model_path", type=click.Path(exists=True))
@click.option("--filament", default=None, help="Filament name (defaults to ACTIVE_FILAMENT in .env)")
@click.option("--nozzle", default=None, help="Nozzle size (defaults to ACTIVE_NOZZLE in .env)")
def advise(model_path: str, filament: str, nozzle: str):
    """Phase 2: Get profile recommendations for a specific .3mf model."""
    config = get_config()
    filament = filament or config.get("active_filament", "")
    nozzle = nozzle or config.get("active_nozzle", "0.4mm")
    if not filament:
        click.echo("Error: specify --filament or set ACTIVE_FILAMENT in .env", err=True)
        sys.exit(1)

    orch = Orchestrator.from_config(
        db_path=DB_PATH,
        confirm_fn=lambda msg: click.confirm(msg),
        ask_fn=lambda prompt: click.prompt(prompt, default="", show_default=False),
    )
    result = orch.advise(Path(model_path), filament, nozzle)

    click.echo(f"\n── Profile Recommendations ────────────────")
    if not result.get("recommendations"):
        click.echo("  No changes recommended.")
    else:
        for rec in result["recommendations"]:
            click.echo(f"  {rec['param']:20s}: {rec['current']} → {rec['suggested']}  ({rec['reason']})")
    click.echo(f"\n{result.get('summary', '')}")

    if result.get("recommendations"):
        if click.confirm("\nApply these recommendations to the active profile?"):
            click.echo("(Profile write not yet implemented — coming in Plan 3)")


@cli.command()
@click.option("--filament", default=None, help="Filament name (defaults to ACTIVE_FILAMENT in .env)")
@click.option("--nozzle", default=None, help="Nozzle size (defaults to ACTIVE_NOZZLE in .env)")
@click.option("--quality", default=0.80, type=float, show_default=True, help="Minimum quality threshold (0.0–1.0)")
def speed(filament: str, nozzle: str, quality: float):
    """Phase 3: Find the fastest print speed that maintains quality."""
    config = get_config()
    filament = filament or config.get("active_filament", "")
    nozzle = nozzle or config.get("active_nozzle", "0.4mm")
    if not filament:
        click.echo("Error: specify --filament or set ACTIVE_FILAMENT in .env", err=True)
        sys.exit(1)

    orch = Orchestrator.from_config(
        db_path=DB_PATH,
        confirm_fn=lambda msg: click.confirm(msg),
        ask_fn=lambda prompt: click.prompt(prompt, default="", show_default=False),
    )
    click.echo(f"Speed optimization for {filament} | {nozzle}  (quality threshold: {quality:.0%})")
    result = orch.speed_push(filament, nozzle, quality_threshold=quality)

    click.echo(f"\n── Speed Optimization Result ──────────────")
    click.echo(f"  Final speed : {result['final_speed']} mm/s")
    click.echo(f"  Stopped     : {result['stopped_reason']}")
    for p in result.get("pareto_points", []):
        marker = "✓" if p["quality"] >= quality else "✗"
        click.echo(f"  {marker} {p['speed']:4.0f} mm/s → quality={p['quality']:.2f}")


@cli.command()
@click.option("--filament", default=None, help="Filament name (defaults to ACTIVE_FILAMENT in .env)")
@click.option("--nozzle", default=None, help="Nozzle size (defaults to ACTIVE_NOZZLE in .env)")
def rollback(filament: str, nozzle: str):
    """Restore the most recent .bak OrcaSlicer profile backup for a filament."""
    config = get_config()
    filament = filament or config.get("active_filament", "")
    nozzle = nozzle or config.get("active_nozzle", "0.4mm")
    if not filament:
        click.echo("Error: specify --filament or set ACTIVE_FILAMENT in .env", err=True)
        sys.exit(1)

    orch = Orchestrator.from_config(
        db_path=DB_PATH,
        confirm_fn=lambda msg: click.confirm(msg),
        ask_fn=lambda prompt: click.prompt(prompt, default="", show_default=False),
    )
    try:
        orch.rollback(filament, nozzle)
        click.echo(f"✓ Rolled back OrcaSlicer profile for {filament}")
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


_PID_DIR = Path.home() / ".local" / "share" / "3d-tuner"
_PID_FILE = _PID_DIR / "server.pid"


@cli.command()
@click.option("--port", default=8765, type=click.IntRange(1, 65535), show_default=True, help="Port to listen on")
@click.option("--daemon", is_flag=True, default=False, help="Run in background")
@click.option("--stop", is_flag=True, default=False, help="Stop a running daemon")
def serve(port: int, daemon: bool, stop: bool):
    """Start (or stop) the dashboard server."""
    if stop:
        if not _PID_FILE.exists():
            click.echo("No running server found (no PID file).", err=True)
            sys.exit(1)
        try:
            pid = int(_PID_FILE.read_text().strip())
        except ValueError:
            click.echo("Error: PID file is corrupted. Remove ~/.local/share/3d-tuner/server.pid manually.", err=True)
            sys.exit(1)
        try:
            os.kill(pid, signal.SIGTERM)
            _PID_FILE.unlink(missing_ok=True)
            click.echo(f"Stopped server (PID {pid})")
        except ProcessLookupError:
            _PID_FILE.unlink(missing_ok=True)
            click.echo(f"Process {pid} not found — stale PID file removed.")
        return

    if daemon:
        _PID_DIR.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "server.app:app",
                 "--host", "0.0.0.0", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            click.echo(f"Error: failed to start daemon: {e}", err=True)
            sys.exit(1)
        _PID_FILE.write_text(str(proc.pid))
        click.echo(f"Dashboard running at http://localhost:{port}  (PID {proc.pid})")
        click.echo("Stop with: tune serve --stop")
        return

    click.echo(f"Dashboard at http://localhost:{port}  (Ctrl+C to stop)")
    uvicorn.run("server.app:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    cli()
