import sys
from pathlib import Path
import click
from tools.config import get_config
from tools.ha_client import HAClient
from tools.calibration_db import CalibrationDB

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


if __name__ == "__main__":
    cli()
