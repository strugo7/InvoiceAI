import os
import json
import logging
from fastapi import FastAPI, HTTPException, BackgroundTasks, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from contextlib import asynccontextmanager

from agent import GmailInvoiceAgent, get_connected_accounts, disconnect_account, connect_new_gmail_account
from fastapi.responses import FileResponse
from report_generator import generate_monthly_pdf, load_invoices_for_month
from mailer import send_report_email
from scheduler import start_scheduler, stop_scheduler

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


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

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from dotenv import set_key

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")

class SettingsModel(BaseModel):
    use_mock: bool = False
    sheet_id: Optional[str] = ""

def load_config() -> Dict[str, Any]:
    """Loads configuration settings.

    `use_mock` is stored in config.json (safe to commit). `sheet_id` is sourced
    from the SHEET_ID env var (.env, untracked) so the resource id never lands in
    version control.
    """
    config: Dict[str, Any] = {"use_mock": False}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                stored = json.load(f)
                config["use_mock"] = stored.get("use_mock", False)
        except Exception as e:
            logging.error(f"Error loading config: {e}")
    else:
        save_config(config)

    config["sheet_id"] = os.environ.get("SHEET_ID", "")
    return config

def save_config(config: Dict[str, Any]):
    """Persists `use_mock` to config.json.

    `sheet_id` is intentionally NOT written here — it lives in .env (see
    update_settings) to keep it out of git.
    """
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"use_mock": config.get("use_mock", False)}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Error saving config: {e}")


@app.get("/api/settings")
def get_settings():
    """Retrieve current settings."""
    return load_config()


@app.post("/api/settings")
def update_settings(settings: SettingsModel):
    """Update settings. `use_mock` -> config.json; `sheet_id` -> .env (untracked)."""
    config = settings.model_dump()
    save_config(config)

    # Persist sheet_id to .env and the live environment so it never enters git.
    sheet_id = config.get("sheet_id") or ""
    try:
        set_key(ENV_FILE, "SHEET_ID", sheet_id)
        os.environ["SHEET_ID"] = sheet_id
    except Exception as e:
        logging.error(f"Error saving SHEET_ID to .env: {e}")

    return {"status": "success", "message": "Settings updated successfully", "config": load_config()}


@app.get("/api/invoices")
def get_invoices():
    """
    Retrieve all invoices for the dashboard. Supabase is the source of truth
    (falling back to the local JSON cache). Never fabricates mock data — an empty
    database returns an empty list so the dashboard only ever shows real records.
    """
    from agent import load_all_invoices
    try:
        data = load_all_invoices()
        return {"status": "success", "data": data}
    except Exception as e:
        logging.error(f"Error reading invoices: {e}")
        raise HTTPException(status_code=500, detail=f"Error reading invoices: {str(e)}")


@app.get("/api/invoices/{email_id}/document")
def get_invoice_document_endpoint(email_id: str, account: str):
    """
    Classify how an invoice can be viewed. Returns JSON:
      {"type": "pdf"}                                  -> stream via the /pdf route
      {"type": "page", "html": "...", "link": url|null} -> render email body + optional hosted link
      {"type": "none"}                                 -> nothing renderable
    """
    from agent import get_invoice_document
    return get_invoice_document(email_id, account)


@app.get("/api/invoices/{email_id}/pdf")
def get_invoice_pdf_endpoint(email_id: str, account: str):
    """
    Stream the original invoice PDF for a given Gmail message, fetched on demand
    from the user's mailbox. `account` is the scanned Gmail address (validated
    against connected accounts inside the agent). Served inline so the browser
    displays it without downloading.
    """
    from agent import get_invoice_pdf
    from urllib.parse import quote
    result = get_invoice_pdf(email_id, account)
    if not result:
        raise HTTPException(status_code=404, detail="PDF not found for this invoice")
    pdf_bytes, filename = result
    # HTTP headers are latin-1 only; encode non-ASCII (e.g. Hebrew) filenames per RFC 5987
    ascii_name = filename.encode("ascii", "ignore").decode() or "invoice.pdf"
    disposition = f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition},
    )


@app.post("/api/sync")
async def trigger_sync():
    """Manually trigger the Gmail scan agent."""
    config = load_config()
    use_mock = config.get("use_mock", True)
    sheet_id = config.get("sheet_id", "")
    
    # If sheet_id is empty, set to None
    sheet_id_param = sheet_id if sheet_id else None
    
    agent = GmailInvoiceAgent(use_mock=use_mock, sheet_id=sheet_id_param)
    
    logging.info(f"Sync triggered. Mode: {'MOCK' if use_mock else 'PRODUCTION'}")
    
    result = await agent.scan_and_process()
    
    if result["status"] == "success":
        return result
    else:
        raise HTTPException(status_code=500, detail=result.get("message", "Synchronization failed."))


# --- Multi-Account Gmail API routes ---

@app.get("/api/accounts")
def get_accounts():
    """Get list of currently connected Gmail accounts."""
    accounts = get_connected_accounts()
    return {"status": "success", "accounts": accounts}


@app.post("/api/accounts/connect")
async def connect_account():
    """Trigger OAuth flow to connect a new Gmail account."""
    try:
        email = await connect_new_gmail_account()
        return {"status": "success", "message": f"Successfully connected account: {email}", "email": email}
    except FileNotFoundError as fnf_err:
        raise HTTPException(status_code=400, detail=str(fnf_err))
    except Exception as e:
        logging.error(f"OAuth Account connection failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to connect account: {str(e)}")


@app.delete("/api/accounts/{email}")
def remove_account(email: str):
    """Disconnect and delete credentials for a specific account email."""
    success = disconnect_account(email)
    if success:
        return {"status": "success", "message": f"Successfully disconnected account: {email}"}
    else:
        raise HTTPException(status_code=404, detail=f"Account token for {email} not found.")


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


# Serve frontend static files
# We mount this at the very end so that API routes take priority.
# The index.html should be served at the root '/' path.
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
else:
    logging.warning(f"Frontend directory not found at {frontend_dir}. Please create it to serve static files.")


if __name__ == "__main__":
    import uvicorn
    load_config()
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
