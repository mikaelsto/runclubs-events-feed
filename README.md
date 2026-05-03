# Running Clubs — Events Feed

Pulls upcoming events from every Strava running club you follow and appends each occurrence as a new row in a Google Sheet. Runs four times a day via GitHub Actions and deploys a live HTML page via GitHub Pages.

## What it does

- **Strava**: Uses your personal Strava account (you're already a member of the clubs) to auto-discover every club and fetch their upcoming group events. Each upcoming occurrence of a recurring event becomes its own row.
- **Google Sheet**: Appends new rows, deduped on the event URL + occurrence date. Safe to re-run anytime — already-seen rows are skipped.
- **GitHub Pages**: Generates a self-contained HTML infographic from the sheet after each sync, filtered to upcoming events in Stockholm, Göteborg, and Malmö.

## Sheet columns

`source | club | title | date | location | description | link | image_url | engagement | fetched_at`

- `source` is always `strava`
- `engagement` is the joined-athletes count
- `link` is the Strava event URL with the occurrence date appended as a fragment (used as the dedup key)

---

## One-time setup

### 1. Create the Google Sheet

1. Create a new Google Sheet (any name — e.g. "Running clubs events feed").
2. Copy its ID from the URL: `docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`. You'll paste that into a GitHub secret later.
3. Leave the first tab named `Events` (or change `worksheet_name` in `config.yaml`).

### 2. Create a Google service account

1. Go to https://console.cloud.google.com/ and create a project (or reuse one).
2. Enable the **Google Sheets API** for that project (APIs & Services → Library → Sheets API → Enable).
3. IAM & Admin → Service Accounts → **Create service account**. Give it a name like `running-clubs-sync`. No roles needed.
4. On the service account, go to **Keys** → **Add key → JSON**. Download the file. This is your `GOOGLE_SERVICE_ACCOUNT_JSON`.
5. Open the JSON, find `"client_email"`, copy that email address.
6. Go back to your Google Sheet → Share → paste the service account email → give it **Editor** access.

### 3. Create a Strava API application

1. Go to https://www.strava.com/settings/api and click **Create an App**.
2. Fill in the form. For "Authorization Callback Domain" use `localhost`.
3. After creating, note the **Client ID** and **Client Secret**.

### 4. Get your Strava refresh token (one-time)

1. In your browser, visit this URL (replace `YOUR_CLIENT_ID`):
   ```
   https://www.strava.com/oauth/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http://localhost&approval_prompt=force&scope=read,read_all
   ```
2. Approve access. Strava redirects you to `http://localhost/?state=&code=XXXXXXXX&scope=...` — the page won't load but that's fine. Copy the `code` value from the URL bar.
3. Exchange that code for tokens. Replace the three values and run:
   ```bash
   curl -X POST https://www.strava.com/oauth/token \
     -d client_id=YOUR_CLIENT_ID \
     -d client_secret=YOUR_CLIENT_SECRET \
     -d code=THE_CODE_FROM_STEP_2 \
     -d grant_type=authorization_code
   ```
4. Copy the `refresh_token` from the response. That's your `STRAVA_REFRESH_TOKEN` — it doesn't expire unless you revoke it in Strava settings.

### 5. Push to GitHub and add secrets

1. Create a new GitHub repo (private is fine) and push this folder.
2. In the repo → Settings → Secrets and variables → Actions → **New repository secret**. Add each of:
   - `STRAVA_CLIENT_ID`
   - `STRAVA_CLIENT_SECRET`
   - `STRAVA_REFRESH_TOKEN`
   - `GOOGLE_SERVICE_ACCOUNT_JSON` — paste the **entire JSON file contents** as the value
   - `GOOGLE_SHEET_ID`
3. The workflow in `.github/workflows/daily-sync.yml` runs four times a day at 04:00, 10:00, 16:00, and 22:00 UTC. You can also trigger it manually from the Actions tab (**Run workflow** button).

---

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export STRAVA_CLIENT_ID=...
export STRAVA_CLIENT_SECRET=...
export STRAVA_REFRESH_TOKEN=...
export GOOGLE_SERVICE_ACCOUNT_JSON=$(cat /path/to/service-account.json)
export GOOGLE_SHEET_ID=...

python -m src.main
```

The first run writes the header row and appends all upcoming event occurrences. Subsequent runs only append rows with new `link` values.

---

## Customising

- **Schedule**: edit the cron lines in `.github/workflows/daily-sync.yml`.
- **Columns**: edit `HEADERS` in `src/sheets.py` and the corresponding dataclass in `src/strava.py`.
- **Filter by club**: add a `strava_exclude_clubs:` list to `config.yaml` and filter on `club["id"]` inside `strava.fetch_all_events`.
- **Location filter**: edit `ALLOWED_CITIES` in `src/generate_html.py`.

---

## Known limitations

- **Strava rate limits**: 100 requests per 15 minutes, 1000 per day. With 65 clubs and 4 syncs/day that's ~260 requests/day — well within limits. Do not add pagination to `_list_club_events` in `strava.py`; the endpoint ignores the `page` parameter and returns the same data on every call, causing an infinite loop.
- **Private Strava clubs**: only events from clubs you're a member of are returned. Make sure you've joined each one from the account whose refresh token you're using.
- **Sheet accumulation**: past events are never deleted from the sheet (the HTML filters them out). Periodically archive or clear old rows if the sheet grows large.
