"""Portable client entry point with a persistent connection directory."""

import os
from pathlib import Path


def main():
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    os.environ.setdefault("MARKET_DATA_DIR", str(base / "research-market"))
    import httpx
    import typer

    from .remote_cli import app

    try:
        app()
    except (ValueError, httpx.HTTPError) as error:
        typer.echo(str(error), err=True)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
