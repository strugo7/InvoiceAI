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
