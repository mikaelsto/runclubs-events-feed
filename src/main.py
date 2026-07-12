"""Entry point for the weekly running-clubs sync.

Loads config, pulls events from Strava, deduplicates by link, and
appends new rows to the configured Google Sheet. Safe to run
repeatedly — only new rows are added.

Run locally:
    python -m src.main

Or via GitHub Actions (see .github/workflows/daily-sync.yml).
"""

from __future__ import annotations

import dataclasses
import logging
import os
import subprocess
import sys
from pathlib import Path

import yaml

from src import sheets, strava

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("running-clubs-sync")

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        log.error("Missing config.yaml at %s", CONFIG_PATH)
        sys.exit(1)
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f) or {}


def main() -> int:
    config = _load_config()

    sheet_id = os.environ.get("GOOGLE_SHEET_ID") or config.get("google_sheet_id")
    if not sheet_id:
        log.error("GOOGLE_SHEET_ID not set (env var or config.yaml)")
        return 1

    worksheet_name = config.get("worksheet_name", "Events")

    rows: list[dict] = []
    exit_code = 0

    # --- Strava --------------------------------------------------------
    # A failure here (bad/expired auth, missing env var) must fail the job —
    # swallowing it silently makes GitHub Actions report success while the
    # sheet quietly stops receiving updates. Rows collected before a
    # mid-iteration failure (e.g. one club erroring after others succeeded)
    # are still written below.
    try:
        for event in strava.fetch_all_events():
            rows.append(dataclasses.asdict(event))
    except KeyError as exc:
        log.error("Missing Strava env var: %s", exc)
        exit_code = 1
    except Exception as exc:
        log.exception("Strava fetch failed: %s", exc)
        exit_code = 1

    log.info("Collected %d total rows before dedupe", len(rows))

    # --- Write to Sheet -----------------------------------------------
    appended, updated = sheets.append_rows(sheet_id, worksheet_name, rows)
    log.info("Done. Appended %d new rows, updated %d existing rows.", appended, updated)

    _maybe_persist_rotated_refresh_token()
    return exit_code


def _maybe_persist_rotated_refresh_token() -> None:
    marker = Path(os.environ.get("STRAVA_ROTATION_MARKER", "/tmp/strava_rotated_refresh_token"))
    if not marker.exists():
        return
    repo = os.environ.get("SECRETS_REPO")
    if not repo:
        log.warning("Strava rotated the refresh_token but SECRETS_REPO is not set; skipping GH secret update")
        return
    new_token = marker.read_text().strip()
    try:
        subprocess.run(
            ["gh", "secret", "set", "STRAVA_REFRESH_TOKEN", "--repo", repo],
            input=new_token,
            text=True,
            check=True,
        )
        log.info("Updated STRAVA_REFRESH_TOKEN secret on %s with rotated value", repo)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        log.error("Failed to update rotated refresh_token: %s", exc)
    finally:
        try:
            marker.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
