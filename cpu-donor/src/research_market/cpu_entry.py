"""Private CPU donor entry point, with state separate from the portable client."""

import os
import subprocess
import sys
from pathlib import Path


def main():
    if sys.platform != "linux":
        raise SystemExit("This reviewed CPU donor candidate requires Linux.")
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    os.environ.setdefault("MARKET_DATA_DIR", str(base / "multivac-cpu-donor"))
    import httpx
    import typer

    from .cpu_cli import app

    try:
        app()
    except (ValueError, httpx.HTTPError, OSError, subprocess.SubprocessError) as error:
        typer.echo(str(error), err=True)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
