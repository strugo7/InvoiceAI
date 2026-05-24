import os
import json
import logging
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from contextlib import asynccontextmanager

from agent import GmailInvoiceAgent, CACHE_FILE, get_connected_accounts, disconnect_account, connect_new_gmail_account
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

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

class SettingsModel(BaseModel):
    use_mock: bool = True
    sheet_id: Optional[str] = ""

def load_config() -> Dict[str, Any]:
    """Loads configuration settings from config.json."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading config: {e}")
    
    # Default config
    default_config = {"use_mock": True, "sheet_id": ""}
    save_config(default_config)
    return default_config

def save_config(config: Dict[str, Any]):
    """Saves configuration settings to config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Error saving config: {e}")


@app.get("/api/settings")
def get_settings():
    """Retrieve current settings."""
    return load_config()


@app.post("/api/settings")
def update_settings(settings: SettingsModel):
    """Update settings."""
    config = settings.model_dump()
    save_config(config)
    return {"status": "success", "message": "Settings updated successfully", "config": config}


@app.get("/api/invoices")
def get_invoices():
    """Retrieve all parsed/cached invoices."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {"status": "success", "data": data}
        except Exception as e:
            logging.error(f"Error reading cache file: {e}")
            raise HTTPException(status_code=500, detail=f"Error reading invoice cache: {str(e)}")
    
    # If no cache exists, return empty list or run mock generator to show something by default
    logging.info("No invoice cache found. Generating initial mock data for first-time dashboard load.")
    from agent import generate_mock_invoices
    mock_data = generate_mock_invoices()
    
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(mock_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Error writing initial cache: {e}")
        
    return {"status": "success", "data": mock_data}


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
