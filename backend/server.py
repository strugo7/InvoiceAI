import os
import json
import logging
from fastapi import FastAPI, HTTPException, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Dict, Any

from contextlib import asynccontextmanager

from agent import GmailInvoiceAgent
from fastapi.responses import FileResponse
from report_generator import generate_monthly_pdf, load_invoices_for_month
from scheduler import start_scheduler, stop_scheduler
from auth import router as auth_router, get_current_user

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

# CORS: only enable for explicitly allowed origins (never "*", since we use
# credentialed cookies). The frontend is served same-origin by this app, so CORS
# is typically unnecessary — set APP_ORIGIN only if a separate frontend host is used.
_origins = [o.strip() for o in os.environ.get("APP_ORIGIN", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Google Sign-In auth routes (/api/auth/login, /callback, /me, /logout)
app.include_router(auth_router)

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

class SettingsModel(BaseModel):
    use_mock: bool = False

def load_config() -> Dict[str, Any]:
    """Loads configuration settings from config.json."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading config: {e}")

    # Default config
    default_config = {"use_mock": False}
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
def get_settings(user: Dict[str, Any] = Depends(get_current_user)):
    """Retrieve current settings."""
    return load_config()


@app.post("/api/settings")
def update_settings(settings: SettingsModel, user: Dict[str, Any] = Depends(get_current_user)):
    """Update settings (deployment-level run mode)."""
    config = settings.model_dump()
    save_config(config)
    return {"status": "success", "message": "Settings updated successfully", "config": config}


@app.get("/api/invoices")
def get_invoices(user: Dict[str, Any] = Depends(get_current_user)):
    """Retrieve the signed-in user's invoices for the dashboard (from Supabase)."""
    from agent import load_all_invoices
    try:
        data = load_all_invoices(user["email"])
        return {"status": "success", "data": data}
    except Exception as e:
        logging.error(f"Error reading invoices: {e}")
        raise HTTPException(status_code=500, detail=f"Error reading invoices: {str(e)}")


@app.get("/api/invoices/{email_id}/document")
def get_invoice_document_endpoint(email_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """
    Classify how an invoice can be viewed for the signed-in user. Returns JSON:
      {"type": "pdf"}                                  -> stream via the /pdf route
      {"type": "page", "html": "...", "link": url|null} -> render email body + optional hosted link
      {"type": "none"}                                 -> nothing renderable
    """
    from agent import get_invoice_document
    return get_invoice_document(email_id, user["email"])


@app.get("/api/invoices/{email_id}/pdf")
def get_invoice_pdf_endpoint(email_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """
    Stream the original invoice PDF for a given Gmail message, fetched on demand
    from the signed-in user's own mailbox. Served inline so the browser displays it.
    """
    from agent import get_invoice_pdf
    from urllib.parse import quote
    result = get_invoice_pdf(email_id, user["email"])
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
async def trigger_sync(user: Dict[str, Any] = Depends(get_current_user)):
    """Manually trigger the Gmail scan agent for the signed-in user."""
    config = load_config()
    use_mock = config.get("use_mock", False)

    agent = GmailInvoiceAgent(use_mock=use_mock)

    logging.info(f"Sync triggered by {user['email']}. Mode: {'MOCK' if use_mock else 'PRODUCTION'}")

    result = await agent.scan_and_process(user_email=user["email"])

    if result["status"] == "success":
        return result
    else:
        raise HTTPException(status_code=500, detail=result.get("message", "Synchronization failed."))


@app.get("/api/reports/monthly")
def download_monthly_report(month: str = "", user: Dict[str, Any] = Depends(get_current_user)):
    """Generate and return the signed-in user's PDF report for a month (YYYY-MM)."""
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

    invoices = load_invoices_for_month(year, mon, user["email"])
    if not invoices:
        raise HTTPException(status_code=404, detail=f"No invoices found for {month or 'current month'}.")

    pdf_path = generate_monthly_pdf(year, mon, user["email"])
    filename = f"expense_report_{year:04d}_{mon:02d}.pdf"
    return FileResponse(pdf_path, media_type="application/pdf", filename=filename)


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
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
