"""Google Sheets writer.

Uses a service account (JSON credentials) to upsert rows into a single
worksheet, matched on the `link` column, so the script is safe to run
repeatedly: a link seen before updates its existing row in place if any
of its other fields changed (e.g. the organizer edited the event on
Strava), otherwise nothing happens; a new link gets appended.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

HEADERS = [
    "source",
    "club",
    "title",
    "date",
    "location",
    "description",
    "link",
    "image_url",
    "engagement",
    "fetched_at",
]


def _client() -> gspread.Client:
    raw = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


def _ensure_headers(ws: gspread.Worksheet) -> None:
    existing = ws.row_values(1)
    if existing == HEADERS:
        return
    if not existing:
        ws.update("A1", [HEADERS])
        log.info("Wrote header row")
        return
    # Header mismatch — prepend a fresh header row to avoid data loss
    log.warning("Existing header row differs. Overwriting row 1 with expected schema.")
    ws.update("A1", [HEADERS])


def _existing_rows(ws: gspread.Worksheet) -> dict[str, tuple[int, list[str]]]:
    """Map link -> (1-indexed sheet row number, current row values)."""
    try:
        values = ws.get_all_values()
    except Exception as exc:
        log.warning("Could not read existing rows: %s", exc)
        return {}
    link_idx = HEADERS.index("link")
    existing: dict[str, tuple[int, list[str]]] = {}
    for i, row in enumerate(values[1:], start=2):  # row 1 is the header
        if len(row) > link_idx and row[link_idx]:
            existing[row[link_idx]] = (i, row)
    return existing


def _content_changed(current: list[str], incoming: list[str]) -> bool:
    """True if any column other than `fetched_at` differs between the rows."""
    fetched_idx = HEADERS.index("fetched_at")
    for i in range(fetched_idx):
        cur = current[i] if i < len(current) else ""
        if cur != incoming[i]:
            return True
    return False


def _col_letter(n: int) -> str:
    """1-indexed column number -> A1 letter (1 -> A, 27 -> AA, ...)."""
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def append_rows(sheet_id: str, worksheet_name: str, rows: list[dict]) -> tuple[int, int]:
    """Upsert rows into the worksheet, matched on `link`.

    A link not seen before is appended as a new row. A link already present
    whose other fields differ from what's stored gets that row overwritten
    in place (this is what makes edits made on Strava after the first sync
    actually show up instead of being silently dropped).

    Returns (appended_count, updated_count).
    """
    if not rows:
        log.info("No rows to append")
        return 0, 0

    gc = _client()
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=len(HEADERS))
        log.info("Created worksheet %s", worksheet_name)

    _ensure_headers(ws)
    existing = _existing_rows(ws)

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_rows: list[list[str]] = []
    updates: list[dict] = []
    seen_links: set[str] = set()

    for row in rows:
        link = row.get("link", "")
        if not link or link in seen_links:
            continue
        seen_links.add(link)

        incoming_values = [str(row.get(col, "")) for col in HEADERS[:-1]] + [fetched_at]

        match = existing.get(link)
        if match is None:
            new_rows.append(incoming_values)
            continue

        row_number, current_values = match
        if _content_changed(current_values, incoming_values):
            last_col = _col_letter(len(HEADERS))
            updates.append({
                "range": f"A{row_number}:{last_col}{row_number}",
                "values": [incoming_values],
            })

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        log.info("Updated %d existing rows whose content changed", len(updates))

    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")

    log.info("Appended %d new rows, updated %d existing rows (of %d incoming)",
              len(new_rows), len(updates), len(rows))
    return len(new_rows), len(updates)
