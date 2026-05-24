import os
import json
import logging
import asyncio
import glob
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import pydantic
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Target schema for structured extraction using Pydantic
class InvoiceDetail(pydantic.BaseModel):
    service_name: str = pydantic.Field(description="The name of the service/company, e.g., 'OpenAI', 'Google Cloud', 'Netflix', 'Netlify'.")
    date: str = pydantic.Field(description="The date of the invoice in YYYY-MM-DD format.")
    amount: float = pydantic.Field(description="The numeric amount paid.")
    currency: str = pydantic.Field(description="The currency of the payment, e.g., 'USD', 'ILS', 'EUR'. Use standard 3-letter codes.")
    category: str = pydantic.Field(description="The category of the expense: 'SaaS/Subscription', 'Cloud/Hosting', 'Utilities', 'Marketing', 'Entertainment', or 'Other'.")
    invoice_id: Optional[str] = pydantic.Field(None, description="The invoice number or transaction ID, if found.")
    description: Optional[str] = pydantic.Field(None, description="A brief description of what was purchased (e.g., 'API Usage', 'Premium Plan').")

class InvoiceExtractionList(pydantic.BaseModel):
    invoices: List[InvoiceDetail]

# Local Cache File for Simulation / Backup
CACHE_FILE = os.path.join(os.path.dirname(__file__), "invoices.json")
BACKEND_DIR = os.path.dirname(__file__)

# Mock Invoices Generator for Simulation Mode
def generate_mock_invoices() -> List[Dict[str, Any]]:
    """Generates rich, realistic mock invoice data representing monthly expenses."""
    today = datetime.now()
    
    # Standard services and typical charges
    services = [
        {"name": "OpenAI", "category": "SaaS/Subscription", "amount_range": (15.0, 45.0), "currency": "USD", "desc": "ChatGPT Plus & API usage"},
        {"name": "Google Cloud", "category": "Cloud/Hosting", "amount_range": (20.0, 110.0), "currency": "USD", "desc": "Firebase & Compute Engine"},
        {"name": "Netflix", "category": "Entertainment", "amount_range": (69.90, 69.90), "currency": "ILS", "desc": "Monthly Premium Subscription"},
        {"name": "Netlify", "category": "Cloud/Hosting", "amount_range": (19.0, 19.0), "currency": "USD", "desc": "Pro Plan hosting"},
        {"name": "Adobe Creative Cloud", "category": "SaaS/Subscription", "amount_range": (185.0, 185.0), "currency": "ILS", "desc": "Creative Cloud Photography Plan"},
        {"name": "GitHub", "category": "SaaS/Subscription", "amount_range": (4.0, 10.0), "currency": "USD", "desc": "GitHub Copilot & private repos"},
        {"name": "Vercel", "category": "Cloud/Hosting", "amount_range": (20.0, 20.0), "currency": "USD", "desc": "Pro Subscription"},
        {"name": "Spotify", "category": "Entertainment", "amount_range": (31.90, 31.90), "currency": "ILS", "desc": "Spotify Premium Family"},
        {"name": "Electric Bill", "category": "Utilities", "amount_range": (250.0, 450.0), "currency": "ILS", "desc": "Bi-monthly electric utility bill"},
        {"name": "Internet Service", "category": "Utilities", "amount_range": (99.0, 110.0), "currency": "ILS", "desc": "Fiber Optic 1Gbps"},
        {"name": "Zoom", "category": "SaaS/Subscription", "amount_range": (15.99, 15.99), "currency": "USD", "desc": "Pro Meeting Plan"},
        {"name": "Figma", "category": "SaaS/Subscription", "amount_range": (15.0, 30.0), "currency": "USD", "desc": "Professional Design Editor Team"}
    ]
    
    mock_data = []
    # Generate for the past 3 months
    for month_offset in range(3, -1, -1):
        target_month = today - timedelta(days=30 * month_offset)
        
        # Pick 5-8 random bills per month
        import random
        random.seed(42 + month_offset) # Determistic but varied
        
        selected_services = random.sample(services, k=random.randint(6, 9))
        for idx, svc in enumerate(selected_services):
            # Calculate a random date in that month
            day = random.randint(1, 28)
            date_str = datetime(target_month.year, target_month.month, day).strftime("%Y-%m-%d")
            
            amount = round(random.uniform(svc["amount_range"][0], svc["amount_range"][1]), 2)
            invoice_id = f"INV-{target_month.year}{target_month.month:02d}-{idx:04d}"
            
            mock_data.append({
                "id": f"msg-mock-{target_month.year}-{target_month.month}-{idx}",
                "service_name": svc["name"],
                "date": date_str,
                "amount": amount,
                "currency": svc["currency"],
                "category": svc["category"],
                "invoice_id": invoice_id,
                "description": svc["desc"],
                "email_subject": f"Your monthly invoice for {svc['name']}"
            })
            
    # Sort by date descending
    mock_data.sort(key=lambda x: x["date"], reverse=True)
    return mock_data


def get_connected_accounts() -> List[str]:
    """Scans the backend directory and returns a list of connected Gmail addresses."""
    tokens = glob.glob(os.path.join(BACKEND_DIR, "token_*.json"))
    emails = []
    for t in tokens:
        filename = os.path.basename(t)
        # Extract email between 'token_' and '.json'
        email = filename[6:-5]
        emails.append(email)
    
    # Also support legacy token.json as 'legacy_default' if no other token is found
    legacy_token = os.path.join(BACKEND_DIR, "token.json")
    if os.path.exists(legacy_token) and not emails:
        emails.append("default_legacy")
        
    return emails


def disconnect_account(email: str) -> bool:
    """Deletes the token file corresponding to the specified email."""
    if email == "default_legacy":
        token_path = os.path.join(BACKEND_DIR, "token.json")
    else:
        token_path = os.path.join(BACKEND_DIR, f"token_{email}.json")
        
    if os.path.exists(token_path):
        os.remove(token_path)
        logging.info(f"Disconnected account and deleted token for: {email}")
        return True
    return False


async def connect_new_gmail_account() -> str:
    """Triggers OAuth 2.0 flow to authorize a new Gmail account and saves its token file dynamically."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = [
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/spreadsheets',
    ]
    creds_path = os.path.join(BACKEND_DIR, "credentials.json")
    
    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            "Credentials file 'credentials.json' not found. "
            "Please upload it to the backend folder before connecting an account."
        )
        
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    
    # Run the local server in a separate thread so it doesn't block the asyncio event loop
    creds = await asyncio.to_thread(flow.run_local_server, port=0, open_browser=True)
    
    # Query Gmail API to get the email address of the authenticated user
    service = build('gmail', 'v1', credentials=creds)
    profile = service.users().getProfile(userId='me').execute()
    email_address = profile.get("emailAddress")
    
    if not email_address:
        raise ValueError("Could not retrieve email address from authorized profile.")
        
    # Save the token to a dynamic path matching the email address
    token_path = os.path.join(BACKEND_DIR, f"token_{email_address}.json")
    with open(token_path, 'w') as token_file:
        token_file.write(creds.to_json())
        
    logging.info(f"Successfully connected new Gmail account: {email_address}")
    return email_address


class GmailInvoiceAgent:
    """Agent that processes Gmail accounts and stores invoice details in Google Sheets."""
    
    def __init__(self, use_mock: bool = True, sheet_id: Optional[str] = None):
        self.use_mock = use_mock
        self.sheet_id = sheet_id
        
    def _load_cached_invoices(self) -> List[Dict[str, Any]]:
        """Loads locally cached invoices from the JSON file."""
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Error loading cached invoices: {e}")
        return []

    def _save_cached_invoices(self, invoices: List[Dict[str, Any]]):
        """Saves invoices to the local JSON file cache."""
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(invoices, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Error saving cached invoices: {e}")

    async def scan_and_process(self) -> Dict[str, Any]:
        """Runs the main scanning and processing cycle."""
        if self.use_mock:
            logging.info("Running Gmail Invoice Agent in SIMULATION (MOCK) mode...")
            await asyncio.sleep(2.5) # Simulate AI processing time
            
            # Retrieve or generate mock data
            mock_invoices = generate_mock_invoices()
            
            # Save to local cache
            self._save_cached_invoices(mock_invoices)
            
            # If sheet ID is provided, try to write to Google Sheets too
            if self.sheet_id:
                try:
                    self._write_to_google_sheet(mock_invoices, token_path=None)
                except Exception as e:
                    logging.warning(f"Could not write mock data to Google Sheets: {e}. Keeping local cache.")
                    
            return {
                "status": "success",
                "mode": "simulation",
                "invoices_found": len(mock_invoices),
                "message": f"Successfully simulated scan. {len(mock_invoices)} mock invoices generated and stored.",
                "data": mock_invoices
            }
            
        else:
            logging.info("Running Gmail Invoice Agent in PRODUCTION mode...")
            
            # Get list of all dynamic tokens to scan
            connected_emails = get_connected_accounts()
            if not connected_emails:
                return {
                    "status": "error",
                    "mode": "production",
                    "message": "No Gmail accounts connected. Please connect at least one account in Settings."
                }
                
            new_invoices_total = []
            cached_data = self._load_cached_invoices()
            existing_ids = {inv.get("id") for inv in cached_data}
            
            try:
                from google import genai
                from google.genai import types

                SYSTEM_INSTRUCTION = (
                    "You are an expert financial auditor. Analyze the provided email text "
                    "(receipt, invoice, or monthly bill) and extract key financial data. "
                    "Rules:\n"
                    "- amount: extract the TOTAL amount as a positive float. Never return 0 unless the invoice truly is free. "
                    "Look for patterns like '104 ₪', '104.00 ש\"ח', '$19.00', '19.00 USD', 'סה\"כ 104'. "
                    "If the amount appears with a currency symbol (₪, $, €), strip the symbol and return the number.\n"
                    "- currency: ILS for ₪/שח/ש\"ח, USD for $, EUR for €. Use 3-letter ISO codes only.\n"
                    "- date: YYYY-MM-DD format strictly.\n"
                    "- If multiple invoices appear in the same email, extract all of them.\n"
                    "- service_name: the company or service name, not the email domain."
                )

                gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

                # Run the scan for each connected mailbox
                for email in connected_emails:
                    logging.info(f"Scanning mailbox: {email}")

                    # Set corresponding token path
                    if email == "default_legacy":
                        token_path = os.path.join(BACKEND_DIR, "token.json")
                    else:
                        token_path = os.path.join(BACKEND_DIR, f"token_{email}.json")

                    # Fetch emails using this specific token
                    try:
                        emails = self._fetch_invoice_emails(token_path)
                    except Exception as fetch_err:
                        logging.error(f"Failed to fetch emails for {email}: {fetch_err}")
                        continue

                    if not emails:
                        logging.info(f"No new invoice emails found in {email}")
                        continue

                    # Parse emails
                    for mail in emails:
                        msg_id = mail["id"]
                        if msg_id in existing_ids:
                            logging.info(f"Skipping duplicate email ID: {msg_id}")
                            continue

                        logging.info(f"AI Agent analyzing email: '{mail['subject']}' from {email}")

                        prompt = f"Subject: {mail['subject']}\nSender: {mail['sender']}\nDate: {mail['date']}\n\nBody:\n{mail['body']}"
                        gemini_response = await asyncio.to_thread(
                            gemini_client.models.generate_content,
                            model="gemini-2.5-flash",
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                system_instruction=SYSTEM_INSTRUCTION,
                                response_mime_type="application/json",
                                response_schema=InvoiceExtractionList,
                            ),
                        )

                        try:
                            extracted: InvoiceExtractionList = gemini_response.parsed
                            if extracted and extracted.invoices:
                                for inv in extracted.invoices:
                                    inv_dict = inv.model_dump()
                                    inv_dict["id"] = msg_id
                                    inv_dict["email_subject"] = mail["subject"]
                                    inv_dict["scanned_account"] = email
                                    new_invoices_total.append(inv_dict)
                        except Exception as parse_err:
                            logging.error(f"Error parsing invoice with Gemini: {parse_err}")
                                
                        # Write to Google Sheets for this account if sheet ID is specified
                        if self.sheet_id and new_invoices_total:
                            try:
                                self._write_to_google_sheet(new_invoices_total, token_path)
                            except Exception as sheet_err:
                                logging.error(f"Failed to write to Google Sheets for {email}: {sheet_err}")

                # Combine new and cached invoices
                all_invoices = new_invoices_total + cached_data
                all_invoices.sort(key=lambda x: x["date"], reverse=True)
                self._save_cached_invoices(all_invoices)
                
                scanned_list_str = ", ".join(connected_emails)
                return {
                    "status": "success",
                    "mode": "production",
                    "invoices_found": len(new_invoices_total),
                    "message": f"Successfully scanned accounts ({scanned_list_str}). Found {len(new_invoices_total)} new invoices.",
                    "data": all_invoices
                }
                
            except Exception as e:
                logging.error(f"Error running Gmail Invoice Agent in production: {e}", exc_info=True)
                return {
                    "status": "error",
                    "mode": "production",
                    "message": f"Production scan failed: {str(e)}"
                }

    def _fetch_invoice_emails(self, token_path: str) -> List[Dict[str, Any]]:
        """Fetches invoice emails using the credentials token specified."""
        from googleapiclient.discovery import build
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        
        SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/spreadsheets']
        
        if not os.path.exists(token_path):
            raise FileNotFoundError(f"Auth token file '{token_path}' not found.")
            
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Save the refreshed token
            with open(token_path, 'w') as token_file:
                token_file.write(creds.to_json())
                
        service = build('gmail', 'v1', credentials=creds)
        
        # Search query for last 30 days
        query = "subject:(invoice OR receipt OR bill OR חשבונית OR קבלה OR תשלום) newer_than:30d"
        logging.info(f"Querying Gmail API at token '{os.path.basename(token_path)}' with: {query}")
        
        results = service.users().messages().list(userId='me', q=query, maxResults=15).execute()
        messages = results.get('messages', [])
        
        email_records = []
        for msg in messages:
            msg_id = msg['id']
            full_msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
            
            headers = full_msg.get('payload', {}).get('headers', [])
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), "No Subject")
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), "Unknown Sender")
            date_str = next((h['value'] for h in headers if h['name'].lower() == 'date'), "")
            
            # Extract email body — prefer plain text, strip HTML tags as fallback
            import base64, re as _re

            def _decode_part(part):
                data = part.get('body', {}).get('data', '')
                if not data:
                    return ''
                return base64.urlsafe_b64decode(data.encode('utf-8')).decode('utf-8', errors='ignore')

            def _strip_html(html: str) -> str:
                text = _re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=_re.DOTALL | _re.IGNORECASE)
                text = _re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=_re.DOTALL | _re.IGNORECASE)
                text = _re.sub(r'<[^>]+>', ' ', text)
                text = _re.sub(r'&nbsp;', ' ', text)
                text = _re.sub(r'&[a-z]+;', '', text)
                text = _re.sub(r'[ \t]{2,}', ' ', text)
                text = _re.sub(r'\n{3,}', '\n\n', text)
                return text.strip()

            def _collect_parts(part, plain_parts, html_parts):
                mime = part.get('mimeType', '')
                if mime == 'text/plain':
                    text = _decode_part(part)
                    if text:
                        plain_parts.append(text)
                elif mime == 'text/html':
                    text = _decode_part(part)
                    if text:
                        html_parts.append(text)
                for subpart in part.get('parts', []):
                    _collect_parts(subpart, plain_parts, html_parts)

            payload = full_msg.get('payload', {})
            plain_parts, html_parts = [], []
            _collect_parts(payload, plain_parts, html_parts)

            if plain_parts:
                body = "\n".join(plain_parts)
            elif html_parts:
                body = _strip_html("\n".join(html_parts))
            elif payload.get('body', {}).get('data'):
                body = _decode_part(payload)
            else:
                body = ""

            body = body[:8000]
            
            email_records.append({
                "id": msg_id,
                "subject": subject,
                "sender": sender,
                "date": date_str,
                "body": body
            })
            
        return email_records

    def _write_to_google_sheet(self, invoices: List[Dict[str, Any]], token_path: Optional[str]):
        """Writes parsed invoice data to the Google Sheet using the active token credentials."""
        import gspread
        from google.oauth2.credentials import Credentials
        
        # If token path is not specified, try to find the first valid token to authorize gspread
        if not token_path or not os.path.exists(token_path):
            tokens = glob.glob(os.path.join(BACKEND_DIR, "token_*.json"))
            if tokens:
                token_path = tokens[0]
            else:
                legacy_token = os.path.join(BACKEND_DIR, "token.json")
                if os.path.exists(legacy_token):
                    token_path = legacy_token
                else:
                    logging.warning("Cannot write to Google Sheet: No active credentials tokens exist.")
                    return
            
        SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        gc = gspread.Client(auth=creds)

        # Accept either a full URL or a bare sheet ID
        import re
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', self.sheet_id)
        sheet_key = match.group(1) if match else self.sheet_id

        sh = gc.open_by_key(sheet_key)
        worksheet = sh.get_worksheet(0)
        
        existing_values = worksheet.get_all_values()
        
        if not existing_values:
            headers = ["תאריך", "שם שירות / חברה", "סכום", "מטבע", "קטגוריה", "מזהה חשבונית", "נושא המייל", "פירוט / תיאור", "מזהה מייל", "תיבת מייל נסרקת"]
            worksheet.append_row(headers)
            existing_ids = set()
        else:
            existing_ids = {row[8] for row in existing_values[1:] if len(row) > 8}
            
        rows_to_append = []
        for inv in invoices:
            msg_id = inv.get("id", "")
            if msg_id in existing_ids:
                continue
                
            row = [
                inv.get("date", ""),
                inv.get("service_name", ""),
                inv.get("amount", 0.0),
                inv.get("currency", ""),
                inv.get("category", ""),
                inv.get("invoice_id", ""),
                inv.get("email_subject", ""),
                inv.get("description", ""),
                msg_id,
                inv.get("scanned_account", "simulation")
            ]
            rows_to_append.append(row)
            
        if rows_to_append:
            logging.info(f"Writing {len(rows_to_append)} rows to Google Sheets...")
            worksheet.append_rows(rows_to_append)
            logging.info("Google Sheets writing completed.")
        else:
            logging.info("No new unique rows to write to Google Sheets.")
