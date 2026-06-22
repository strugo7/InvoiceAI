import os
import re
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import pydantic
from dotenv import load_dotenv

import token_store
from retry import execute_with_retry as _execute_with_retry, call_with_retry as _call_with_retry

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
    subscription_period: str = pydantic.Field(
        "monthly",
        description="Billing frequency: 'monthly' or 'annual'. "
                    "Set to 'annual' when the invoice contains: annual, yearly, שנתי, "
                    "per year, 1-year, 12-month, חיוב שנתי, מנוי שנתי. "
                    "Default to 'monthly' when uncertain."
    )
    is_invoice: bool = pydantic.Field(
        False,
        description="TRUE only if this email/PDF is a REAL invoice, receipt, or bill documenting "
                    "an ACTUAL charge that was made or is due. Set FALSE for marketing emails, "
                    "promotions, order confirmations without a charge, shipping notifications, "
                    "newsletters, price quotes, account statements with no amount, or anything where "
                    "you are guessing the amount. When in doubt, set FALSE."
    )
    confidence: float = pydantic.Field(
        0.0,
        description="Your confidence from 0.0 to 1.0 that the extracted amount and service_name are "
                    "CORRECT and taken verbatim from the source text. Use a LOW value (<0.7) if you "
                    "had to infer, estimate, or guess any field. Never inflate this value."
    )
    source_quote: str = pydantic.Field(
        "",
        description="The EXACT substring from the email/PDF text where you found the total amount "
                    "(e.g. 'Total: $19.00' or 'סה\"כ לתשלום: 104 ₪'). Must be copied verbatim from the "
                    "input. Leave EMPTY if you cannot find the amount as literal text — never invent it."
    )

class InvoiceExtractionList(pydantic.BaseModel):
    invoices: List[InvoiceDetail]

# Local Cache File for Simulation / Backup
CACHE_FILE = os.path.join(os.path.dirname(__file__), "invoices.json")
BACKEND_DIR = os.path.dirname(__file__)


def _env_int(name: str, default: int) -> int:
    """Reads a positive int from the environment, falling back to `default`."""
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


# Guardrails against runaway API usage (overridable via env):
#   SCAN_LOOKBACK_DAYS   — how far back Gmail is searched (bounds the result set).
#   MAX_EMAILS_PER_SCAN  — hard cap on messages processed per scan, which also
#                          caps the number of paid Gemini calls a scan can make.
SCAN_LOOKBACK_DAYS = _env_int("SCAN_LOOKBACK_DAYS", 90)
MAX_EMAILS_PER_SCAN = _env_int("MAX_EMAILS_PER_SCAN", 300)

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
        {"name": "Figma", "category": "SaaS/Subscription", "amount_range": (15.0, 30.0), "currency": "USD", "desc": "Professional Design Editor Team"},
        {"name": "PlayStation Network", "category": "Entertainment", "amount_range": (269.0, 269.0), "currency": "ILS", "desc": "PlayStation Plus Premium - מנוי שנתי", "subscription_period": "annual"},
        {"name": "Fucsee", "category": "SaaS/Subscription", "amount_range": (99.0, 99.0), "currency": "USD", "desc": "Annual Subscription", "subscription_period": "annual"},
    ]

    # Annual services are billed once a year — add them once to the mock data (not per-month)
    annual_services = [svc for svc in services if svc.get("subscription_period") == "annual"]
    monthly_services = [svc for svc in services if svc.get("subscription_period") != "annual"]

    mock_data = []
    # Generate for the past 3 months
    for month_offset in range(3, -1, -1):
        target_month = today - timedelta(days=30 * month_offset)

        # Pick 5-8 random bills per month
        import random
        random.seed(42 + month_offset) # Determistic but varied

        selected_services = random.sample(monthly_services, k=random.randint(6, min(9, len(monthly_services))))
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
                "email_subject": f"Your monthly invoice for {svc['name']}",
                "subscription_period": svc.get("subscription_period", "monthly"),
            })

    # Add annual subscriptions once (billed ~12 months ago from today)
    for idx, svc in enumerate(annual_services):
        annual_date = (today - timedelta(days=random.randint(30, 60))).strftime("%Y-%m-%d")
        mock_data.append({
            "id": f"msg-mock-annual-{idx}",
            "service_name": svc["name"],
            "date": annual_date,
            "amount": svc["amount_range"][0],
            "currency": svc["currency"],
            "category": svc["category"],
            "invoice_id": f"ANN-{today.year}-{idx:04d}",
            "description": svc["desc"],
            "email_subject": f"Annual subscription renewal - {svc['name']}",
            "subscription_period": "annual",
        })
            
    # Sort by date descending
    mock_data.sort(key=lambda x: x["date"], reverse=True)
    return mock_data


def get_connected_accounts() -> List[str]:
    """Returns the connected Gmail addresses from the encrypted Supabase token store."""
    return token_store.list_accounts()


def _build_gmail_service(email: str):
    """Builds an authenticated Gmail API service for a connected account.

    Credentials are loaded (and refreshed) from the encrypted token store; no
    local token files are involved.
    """
    from googleapiclient.discovery import build

    creds = token_store.get_credentials(email)
    if not creds:
        raise FileNotFoundError(f"No stored credentials for account '{email}'.")

    return build('gmail', 'v1', credentials=creds)


def _find_pdf_part(part: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Recursively walks a Gmail message payload and returns the first PDF attachment part."""
    mime = part.get('mimeType', '')
    is_pdf = mime == 'application/pdf' or (
        mime == 'application/octet-stream' and part.get('filename', '').lower().endswith('.pdf')
    )
    if is_pdf:
        body = part.get('body', {})
        if body.get('data') or body.get('attachmentId'):
            return part
    for subpart in part.get('parts', []):
        found = _find_pdf_part(subpart)
        if found:
            return found
    return None


def _collect_html_body(part: Dict[str, Any], html_parts: List[str], text_parts: List[str]) -> None:
    """Recursively gathers decoded text/html (and text/plain) parts of a message."""
    import base64
    mime = part.get('mimeType', '')
    data = part.get('body', {}).get('data')
    if data and mime in ('text/html', 'text/plain'):
        try:
            decoded = base64.urlsafe_b64decode(data.encode('utf-8')).decode('utf-8', errors='ignore')
            (html_parts if mime == 'text/html' else text_parts).append(decoded)
        except Exception:
            pass
    for sub in part.get('parts', []):
        _collect_html_body(sub, html_parts, text_parts)


def _get_email_html(payload: Dict[str, Any]) -> str:
    """Returns the email's renderable HTML body (scripts stripped), or a <pre> of plain text."""
    import re as _re
    html_parts, text_parts = [], []
    _collect_html_body(payload, html_parts, text_parts)
    if html_parts:
        html = "\n".join(html_parts)
        # Defense-in-depth: drop scripts before we render the email in a sandboxed iframe
        html = _re.sub(r'<script[^>]*>.*?</script>', '', html, flags=_re.DOTALL | _re.IGNORECASE)
        return html
    if text_parts:
        body = "\n".join(text_parts)
        return f'<pre style="white-space:pre-wrap;font-family:sans-serif;padding:1rem">{body}</pre>'
    return ""


# Anchor text / href patterns that identify a hosted invoice or receipt link.
_INV_TEXT_STRONG = re.compile(
    r'(invoice|receipt|view\s+it\s+in\s+your\s+browser|חשבונית|קבלה|לצפייה|צפייה\s+בחשבונ)', re.IGNORECASE)
_INV_TEXT_WEAK = re.compile(r'(view|download|generate|הצג|הורד)', re.IGNORECASE)
_INV_HREF = re.compile(
    r'(invoice|/receipts?/|onfastspring\.com|stripe\.com/receipts|invoice\.stripe\.com)', re.IGNORECASE)
_INV_HREF_REJECT = re.compile(
    r'(unsubscribe|/login|/signin|/sign-in|manage|preferences|privacy|/terms|facebook\.com|'
    r'twitter\.com|instagram\.com|linkedin\.com|\.(png|jpe?g|gif|svg|css)(\?|$))', re.IGNORECASE)
_ANCHOR_RE = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r'<[^>]+>')


def _find_invoice_link(payload: Dict[str, Any]) -> Optional[str]:
    """Extracts the most likely hosted invoice/receipt URL from an email's HTML body.

    Scores each anchor by its visible text and href; returns the best match or None.
    """
    import re as _re
    html_parts, _text = [], []
    _collect_html_body(payload, html_parts, _text)
    html = "\n".join(html_parts)
    if not html:
        return None

    best_url, best_score = None, 0
    for href, raw_text in _ANCHOR_RE.findall(html):
        if _INV_HREF_REJECT.search(href):
            continue
        text = _re.sub(r'\s+', ' ', _TAG_RE.sub('', raw_text)).strip()
        score = 0
        if _INV_TEXT_STRONG.search(text):
            score += 2
        elif _INV_TEXT_WEAK.search(text):
            score += 1
        if _INV_HREF.search(href):
            score += 2
        # Require a meaningful signal (strong text, or weak text backed by an invoice-like href)
        if score >= 2 and score > best_score:
            best_url, best_score = href, score
    return best_url


def get_invoice_document(email_id: str, account: str) -> Dict[str, Any]:
    """Classifies how an invoice can be viewed, fetching the Gmail message once.

    Returns one of:
      {"type": "pdf"}                       — a PDF attachment is available (stream via /pdf)
      {"type": "page", "html": ..., "link": url|None}  — render the email body; optional hosted link
      {"type": "none"}                      — nothing renderable (account unknown, fetch error, empty)
    """
    if account not in get_connected_accounts():
        logging.warning(f"Document request for unknown account '{account}'")
        return {"type": "none"}
    try:
        service = _build_gmail_service(account)
        full_msg = service.users().messages().get(userId='me', id=email_id, format='full').execute()
        payload = full_msg.get('payload', {})
        if _find_pdf_part(payload):
            return {"type": "pdf"}
        html = _get_email_html(payload)
        link = _find_invoice_link(payload)
        if html or link:
            return {"type": "page", "html": html, "link": link}
        return {"type": "none"}
    except Exception as e:
        logging.error(f"Failed to classify invoice document (id={email_id}, account={account}): {e}")
        return {"type": "none"}


def get_invoice_pdf(email_id: str, account: str):
    """Fetches the PDF attachment of an invoice email from Gmail on demand.

    Returns (pdf_bytes, filename) or None if no PDF is available / on error.
    The account is validated against connected accounts to avoid path traversal.
    """
    import base64

    if account not in get_connected_accounts():
        logging.warning(f"PDF request for unknown account '{account}'")
        return None

    try:
        service = _build_gmail_service(account)
        full_msg = service.users().messages().get(userId='me', id=email_id, format='full').execute()
        payload = full_msg.get('payload', {})
        pdf_part = _find_pdf_part(payload)
        if not pdf_part:
            return None

        body = pdf_part.get('body', {})
        if body.get('data'):
            pdf_bytes = base64.urlsafe_b64decode(body['data'].encode('utf-8'))
        else:
            att = service.users().messages().attachments().get(
                userId='me', messageId=email_id, id=body['attachmentId']
            ).execute()
            pdf_bytes = base64.urlsafe_b64decode(att['data'].encode('utf-8'))

        filename = pdf_part.get('filename') or 'invoice.pdf'
        return pdf_bytes, filename
    except Exception as e:
        logging.error(f"Failed to fetch invoice PDF (id={email_id}, account={account}): {e}")
        return None


def disconnect_account(email: str) -> bool:
    """Removes the stored (encrypted) credentials for the specified account."""
    return token_store.delete_account(email)


VALID_CURRENCIES = {"ILS", "USD", "EUR"}
# Real receipts arrive as PDF attachments from the service. A PDF-backed invoice is
# trusted at the normal threshold; an inline-only email (the main source of marketing
# noise and hallucinations) must clear a higher bar before we accept it.
MIN_CONFIDENCE_PDF = 0.7
MIN_CONFIDENCE_INLINE = 0.85


def _validate_invoice(inv: Dict[str, Any]) -> tuple:
    """
    Strict anti-hallucination gate. Returns (is_valid: bool, reason: str).
    An invoice is only accepted if Gemini flagged it as a real invoice, with a
    positive amount, a known currency, a verbatim source quote proving the amount
    was actually present, and confidence above a threshold that is RELAXED when the
    email carried a PDF receipt and STRICTER when it did not.
    """
    if not inv.get("is_invoice", False):
        return False, "not flagged as a real invoice"
    try:
        amount = float(inv.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return False, f"non-numeric amount: {inv.get('amount')!r}"
    if amount <= 0:
        return False, f"non-positive amount: {amount}"
    currency = str(inv.get("currency", "")).upper()
    if currency not in VALID_CURRENCIES:
        return False, f"invalid currency: {currency!r}"
    if not str(inv.get("source_quote", "")).strip():
        return False, "missing source_quote (amount not found verbatim)"
    if not str(inv.get("service_name", "")).strip():
        return False, "missing service_name"
    if not str(inv.get("date", "")).strip():
        return False, "missing date"
    try:
        confidence = float(inv.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    has_pdf = bool(inv.get("source_has_pdf", False))
    threshold = MIN_CONFIDENCE_PDF if has_pdf else MIN_CONFIDENCE_INLINE
    if confidence < threshold:
        kind = "pdf-backed" if has_pdf else "inline-only"
        return False, f"low confidence for {kind}: {confidence} < {threshold}"
    return True, "ok"


def load_all_invoices() -> List[Dict[str, Any]]:
    """
    Single source of truth for reading invoices for display.
    Reads from Supabase when configured, falling back to the local JSON cache.
    Used by both the agent and the /api/invoices endpoint.
    """
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if url and key and key != "YOUR_SERVICE_ROLE_KEY_HERE":
        try:
            from supabase import create_client
            sb = create_client(url, key)
            resp = sb.table("invoices").select("*").order("date", desc=True).execute()
            rows = resp.data or []
            for r in rows:
                # Normalise: expose 'email_id' as 'id' so the frontend schema is unchanged
                r["id"] = r.get("email_id", r.get("id", ""))
            logging.info(f"Loaded {len(rows)} invoices from Supabase.")
            return rows
        except Exception as e:
            logging.warning(f"Supabase load failed, falling back to local cache: {e}")

    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading cached invoices: {e}")
    return []


def _extract_pdf_text(pdf_bytes: bytes, max_chars: int = 5000) -> str:
    """Extracts plain text from a PDF binary using pdfplumber. Returns empty string on failure."""
    try:
        import pdfplumber
        import io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            texts = [p.extract_text() or "" for p in pdf.pages]
        return "\n".join(texts)[:max_chars]
    except Exception as e:
        logging.warning(f"PDF text extraction failed: {e}")
        return ""


class GmailInvoiceAgent:
    """Agent that processes Gmail accounts and stores invoice details in Google Sheets."""
    
    def __init__(self, use_mock: bool = True, sheet_id: Optional[str] = None):
        self.use_mock = use_mock
        self.sheet_id = sheet_id
        
    def _get_supabase(self):
        """Returns an authenticated Supabase client, or None if not configured."""
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not url or not key or key == "YOUR_SERVICE_ROLE_KEY_HERE":
            return None
        try:
            from supabase import create_client
            return create_client(url, key)
        except Exception as e:
            logging.warning(f"Could not create Supabase client: {e}")
            return None

    def _load_cached_invoices(self) -> List[Dict[str, Any]]:
        """Loads invoices from Supabase, falling back to the local JSON cache."""
        return load_all_invoices()

    def _save_cached_invoices(self, invoices: List[Dict[str, Any]]):
        """Upserts invoices into Supabase and writes the local JSON backup."""
        sb = self._get_supabase()
        if sb and invoices:
            try:
                rows = []
                for inv in invoices:
                    row = {
                        "email_id":            inv.get("id", ""),
                        "service_name":        inv.get("service_name", ""),
                        "date":                inv.get("date", ""),
                        "amount":              inv.get("amount", 0.0),
                        "currency":            inv.get("currency", ""),
                        "category":            inv.get("category", ""),
                        "invoice_id":          inv.get("invoice_id"),
                        "description":         inv.get("description"),
                        "email_subject":       inv.get("email_subject"),
                        "scanned_account":     inv.get("scanned_account", "simulation"),
                        "subscription_period": inv.get("subscription_period", "monthly"),
                    }
                    rows.append(row)
                sb.table("invoices").upsert(rows, on_conflict="email_id").execute()
                logging.info(f"Upserted {len(rows)} invoices to Supabase.")
            except Exception as e:
                logging.error(f"Supabase upsert failed: {e}")

        # Always keep local JSON as backup
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(invoices, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Error saving local invoice cache: {e}")

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
                    self._write_to_google_sheet(mock_invoices)
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
            # Email-level dedup: strip the per-row "__N" suffix so an already-processed
            # email (even one that yielded multiple invoices) is recognised and skipped.
            existing_ids = {str(inv.get("id", "")).split("__")[0] for inv in cached_data}
            
            try:
                from google import genai
                from google.genai import types

                SYSTEM_INSTRUCTION = (
                    "You are an expert financial auditor. Analyze the provided email text "
                    "(receipt, invoice, or monthly bill) and extract key financial data. "
                    "CRITICAL ANTI-HALLUCINATION RULES — accuracy matters more than completeness:\n"
                    "- NEVER invent, estimate, or guess any value. Every field must come VERBATIM from the input text. "
                    "If a value is not literally present, do not fabricate it.\n"
                    "- is_invoice: set TRUE only for a REAL invoice/receipt/bill with an actual charge. Set FALSE for "
                    "marketing, promotions, order confirmations without a charge, shipping notices, newsletters, price "
                    "quotes, or statements with no concrete total. When in doubt, FALSE and return an empty invoices list.\n"
                    "- source_quote: copy the EXACT substring containing the total (e.g. 'Total: $19.00', 'סה\"כ לתשלום: 104 ₪'). "
                    "If you cannot find the amount as literal text, leave source_quote EMPTY and set is_invoice FALSE.\n"
                    "- confidence: 0.0-1.0, how sure you are the amount and service_name are exactly correct. Be honest; "
                    "use <0.7 whenever you had to infer anything.\n"
                    "- amount: the TOTAL amount as a positive float, taken from source_quote. Strip currency symbols "
                    "(₪, $, €). Do not return 0.\n"
                    "- currency: ILS for ₪/שח/ש\"ח, USD for $, EUR for €. Use 3-letter ISO codes only.\n"
                    "- date: YYYY-MM-DD format strictly.\n"
                    "- If multiple genuine invoices appear in the same email, extract all of them.\n"
                    "- service_name: the company or service name, not the email domain.\n"
                    "- subscription_period: set to 'annual' if the invoice indicates yearly billing "
                    "(keywords: annual, yearly, שנתי, per year, 1-year plan, 12-month subscription, "
                    "חיוב שנתי, מנוי שנתי). Otherwise set to 'monthly'. When unsure, default to 'monthly'. "
                    "For annual subscriptions, 'amount' is the FULL annual charge — do NOT divide it."
                )

                gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

                # Run the scan for each connected mailbox
                for email in connected_emails:
                    logging.info(f"Scanning mailbox: {email}")

                    # Fetch emails using this account's stored credentials
                    try:
                        emails = self._fetch_invoice_emails(email)
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

                        def _call_gemini():
                            return gemini_client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=prompt,
                                config=types.GenerateContentConfig(
                                    system_instruction=SYSTEM_INSTRUCTION,
                                    response_mime_type="application/json",
                                    response_schema=InvoiceExtractionList,
                                ),
                            )

                        # Off-loop thread + bounded backoff so a Gemini 429 doesn't
                        # fail the whole scan or trigger an uncontrolled caller retry.
                        gemini_response = await asyncio.to_thread(
                            _call_with_retry, _call_gemini, what="Gemini"
                        )

                        try:
                            extracted: InvoiceExtractionList = gemini_response.parsed
                            if extracted and extracted.invoices:
                                accepted_in_email = 0
                                for idx, inv in enumerate(extracted.invoices):
                                    inv_dict = inv.model_dump()
                                    # Verification signal: did this email carry a real PDF receipt?
                                    inv_dict["source_has_pdf"] = mail.get("had_pdf", False)

                                    # Strict validation gate — drop hallucinated / non-invoice data
                                    is_valid, reason = _validate_invoice(inv_dict)
                                    if not is_valid:
                                        logging.info(
                                            f"REJECTED extraction from '{mail['subject']}': {reason} "
                                            f"(service={inv_dict.get('service_name')!r}, amount={inv_dict.get('amount')!r})"
                                        )
                                        continue

                                    # Unique row id so multi-invoice emails are NOT collapsed in Supabase
                                    row_id = msg_id if accepted_in_email == 0 else f"{msg_id}__{accepted_in_email}"
                                    inv_dict["id"] = row_id
                                    inv_dict["email_subject"] = mail["subject"]
                                    inv_dict["scanned_account"] = email
                                    # Persist whether a PDF receipt was attached so the UI knows
                                    # whether to surface the "view original invoice" action.
                                    inv_dict["has_pdf"] = mail.get("had_pdf", False)

                                    # Drop validation-only fields before persisting (keep storage clean)
                                    for k in ("is_invoice", "confidence", "source_quote", "source_has_pdf"):
                                        inv_dict.pop(k, None)

                                    new_invoices_total.append(inv_dict)
                                    accepted_in_email += 1
                        except Exception as parse_err:
                            logging.error(f"Error parsing invoice with Gemini: {parse_err}")
                                
                        # Write to Google Sheets for this account if sheet ID is specified
                        if self.sheet_id and new_invoices_total:
                            try:
                                self._write_to_google_sheet(new_invoices_total, account=email)
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

    def _fetch_invoice_emails(self, account: str) -> List[Dict[str, Any]]:
        """Fetches invoice emails for a connected account using its stored credentials."""
        from googleapiclient.discovery import build

        creds = token_store.get_credentials(account)
        if not creds:
            raise FileNotFoundError(f"No stored credentials for account '{account}'.")

        service = build('gmail', 'v1', credentials=creds)
        
        # Two queries: (1) subject keyword search with expanded vocabulary, (2) PDF attachments
        # Combined and deduplicated by message ID to avoid double-processing.
        # Bounded by SCAN_LOOKBACK_DAYS so we never sweep the entire mailbox.
        query_keywords = (
            f"in:anywhere newer_than:{SCAN_LOOKBACK_DAYS}d "
            "subject:(invoice OR receipt OR bill OR payment OR order OR subscription OR "
            "חשבונית OR קבלה OR תשלום OR הזמנה OR מנוי OR חשבון OR חשבוניות)"
        )
        query_pdf = (
            f"in:anywhere newer_than:{SCAN_LOOKBACK_DAYS}d "
            "has:attachment filename:pdf"
        )

        seen_ids: set = set()
        messages = []
        # Hard cap: stop paginating once we have MAX_EMAILS_PER_SCAN unique messages,
        # so a single scan can't fan out into unbounded list/get/Gemini calls.
        capped = False
        for query in [query_keywords, query_pdf]:
            if capped:
                break
            logging.info(f"Querying Gmail API for '{account}': {query[:60]}...")
            page_token = None
            while True:
                remaining = MAX_EMAILS_PER_SCAN - len(messages)
                if remaining <= 0:
                    capped = True
                    break
                kwargs = {"userId": "me", "q": query, "maxResults": min(500, remaining)}
                if page_token:
                    kwargs["pageToken"] = page_token
                results = _execute_with_retry(service.users().messages().list(**kwargs))
                for m in results.get("messages", []):
                    if m["id"] not in seen_ids:
                        seen_ids.add(m["id"])
                        messages.append(m)
                page_token = results.get("nextPageToken")
                logging.info(f"  batch fetched (unique total so far: {len(messages)})")
                if not page_token:
                    break
        if capped:
            logging.warning(
                f"Reached MAX_EMAILS_PER_SCAN={MAX_EMAILS_PER_SCAN} for '{account}'; "
                "remaining messages will be picked up on the next scan."
            )

        logging.info(f"Total messages to process for '{account}': {len(messages)}")

        email_records = []
        for msg in messages:
            msg_id = msg['id']
            full_msg = _execute_with_retry(
                service.users().messages().get(userId='me', id=msg_id, format='full')
            )

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

            def _collect_parts(part, plain_parts, html_parts, pdf_parts):
                mime = part.get('mimeType', '')
                if mime == 'text/plain':
                    text = _decode_part(part)
                    if text:
                        plain_parts.append(text)
                elif mime == 'text/html':
                    text = _decode_part(part)
                    if text:
                        html_parts.append(text)
                elif mime == 'application/pdf' or (
                    mime == 'application/octet-stream' and
                    part.get('filename', '').lower().endswith('.pdf')
                ):
                    data = part.get('body', {}).get('data', '') or None
                    att_id = part.get('body', {}).get('attachmentId')
                    if data or att_id:
                        pdf_parts.append({'data': data, 'attachmentId': att_id})
                for subpart in part.get('parts', []):
                    _collect_parts(subpart, plain_parts, html_parts, pdf_parts)

            payload = full_msg.get('payload', {})
            plain_parts, html_parts, pdf_parts = [], [], []
            _collect_parts(payload, plain_parts, html_parts, pdf_parts)

            if plain_parts:
                body = "\n".join(plain_parts)
            elif html_parts:
                body = _strip_html("\n".join(html_parts))
            elif payload.get('body', {}).get('data'):
                body = _decode_part(payload)
            else:
                body = ""

            # Extract text from PDF attachments and append to body
            pdf_texts = []
            for pdf_info in pdf_parts:
                if pdf_info['data']:
                    pdf_bytes = base64.urlsafe_b64decode(pdf_info['data'].encode('utf-8'))
                elif pdf_info['attachmentId']:
                    try:
                        att = _execute_with_retry(
                            service.users().messages().attachments().get(
                                userId='me', messageId=msg_id, id=pdf_info['attachmentId']
                            )
                        )
                        pdf_bytes = base64.urlsafe_b64decode(att['data'].encode('utf-8'))
                    except Exception as att_err:
                        logging.warning(f"Could not fetch PDF attachment {pdf_info['attachmentId']}: {att_err}")
                        continue
                else:
                    continue
                extracted = _extract_pdf_text(pdf_bytes)
                if extracted:
                    pdf_texts.append(f"\n[PDF Attachment]:\n{extracted}")

            if pdf_texts:
                body = body + "\n".join(pdf_texts)

            body = body[:8000]
            
            email_records.append({
                "id": msg_id,
                "subject": subject,
                "sender": sender,
                "date": date_str,
                "body": body,
                # Verification signal: real receipts arrive as PDF attachments from the service.
                # True only when a PDF was attached AND its text was successfully extracted.
                "had_pdf": bool(pdf_texts),
            })
            
        return email_records

    def _write_to_google_sheet(self, invoices: List[Dict[str, Any]], account: Optional[str] = None):
        """Writes parsed invoice data to the Google Sheet using stored OAuth credentials.

        Authorizes gspread with the given account's credentials, or the first
        connected account when none is specified (e.g. mock-mode writes).
        """
        import gspread

        if not account:
            accounts = get_connected_accounts()
            if not accounts:
                logging.warning("Cannot write to Google Sheet: no connected accounts.")
                return
            account = accounts[0]

        creds = token_store.get_credentials(account)
        if not creds:
            logging.warning(f"Cannot write to Google Sheet: no credentials for '{account}'.")
            return
        gc = gspread.Client(auth=creds)

        # Accept either a full URL or a bare sheet ID
        import re
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', self.sheet_id)
        sheet_key = match.group(1) if match else self.sheet_id

        sh = gc.open_by_key(sheet_key)
        worksheet = sh.get_worksheet(0)
        
        existing_values = worksheet.get_all_values()
        
        if not existing_values:
            headers = ["תאריך", "שם שירות / חברה", "סכום", "מטבע", "קטגוריה", "מזהה חשבונית", "נושא המייל", "פירוט / תיאור", "מזהה מייל", "תיבת מייל נסרקת", "תקופת מנוי"]
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
                inv.get("scanned_account", "simulation"),
                inv.get("subscription_period", "monthly"),
            ]
            rows_to_append.append(row)
            
        if rows_to_append:
            logging.info(f"Writing {len(rows_to_append)} rows to Google Sheets...")
            worksheet.append_rows(rows_to_append)
            logging.info("Google Sheets writing completed.")
        else:
            logging.info("No new unique rows to write to Google Sheets.")
