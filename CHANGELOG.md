# InvoiceAI — Changelog

## Session 2026-06-22

---

### ✨ New Features

#### OAuth 2.0 Web Application flow (replaces desktop flow)
Reworked Gmail account connection so it works inside a container / in the cloud,
removing the dependency on a local `credentials.json` file and on
`InstalledAppFlow.run_local_server` (which opened a browser **on the server** and
cannot run in a headless container).

- **New `backend/oauth_flow.py`** — builds a Google **Web** OAuth flow entirely
  from env vars: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `OAUTH_REDIRECT_URI`.
  No `credentials.json`.
- **New endpoints in `server.py`:**
  - `GET /api/auth/login` — returns the Google consent URL and stores an
    anti-CSRF `state` in a signed session cookie.
  - `GET /api/auth/callback` — verifies `state`, exchanges the `code` for tokens,
    reads the account email, persists the **encrypted** credentials, and redirects
    back to the dashboard (`/?connect=success|error#settings`).
  - Removed the old `POST /api/accounts/connect`.
- **`SessionMiddleware`** (Starlette) added, keyed by `SESSION_SECRET`, `same_site=lax`,
  `https_only` auto-enabled when the redirect URI is HTTPS.
- **Frontend (`app.js`)** — the "חבר חשבון Gmail" button now calls `/api/auth/login`
  and redirects the page to Google; on return it reads `?connect=` and shows a toast.

#### Encrypted, Supabase-backed token storage (no more `token_*.json`)
- **New `backend/token_store.py`** — per-account Gmail credentials are stored in a
  new Supabase table `gmail_accounts`, **encrypted at rest with Fernet** (AES-128-CBC
  + HMAC) using the `TOKEN_ENC_KEY` env var. Plaintext refresh tokens never touch
  disk. Load / refresh / save / delete all go through this module; refreshed tokens
  are re-encrypted and written back.
- Refuses to fall back to insecure on-disk storage — raises a clear error if
  Supabase or `TOKEN_ENC_KEY` are not configured.
- **New `backend/sql/gmail_accounts.sql`** — table + `updated_at` trigger + RLS
  enabled (service-role-only access).
- **`agent.py`** — `get_connected_accounts`, `_build_gmail_service`,
  `_fetch_invoice_emails`, `disconnect_account`, and `_write_to_google_sheet` now
  resolve credentials via `token_store` instead of local token files. Deleted
  `connect_new_gmail_account` and all `token_*.json` / `credentials.json` handling.

#### Containerization & Kubernetes
- Production-grade multi-stage `Dockerfile` + `docker-compose.yml` (runs the app
  from a sealed container; `docker-compose up --build`).
- **New `k8s/`** manifests — `deployment.yaml`, `service.yaml`, `kustomization.yaml`,
  and a `secret.example.yaml` template (placeholders only) for local k3s / Rancher.

#### Security & supply chain hardening
- Patched CVEs, removed hardcoded secrets, moved `sheet_id` out of `config.json`
  into the `SHEET_ID` env var.
- Added CycloneDX SBOM, Opengrep security rules (`rules/`), and a gitleaks config.

- **New dependencies:** `cryptography==44.0.0` (Fernet), `itsdangerous==2.2.0` (signed sessions).
- **New env vars:** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `OAUTH_REDIRECT_URI`,
  `SESSION_SECRET`, `TOKEN_ENC_KEY` (see `backend/.env.example`).

### ✅ Verification
- `py_compile` + venv imports clean; Fernet encrypt/decrypt round-trip asserted
  (ciphertext does not leak plaintext).
- ASGI test: `GET /api/auth/login` → 200 with a real Google consent URL
  (`access_type=offline`); `GET /api/auth/callback` with a forged `state` → CSRF
  rejected → `?connect=error`.
- **gitleaks**: no leaks. **opengrep** (Google-OAuth + Supabase rules): 0 findings.

### ⚠️ Manual steps required before it works in the container
1. Run `backend/sql/gmail_accounts.sql` against the Supabase project.
2. In Google Cloud Console, create a **Web application** OAuth client and add
   `OAUTH_REDIRECT_URI` (e.g. `http://localhost:8000/api/auth/callback`) to the
   Authorized redirect URIs.
3. Set `TOKEN_ENC_KEY` (valid Fernet key) and `SESSION_SECRET` in the environment.

---

## Session 2026-05-25

---

### ✨ New Features

#### Supabase PostgreSQL Integration
- Replaced `invoices.json` as primary storage with a **Supabase PostgreSQL** cloud database.
- Created project `gmail-invoice-tracker` in region `eu-central-1` (Frankfurt).
- Schema: `public.invoices` table with columns: `id`, `email_id` (unique), `service_name`, `date`, `amount`, `currency`, `category`, `invoice_id`, `description`, `email_subject`, `scanned_account`, `created_at`.
- Unique index on `email_id` prevents double-importing the same Gmail message at DB level.
- RLS enabled; `anon`/`authenticated` roles explicitly revoked — backend uses `service_role` key only.
- New `_get_supabase()` helper in `GmailInvoiceAgent` returns an authenticated Supabase client (or `None` if not configured).
- `_load_cached_invoices()` reads from Supabase first, falls back to `invoices.json` if unavailable.
- `_save_cached_invoices()` upserts to Supabase on `email_id` conflict, and always writes `invoices.json` as local backup.
- Mock mode still uses `invoices.json` only — no mock data is written to the cloud DB.
- **New dependency:** `supabase` added to `requirements.txt`.
- **New env vars:** `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` in `backend/.env`.

#### Gmail Scan Improvements
- Extended lookback window from **30 days → 90 days** (3 months).
- Added `in:anywhere` to Gmail search query — now scans Inbox, Promotions, Updates, Sent, and all user labels.
- Expanded subject keywords: added `payment`, `order`, `הזמנה`.
- Increased `maxResults` from 15 → 500 per API call.
- Added **full pagination** via `nextPageToken` loop — fetches all matching messages, not just the first page.

---

## Session 2026-05-24

---

### 🐛 Bug Fixes

#### OAuth 500 on Gmail Connect
- **Problem:** `credentials.json` was corrupted — two versions of the JSON merged into one file, one with a placeholder secret (`[OAUTH_CLIENT_SECRET]`) and one real. The file was invalid JSON and crashed the OAuth flow.
- **Fix:** Rewrote `credentials.json` as valid JSON with the real client secret.

#### `No module named 'google.antigravity'` — Scan 500
- **Problem:** `agent.py` imported `from google.antigravity import Agent, LocalAgentConfig` — a Google-internal SDK that was never publicly released and cannot be pip-installed.
- **Fix:** Replaced with `google-genai` (official Gemini SDK). Rewrote the AI extraction loop to use `gemini_client.models.generate_content()` with `response_schema=InvoiceExtractionList` for structured output.
- **Model:** `gemini-2.5-flash` (2.0-flash was deprecated for new users).
- **Files changed:** `backend/agent.py`, `backend/requirements.txt`

#### Gemini API Key Setup
- Created `backend/.env` with `GEMINI_API_KEY`.
- Added `load_dotenv()` at the top of `agent.py` so the key loads automatically on server start.
- Key must come from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (not a GCP service account key — those expire and require enabling the API per-project).

#### Google Sheets 400 Error — URL vs Key
- **Problem:** `_write_to_google_sheet` called `gc.open_by_key(self.sheet_id)` but `sheet_id` stored in `config.json` was a full URL (`https://docs.google.com/spreadsheets/d/...`).
- **Fix:** Added regex extraction of the bare sheet ID from the URL before passing to gspread.
- **Also fixed:** `gspread.authorize(creds)` was deprecated → replaced with `gspread.Client(auth=creds)`.
- **File changed:** `backend/agent.py` (`_write_to_google_sheet`)

#### HTML Emails Parsed as 0.00 (Cellcom, CapCut etc.)
- **Problem:** `get_body_text` sent raw HTML (full of `<table>`, `<td>` tags) to Gemini when emails had no `text/plain` part. Gemini couldn't reliably extract amounts from tag soup — returned `0.00`.
- **Fix:** Rewrote body extraction to:
  1. Collect `text/plain` and `text/html` parts separately via recursive traversal.
  2. Prefer plain text; fall back to HTML only if no plain exists.
  3. Strip HTML tags (remove `<style>`, `<script>`, replace all tags with spaces, collapse whitespace) before sending to Gemini.
- **Also improved:** Gemini system prompt now explicitly handles Hebrew currency formats (`104 ₪`, `104.00 ש"ח`, `סה"כ 104`) and never returns 0 unless the invoice is genuinely free.
- **File changed:** `backend/agent.py` (`_fetch_invoice_emails`, `SYSTEM_INSTRUCTION`)

---

### ✨ New Features

#### Monthly PDF Report (Auto + Manual)
Full pipeline: scan → generate PDF → email delivery on the 20th of each month.

**New files:**
- `backend/report_generator.py` — generates landscape A4 PDF using `fpdf2`:
  - Header with month name, generation timestamp, invoice count
  - Summary table grouped by category + currency with totals
  - Full invoice detail table with alternating row colors
  - Hebrew font support via `DejaVuSans.ttf` + `DejaVuSans-Bold.ttf` (bundled in `backend/fonts/`)
  - `python-bidi` for correct RTL text rendering

- `backend/mailer.py` — sends the PDF as an email attachment via Gmail API using the existing OAuth token (no extra credentials needed).

- `backend/scheduler.py` — APScheduler `AsyncIOScheduler` with `CronTrigger(day=20, hour=8, minute=0, timezone="Asia/Jerusalem")`. On startup it runs automatically; on the 20th it: scans Gmail → generates PDF → emails to `ofekst@ip-com.co.il`.

**Modified files:**
- `backend/server.py`:
  - Added FastAPI lifespan handler that starts/stops the scheduler on app startup/shutdown.
  - `GET /api/reports/monthly?month=YYYY-MM` — generates and streams PDF as download.
  - `POST /api/reports/send?month=YYYY-MM` — generates PDF and emails it.

- `frontend/index.html` + `frontend/app.js`:
  - Added report bar above the invoices table: month picker + "הורד PDF" button + "שלח במייל" button + status text.
  - Default month = current month.
  - Download uses `URL.createObjectURL(blob)` for client-side file save.

**Dependencies added:** `fpdf2`, `apscheduler`, `python-bidi` (to `requirements.txt` and installed in venv).

#### Gmail `send` Scope for Email Delivery
- The original OAuth token only had `gmail.readonly` + `spreadsheets`.
- Added `https://www.googleapis.com/auth/gmail.send` to `SCOPES` in `connect_new_gmail_account()`.
- Deleted old token files so next login triggers re-authorization with the new scope.
- **Action required:** After a server restart, go to Settings → "חבר חשבון Gmail" and re-authorize so the token includes send permission.

#### Mock Invoice Cleanup
- Removed 29 mock invoices (IDs starting with `msg-mock-`) from `invoices.json`.
- Kept 12 real scanned invoices.
- The `GET /api/invoices` endpoint no longer auto-generates mock data on empty cache (avoids re-polluting real data).

#### InvoiceAI Logo
- Designed in Claude Design (claude.ai/design) — "Extract" variant: document + scan beam + $ being extracted, purple→cyan gradient.
- **Favicon:** Embedded as inline SVG data URI in `<head>` (no external file needed).
- **Sidebar:** Replaced placeholder brain icon with the real Extract SVG mark (inline SVG, 64×64, with glow filter).
- **Logo downloads page** at `/logo.html` — 7 variants (App Icon dark/light, Mark color/mono, Lockup dark/light, Favicon) downloadable as SVG or PNG at multiple sizes, plus bulk ZIP download via JSZip.
- **Sidebar links** added to `/logo.html` (לוגו ומיתוג) and `/admin.html` (ארכיטקטורה).

#### Admin Architecture Page (`/admin.html`)
- Self-contained HTML page at `frontend/admin.html`.
- **SVG architecture diagram** showing file dependency graph: Browser → server.py → agent.py / report_generator.py / mailer.py / scheduler.py, data stores (invoices.json, config.json, .env, credentials.json).
- **File cards** for every file in the project, each with:
  - Role description
  - Module-level constants/variables
  - Classes defined
  - Functions/endpoints
  - Internal imports
- Covers: `server.py`, `agent.py`, `report_generator.py`, `mailer.py`, `scheduler.py`, `app.js`, `index.html`, `style.css`, `config.json`, `.env`, `credentials.json`, `invoices.json`, `token_*.json`.

#### GitHub Repository
- Initialized git repo, added `.gitignore` (excludes `.env`, `credentials.json`, `token_*.json`, `reports/`, `invoices.json`, `venv/`).
- Pushed to: **https://github.com/strugo7/InvoiceAI**

---

### 🛠 State of the Project

#### Working
- Gmail OAuth connect (with `gmail.readonly` + `gmail.send` + `spreadsheets` scopes)
- Real Gmail scan with Gemini 2.5 Flash AI extraction
- HTML email stripping before AI analysis
- Google Sheets sync (accepts full URL or bare sheet ID)
- Mock mode / Production mode toggle
- Manual PDF report download (`GET /api/reports/monthly`)
- Auto scheduler (day 20, 08:00 IST) — email delivery pending re-auth (see below)
- Logo in sidebar + favicon in browser tab
- Admin architecture page

#### Pending / Known Issues
1. **Re-authorize Gmail** — must reconnect account via Settings to get `gmail.send` scope. Until then, the "שלח במייל" button will fail with a scope error.
2. **Email sending test** — not tested end-to-end (requires re-auth first). The code path is: `mailer._get_credentials()` → `build("gmail","v1")` → `users().messages().send()`.
3. **Google Sheets** — verified URL parsing fix is in place; needs a fresh production scan to confirm rows are written correctly.

#### File Structure
```
gmail-invoice-tracker/
├── backend/
│   ├── agent.py                  # AI agent, Gmail OAuth, Gemini extraction
│   ├── server.py                 # FastAPI — all API endpoints + scheduler start
│   ├── report_generator.py       # PDF generation (fpdf2 + DejaVu fonts)
│   ├── mailer.py                 # Gmail API email sender
│   ├── scheduler.py              # APScheduler — monthly report job
│   ├── fonts/
│   │   ├── DejaVuSans.ttf
│   │   └── DejaVuSans-Bold.ttf
│   ├── requirements.txt
│   ├── .env                      # GEMINI_API_KEY (gitignored)
│   ├── credentials.json          # OAuth client (gitignored)
│   ├── config.json               # use_mock + sheet_id
│   └── invoices.json             # local invoice cache (gitignored)
├── frontend/
│   ├── index.html                # Main app UI (Hebrew RTL)
│   ├── app.js                    # All frontend logic
│   ├── style.css                 # Glassmorphism dark theme
│   ├── logo.html                 # Logo download page (7 variants)
│   └── admin.html                # Architecture map page
├── docs/
│   └── superpowers/plans/
│       └── 2026-05-24-monthly-pdf-report.md   # Implementation plan
├── .gitignore
├── README.md
└── CHANGELOG.md                  # This file
```

#### Environment Setup (next session)
```bash
cd backend
source venv/bin/activate
uvicorn server:app --reload --port 8000
```
Make sure `backend/.env` has a valid `GEMINI_API_KEY` from aistudio.google.com/apikey.

---

### 🔑 Key Decisions Made

| Decision | Reason |
|---|---|
| `google-genai` instead of `google.antigravity` | antigravity is Google-internal, not pip-installable |
| `gemini-2.5-flash` model | 2.0-flash deprecated for new users |
| Gemini API key from AI Studio | GCP service account keys require per-project API enablement and expire |
| `fpdf2` + DejaVu fonts for PDF | Native Unicode + Hebrew RTL support without external dependencies |
| APScheduler inside FastAPI lifespan | No external cron needed, scheduler lives with the server process |
| Gmail API for email sending | OAuth token already exists, no extra credentials needed |
| Strip HTML before Gemini | Raw HTML tag soup caused 0.00 amount extraction on billing emails |
| Regex extract sheet ID from URL | Users paste full Google Sheets URLs, not bare IDs |
| `gspread.Client(auth=creds)` | `gspread.authorize()` deprecated in recent versions |
