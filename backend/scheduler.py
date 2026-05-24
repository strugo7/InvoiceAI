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
