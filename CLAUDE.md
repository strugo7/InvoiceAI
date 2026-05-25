# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
cd backend && pip install -r requirements.txt

# Run the server (serves both frontend and API on port 8000)
cd backend && python server.py

# Test agent logic in mock mode (no Gmail/Sheets access needed)
cd backend && python test_agent.py
```

The frontend is vanilla HTML/JS with no build step — it is served statically by FastAPI at `http://localhost:8000`.

## Architecture

**Gmail Invoice Tracker** is an AI-powered expense tracker. It reads Gmail inboxes, extracts invoice data via Gemini 2.5 Flash (structured output), optionally syncs to Google Sheets, and presents a glassmorphic dashboard.

### Key files

| File | Role |
|------|------|
| `backend/server.py` | FastAPI app — routes, lifespan, static file serving |
| `backend/agent.py` | `GmailInvoiceAgent` — core extraction loop; calls Gmail API → Gemini → Sheets |
| `backend/scheduler.py` | APScheduler CronTrigger that fires on day 20 at 08:00 IST |
| `backend/report_generator.py` | PDF report generation via fpdf2 (RTL Hebrew support via Bidi) |
| `backend/mailer.py` | Send emails with PDF attachments using Gmail API |
| `frontend/index.html` | Main dashboard — tabs for Dashboard, Invoices, Settings |
| `frontend/app.js` | All frontend JS (~987 lines); handles sync, pagination, charts, modals |
| `frontend/style.css` | Glassmorphism dark theme — CSS variables, component styles |
| `frontend/admin.html` | Admin panel for diagnostics and account management |

### Data flow (sync cycle)

1. User clicks Sync → `POST /api/sync` → `GmailInvoiceAgent.scan_and_process()`
2. Agent fetches `token_*.json` OAuth tokens, queries Gmail API for recent emails
3. Email body (plain text preferred; HTML stripped as fallback) is sent to Gemini 2.5 Flash with a structured `InvoiceDetail` Pydantic schema
4. Parsed invoices are written to Google Sheets (if `sheet_id` configured) and cached in `invoices.json`
5. Frontend re-renders Chart.js graphs and the invoices table

### Mock vs Production mode

Controlled by `backend/config.json` → `"use_mock": true/false`.

- **Mock mode (default):** Generates deterministic invoices for 3 months; no external credentials needed.
- **Production mode:** Requires `credentials.json` (OAuth client from GCP), `backend/.env` with `GEMINI_API_KEY`, and per-account `token_*.json` files created via OAuth flow.

### Configuration files

| File | Content |
|------|---------|
| `backend/config.json` | `use_mock` (bool), `sheet_id` (Google Sheets URL or ID) |
| `backend/.env` | `GEMINI_API_KEY` |
| `backend/credentials.json` | OAuth Client ID + Secret (from Google Cloud Console) |
| `backend/token_*.json` | Per-account OAuth refresh tokens (auto-created on first auth) |
| `backend/invoices.json` | Local invoice cache (JSON array) |

### AI extraction details

- Model: `gemini-2.5-flash` via `google-genai` SDK (not `google.generativeai` — that package is deprecated)
- Uses structured output with Pydantic v2 `InvoiceDetail` schema defined in `agent.py`
- Handles Hebrew currency strings: ₪, שח, ש"ח
- Gemini API key is loaded from `backend/.env` using `python-dotenv`

### Frontend theme

Glassmorphism dark theme: semi-transparent panels (`rgba(20,20,35,0.45)`), neon purple (`#8b5cf6`) and cyan (`#06b6d4`) accents, base background `#09090e`. RTL-aware with Hebrew navigation labels.
