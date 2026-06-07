# backend/scheduler.py
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler(timezone="Asia/Jerusalem")


async def _monthly_scan_job():
    """
    Scan every registered user's Gmail on the 20th at 08:00 so their dashboards
    stay fresh. Each user is scanned independently using their own stored
    credentials. (Email-report delivery was removed when the gmail.send scope was
    dropped for the public build — users view/download reports in-app instead.)
    """
    from agent import GmailInvoiceAgent
    from auth import list_user_emails

    now = datetime.now()
    month_label = now.strftime("%B %Y")
    user_emails = list_user_emails()
    logging.info(f"[Scheduler] Starting monthly scan for {len(user_emails)} user(s) — {month_label}")

    agent = GmailInvoiceAgent(use_mock=False)
    for email in user_emails:
        try:
            result = await agent.scan_and_process(user_email=email)
            logging.info(f"[Scheduler] Scanned {email}: {result.get('message')}")
        except Exception as e:
            logging.error(f"[Scheduler] Scan failed for {email}: {e}")


def start_scheduler():
    """Register the monthly job and start the scheduler."""
    scheduler.add_job(
        _monthly_scan_job,
        CronTrigger(day=20, hour=8, minute=0),
        id="monthly_scan",
        replace_existing=True,
    )
    scheduler.start()
    logging.info("[Scheduler] Started — monthly scan job scheduled for day 20 at 08:00 IST")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
