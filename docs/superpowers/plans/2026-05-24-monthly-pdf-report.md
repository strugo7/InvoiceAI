# Monthly PDF Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-generate a monthly PDF expense report on the 20th of each month, save it for in-app download, and email it to ofekst@ip-com.co.il.

**Architecture:** `report_generator.py` builds the PDF from `invoices.json`; `mailer.py` sends it via the existing Gmail OAuth token; `scheduler.py` wires an APScheduler job to run both on the 20th of each month at 08:00. Two new FastAPI endpoints expose manual download and send. A month-picker + two buttons are added to the Invoices tab in the frontend.

**Tech Stack:** fpdf2 (PDF), python-bidi (Hebrew RTL rendering), apscheduler (cron), Gmail API via google-api-python-client (email), existing FastAPI + vanilla JS frontend.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `backend/report_generator.py` | Build monthly PDF from invoice list |
| Create | `backend/mailer.py` | Send PDF as email attachment via Gmail API |
| Create | `backend/scheduler.py` | APScheduler job — scan + report + email on day 20 |
| Modify | `backend/server.py` | Add 2 report endpoints + start scheduler on startup |
| Modify | `backend/requirements.txt` | Add fpdf2, apscheduler, python-bidi |
| Already done | `backend/fonts/DejaVuSans.ttf` | Hebrew-capable font bundled in repo |
| Modify | `frontend/index.html` | Add month picker + Download + Send buttons |
| Modify | `frontend/app.js` | Wire buttons to API endpoints |

---

## Task 1: Install dependencies

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Install packages into venv**

```bash
cd /Users/ofekstrogo/.gemini/antigravity/scratch/gmail-invoice-tracker/backend
source venv/bin/activate
pip install fpdf2 apscheduler python-bidi
```

Expected output: `Successfully installed fpdf2-... apscheduler-... python-bidi-...`

- [ ] **Step 2: Add to requirements.txt**

Replace the last line of `backend/requirements.txt` so the file reads:
```
fastapi==0.110.0
uvicorn==0.28.0
pydantic==2.6.4
google-auth-oauthlib==1.2.0
google-api-python-client==2.122.0
gspread==6.1.0
python-multipart==0.0.9
python-dotenv==1.0.1
google-genai
fpdf2
apscheduler
python-bidi
```

- [ ] **Step 3: Verify font exists**

```bash
ls backend/fonts/DejaVuSans.ttf
```

Expected: file path printed (font was downloaded as part of plan setup).

---

## Task 2: Create report_generator.py

**Files:**
- Create: `backend/report_generator.py`

- [ ] **Step 1: Create the file**

```python
# backend/report_generator.py
import os
import json
from datetime import datetime
from typing import List, Dict, Any

from fpdf import FPDF
from bidi.algorithm import get_display

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf")
CACHE_FILE = os.path.join(os.path.dirname(__file__), "invoices.json")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")

CATEGORY_LABELS = {
    "SaaS/Subscription": "SaaS / Subscription",
    "Cloud/Hosting": "Cloud / Hosting",
    "Utilities": "Utilities",
    "Entertainment": "Entertainment",
    "Other": "Other",
}


def _rtl(text: str) -> str:
    """Render Hebrew/RTL text correctly for fpdf."""
    return get_display(str(text))


def load_invoices_for_month(year: int, month: int) -> List[Dict[str, Any]]:
    """Return invoices whose date starts with YYYY-MM."""
    prefix = f"{year:04d}-{month:02d}"
    if not os.path.exists(CACHE_FILE):
        return []
    with open(CACHE_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return [inv for inv in data if str(inv.get("date", "")).startswith(prefix)]


def generate_monthly_pdf(year: int, month: int) -> str:
    """
    Generate a PDF report for the given month.
    Returns the absolute path to the saved PDF file.
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)
    invoices = load_invoices_for_month(year, month)

    month_name = datetime(year, month, 1).strftime("%B %Y")
    filename = f"report_{year:04d}_{month:02d}.pdf"
    filepath = os.path.join(REPORTS_DIR, filename)

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_font("DejaVu", style="", fname=FONT_PATH)
    pdf.add_font("DejaVu", style="B", fname=FONT_PATH)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── Header ──────────────────────────────────────────────────────────────
    pdf.set_font("DejaVu", style="B", size=20)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 12, f"Monthly Expense Report — {month_name}", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_font("DejaVu", size=9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Total invoices: {len(invoices)}",
             new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)

    # ── Summary by category ─────────────────────────────────────────────────
    totals_by_cat: Dict[str, Dict[str, float]] = {}
    currency_totals: Dict[str, float] = {}

    for inv in invoices:
        cat = inv.get("category", "Other")
        cur = inv.get("currency", "USD")
        amt = float(inv.get("amount", 0))
        totals_by_cat.setdefault(cat, {}).setdefault(cur, 0)
        totals_by_cat[cat][cur] += amt
        currency_totals.setdefault(cur, 0)
        currency_totals[cur] += amt

    pdf.set_font("DejaVu", style="B", size=12)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 8, "Summary by Category", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(200, 200, 200)
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 267, pdf.get_y())
    pdf.ln(2)

    pdf.set_font("DejaVu", size=10)
    col_w = [90, 80, 80]
    pdf.set_fill_color(245, 245, 245)
    pdf.set_text_color(60, 60, 60)
    for header, w in zip(["Category", "Currency", "Total"], col_w):
        pdf.cell(w, 7, header, border=0, fill=True, align="L")
    pdf.ln()

    for cat, cur_map in sorted(totals_by_cat.items()):
        for cur, total in cur_map.items():
            label = CATEGORY_LABELS.get(cat, cat)
            pdf.set_font("DejaVu", size=9)
            pdf.cell(col_w[0], 6, label, align="L")
            pdf.cell(col_w[1], 6, cur, align="L")
            pdf.cell(col_w[2], 6, f"{total:,.2f}", align="L")
            pdf.ln()

    pdf.ln(2)
    pdf.set_font("DejaVu", style="B", size=10)
    pdf.set_text_color(30, 30, 30)
    for cur, total in sorted(currency_totals.items()):
        pdf.cell(col_w[0], 7, "TOTAL", align="L")
        pdf.cell(col_w[1], 7, cur, align="L")
        pdf.cell(col_w[2], 7, f"{total:,.2f}", align="L")
        pdf.ln()

    pdf.ln(6)

    # ── Invoice table ────────────────────────────────────────────────────────
    pdf.set_font("DejaVu", style="B", size=12)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 8, "Invoice Details", new_x="LMARGIN", new_y="NEXT")
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 267, pdf.get_y())
    pdf.ln(2)

    col_headers = ["Date", "Service", "Category", "Amount", "Currency", "Invoice ID", "Description"]
    col_widths  = [25,     55,        45,          22,       20,         38,            62]

    pdf.set_font("DejaVu", style="B", size=9)
    pdf.set_fill_color(50, 50, 80)
    pdf.set_text_color(255, 255, 255)
    for header, w in zip(col_headers, col_widths):
        pdf.cell(w, 7, header, border=0, fill=True, align="C")
    pdf.ln()

    pdf.set_font("DejaVu", size=8)
    fill = False
    for inv in sorted(invoices, key=lambda x: x.get("date", ""), reverse=True):
        pdf.set_fill_color(248, 248, 255) if fill else pdf.set_fill_color(255, 255, 255)
        pdf.set_text_color(40, 40, 40)
        service = str(inv.get("service_name", ""))[:28]
        cat = CATEGORY_LABELS.get(inv.get("category", "Other"), inv.get("category", ""))[:22]
        inv_id = str(inv.get("invoice_id") or "")[:18]
        desc = str(inv.get("description") or "")[:32]
        row = [
            inv.get("date", ""),
            service,
            cat,
            f"{float(inv.get('amount', 0)):,.2f}",
            inv.get("currency", ""),
            inv_id,
            desc,
        ]
        for val, w in zip(row, col_widths):
            pdf.cell(w, 6, str(val), border=0, fill=True, align="L")
        pdf.ln()
        fill = not fill

    # ── Footer ───────────────────────────────────────────────────────────────
    pdf.set_y(-12)
    pdf.set_font("DejaVu", size=8)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(0, 6, "Generated automatically by Gmail Invoice Tracker", align="C")

    pdf.output(filepath)
    return filepath
```

- [ ] **Step 2: Smoke-test manually**

```bash
cd /Users/ofekstrogo/.gemini/antigravity/scratch/gmail-invoice-tracker/backend
source venv/bin/activate
python3 -c "
from report_generator import generate_monthly_pdf
path = generate_monthly_pdf(2026, 5)
print('PDF created at:', path)
"
```

Expected: `PDF created at: .../backend/reports/report_2026_05.pdf`
Open the file and confirm the table renders with correct data.

- [ ] **Step 3: Commit**

```bash
cd /Users/ofekstrogo/.gemini/antigravity/scratch/gmail-invoice-tracker
git add backend/report_generator.py backend/fonts/DejaVuSans.ttf backend/requirements.txt
git commit -m "feat: add monthly PDF report generator with Hebrew font support"
```

---

## Task 3: Create mailer.py

**Files:**
- Create: `backend/mailer.py`

- [ ] **Step 1: Create the file**

```python
# backend/mailer.py
import os
import base64
import glob
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

BACKEND_DIR = os.path.dirname(__file__)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _get_credentials() -> Credentials:
    """Load and refresh the first available OAuth token."""
    token_files = glob.glob(os.path.join(BACKEND_DIR, "token_*.json"))
    if not token_files:
        legacy = os.path.join(BACKEND_DIR, "token.json")
        if os.path.exists(legacy):
            token_files = [legacy]
    if not token_files:
        raise FileNotFoundError("No Gmail OAuth token found. Connect a Gmail account first.")
    token_path = token_files[0]
    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return creds


def send_report_email(pdf_path: str, month_label: str, recipient: str) -> None:
    """Send the PDF report as an email attachment via Gmail API."""
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds)

    msg = MIMEMultipart()
    msg["To"] = recipient
    msg["Subject"] = f"Monthly Expense Report — {month_label}"

    body = MIMEText(
        f"Hi,\n\nPlease find attached the monthly expense report for {month_label}.\n\n"
        "This report was generated automatically by Gmail Invoice Tracker.\n\nBest regards",
        "plain",
        "utf-8",
    )
    msg.attach(body)

    with open(pdf_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f'attachment; filename="{os.path.basename(pdf_path)}"',
    )
    msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    logging.info(f"Report email sent to {recipient} for {month_label}")
```

- [ ] **Step 2: Verify import works**

```bash
cd /Users/ofekstrogo/.gemini/antigravity/scratch/gmail-invoice-tracker/backend
source venv/bin/activate
python3 -c "from mailer import send_report_email; print('mailer OK')"
```

Expected: `mailer OK`

- [ ] **Step 3: Commit**

```bash
git add backend/mailer.py
git commit -m "feat: add Gmail API mailer for sending PDF report as email attachment"
```

---

## Task 4: Create scheduler.py

**Files:**
- Create: `backend/scheduler.py`

- [ ] **Step 1: Create the file**

```python
# backend/scheduler.py
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

REPORT_RECIPIENT = "ofekst@ip-com.co.il"

scheduler = AsyncIOScheduler(timezone="Asia/Jerusalem")


async def _monthly_report_job():
    """Scan Gmail, generate PDF report, send by email. Runs on the 20th at 08:00."""
    import json, os
    from agent import GmailInvoiceAgent, CACHE_FILE
    from report_generator import generate_monthly_pdf
    from mailer import send_report_email

    now = datetime.now()
    year, month = now.year, now.month
    month_label = now.strftime("%B %Y")

    logging.info(f"[Scheduler] Starting monthly report job for {month_label}")

    # 1. Scan Gmail
    agent = GmailInvoiceAgent(use_mock=False)
    result = await agent.scan_and_process()
    if result.get("status") != "success":
        logging.error(f"[Scheduler] Scan failed: {result.get('message')}")
        return

    # 2. Generate PDF
    pdf_path = generate_monthly_pdf(year, month)
    logging.info(f"[Scheduler] PDF generated at {pdf_path}")

    # 3. Send email
    try:
        send_report_email(pdf_path, month_label, REPORT_RECIPIENT)
    except Exception as e:
        logging.error(f"[Scheduler] Email send failed: {e}")


def start_scheduler():
    """Register the monthly job and start the scheduler."""
    scheduler.add_job(
        _monthly_report_job,
        CronTrigger(day=20, hour=8, minute=0),
        id="monthly_report",
        replace_existing=True,
    )
    scheduler.start()
    logging.info("[Scheduler] Started — monthly report job scheduled for day 20 at 08:00 IST")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
```

- [ ] **Step 2: Verify import**

```bash
python3 -c "from scheduler import start_scheduler; print('scheduler OK')"
```

Expected: `scheduler OK`

- [ ] **Step 3: Commit**

```bash
git add backend/scheduler.py
git commit -m "feat: add APScheduler monthly report job (day 20, 08:00 IST)"
```

---

## Task 5: Add report endpoints to server.py + start scheduler

**Files:**
- Modify: `backend/server.py`

- [ ] **Step 1: Add imports at top of server.py**

After the existing imports block (after `from agent import ...`), add:

```python
from fastapi.responses import FileResponse
from report_generator import generate_monthly_pdf, load_invoices_for_month
from mailer import send_report_email
from scheduler import start_scheduler, stop_scheduler
```

- [ ] **Step 2: Add the two report endpoints**

Add these two endpoints just before the `# Serve frontend static files` comment:

```python
@app.get("/api/reports/monthly")
def download_monthly_report(month: str = ""):
    """Generate and return the PDF report for a given month (YYYY-MM). Defaults to current month."""
    from datetime import datetime
    if not month:
        now = datetime.now()
        year, mon = now.year, now.month
    else:
        try:
            dt = datetime.strptime(month, "%Y-%m")
            year, mon = dt.year, dt.month
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM.")

    invoices = load_invoices_for_month(year, mon)
    if not invoices:
        raise HTTPException(status_code=404, detail=f"No invoices found for {month or 'current month'}.")

    pdf_path = generate_monthly_pdf(year, mon)
    filename = f"expense_report_{year:04d}_{mon:02d}.pdf"
    return FileResponse(pdf_path, media_type="application/pdf", filename=filename)


@app.post("/api/reports/send")
async def send_monthly_report(month: str = ""):
    """Generate PDF and email it to the configured recipient."""
    from datetime import datetime
    if not month:
        now = datetime.now()
        year, mon = now.year, now.month
    else:
        try:
            dt = datetime.strptime(month, "%Y-%m")
            year, mon = dt.year, dt.month
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM.")

    invoices = load_invoices_for_month(year, mon)
    if not invoices:
        raise HTTPException(status_code=404, detail=f"No invoices found for {month or 'current month'}.")

    pdf_path = generate_monthly_pdf(year, mon)
    month_label = datetime(year, mon, 1).strftime("%B %Y")
    try:
        import asyncio
        await asyncio.to_thread(send_report_email, pdf_path, month_label, "ofekst@ip-com.co.il")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

    return {"status": "success", "message": f"Report for {month_label} sent to ofekst@ip-com.co.il"}
```

- [ ] **Step 3: Start scheduler on app startup**

Add a lifespan handler. Replace the line `app = FastAPI(...)` at the top of server.py with:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()

app = FastAPI(
    title="Gmail Invoice Tracker API",
    description="Backend API for AI Gmail Invoice Agent",
    lifespan=lifespan,
)
```

- [ ] **Step 4: Restart server and verify endpoints appear**

```bash
pkill -f "uvicorn server:app"; sleep 1
source venv/bin/activate && uvicorn server:app --reload --port 8000
```

Then in another terminal:
```bash
curl -s http://localhost:8000/docs | grep -o "monthly"
```

Expected: `monthly` appears (FastAPI auto-docs lists the endpoints).

- [ ] **Step 5: Test download endpoint**

```bash
curl -s "http://localhost:8000/api/reports/monthly?month=2026-05" -o /tmp/test_report.pdf
file /tmp/test_report.pdf
```

Expected: `PDF document`

- [ ] **Step 6: Commit**

```bash
git add backend/server.py
git commit -m "feat: add /api/reports/monthly and /api/reports/send endpoints, start scheduler on startup"
```

---

## Task 6: Add report UI to frontend

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`

- [ ] **Step 1: Add report controls bar in index.html**

Find this block in index.html (the invoices tab, just after `<section class="tab-content" id="tab-invoices">`):

```html
<div class="table-filter-bar glass-panel">
```

Insert a new `div` **above** that line:

```html
<div class="report-bar glass-panel" style="display:flex;align-items:center;gap:12px;padding:12px 16px;margin-bottom:12px;flex-wrap:wrap;">
    <span style="font-weight:600;font-size:14px;">דוח חודשי:</span>
    <input type="month" id="report-month-picker" style="padding:6px 10px;border-radius:8px;border:1px solid #444;background:#1e1e2e;color:#fff;font-size:13px;">
    <button id="btn-download-report" class="action-btn" style="padding:7px 16px;border-radius:8px;background:#6c63ff;color:#fff;border:none;cursor:pointer;font-size:13px;">
        <i class="fa-solid fa-file-pdf"></i> הורד PDF
    </button>
    <button id="btn-send-report" class="action-btn" style="padding:7px 16px;border-radius:8px;background:#2ecc71;color:#fff;border:none;cursor:pointer;font-size:13px;">
        <i class="fa-solid fa-envelope"></i> שלח במייל
    </button>
    <span id="report-status" style="font-size:12px;color:#aaa;"></span>
</div>
```

- [ ] **Step 2: Set default month value in app.js**

Find the `fetchInvoices` function or the DOMContentLoaded / init section in app.js. Add this code inside the initialization block (where other UI setup happens):

```javascript
// Set month picker default to current month
const picker = document.getElementById('report-month-picker');
if (picker) {
    const now = new Date();
    picker.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}
```

- [ ] **Step 3: Wire the Download button in app.js**

Add this function and event listener (can be placed near the bottom of app.js before the closing DOMContentLoaded block):

```javascript
function setupReportButtons() {
    const downloadBtn = document.getElementById('btn-download-report');
    const sendBtn = document.getElementById('btn-send-report');
    const statusEl = document.getElementById('report-status');
    const picker = document.getElementById('report-month-picker');

    if (!downloadBtn || !sendBtn) return;

    downloadBtn.addEventListener('click', async () => {
        const month = picker.value;
        if (!month) { statusEl.textContent = 'בחר חודש תחילה'; return; }
        statusEl.textContent = 'מייצר דוח...';
        try {
            const res = await fetch(`/api/reports/monthly?month=${month}`);
            if (!res.ok) {
                const err = await res.json();
                statusEl.textContent = `שגיאה: ${err.detail}`;
                return;
            }
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `expense_report_${month}.pdf`;
            a.click();
            URL.revokeObjectURL(url);
            statusEl.textContent = 'הדוח הורד בהצלחה ✓';
        } catch (e) {
            statusEl.textContent = 'שגיאה בהורדת הדוח';
        }
    });

    sendBtn.addEventListener('click', async () => {
        const month = picker.value;
        if (!month) { statusEl.textContent = 'בחר חודש תחילה'; return; }
        statusEl.textContent = 'שולח מייל...';
        sendBtn.disabled = true;
        try {
            const res = await fetch(`/api/reports/send?month=${month}`, { method: 'POST' });
            const data = await res.json();
            if (!res.ok) { statusEl.textContent = `שגיאה: ${data.detail}`; return; }
            statusEl.textContent = `נשלח ל-ofekst@ip-com.co.il ✓`;
        } catch (e) {
            statusEl.textContent = 'שגיאה בשליחת המייל';
        } finally {
            sendBtn.disabled = false;
        }
    });
}
```

- [ ] **Step 4: Call setupReportButtons() in the init block**

Find where other setup functions are called (e.g., `setupAccountsConnector()` or similar). Add:

```javascript
setupReportButtons();
```

- [ ] **Step 5: Manual end-to-end test**

1. Open `http://localhost:8000`
2. Go to the **חשבוניות** tab
3. Confirm the report bar appears at the top with a month picker and two buttons
4. Select `2026-05`, click **הורד PDF** — a PDF should download
5. Open the PDF and verify it shows the real invoices with totals
6. Click **שלח במייל** — confirm status shows "נשלח ל-ofekst@ip-com.co.il ✓"
7. Check `ofekst@ip-com.co.il` inbox for the email with PDF attachment

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html frontend/app.js
git commit -m "feat: add monthly report UI — month picker, download PDF and send email buttons"
```

---

## Task 7: Re-authorize Gmail for send permission

> The current OAuth token was issued with `gmail.readonly` scope. Sending email requires `gmail.send`. The user must re-authorize.

**Files:**
- Modify: `backend/agent.py` (update SCOPES in `connect_new_gmail_account`)

- [ ] **Step 1: Add gmail.send scope to connect_new_gmail_account in agent.py**

Find this line in `connect_new_gmail_account()`:

```python
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/spreadsheets']
```

Replace with:

```python
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/spreadsheets',
]
```

- [ ] **Step 2: Delete old token so re-auth is triggered**

```bash
cd /Users/ofekstrogo/.gemini/antigravity/scratch/gmail-invoice-tracker/backend
rm -f token_*.json token.json
```

- [ ] **Step 3: Reconnect Gmail account via the app**

In the app, go to **הגדרות** → click **חבר חשבון Gmail**. Complete the OAuth flow in the browser. This time the consent screen will ask for send permission as well.

- [ ] **Step 4: Verify token has send scope**

```bash
python3 -c "
import json, glob
files = glob.glob('token_*.json')
if files:
    data = json.load(open(files[0]))
    print('Scopes:', data.get('scopes', data.get('scope', 'not found')))
"
```

Expected: output includes `gmail.send`

- [ ] **Step 5: Commit**

```bash
git add backend/agent.py
git commit -m "feat: add gmail.send scope to OAuth flow for email sending"
```
