# backend/report_generator.py
import os
import re
from datetime import datetime
from typing import List, Dict, Any

from fpdf import FPDF
from bidi.algorithm import get_display

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf")
FONT_PATH_BOLD = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans-Bold.ttf")
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


def load_invoices_for_month(year: int, month: int, user_email: str) -> List[Dict[str, Any]]:
    """Return a user's invoices whose date starts with YYYY-MM (read from Supabase)."""
    from agent import load_all_invoices
    prefix = f"{year:04d}-{month:02d}"
    data = load_all_invoices(user_email)
    return [inv for inv in data if str(inv.get("date", "")).startswith(prefix)]


def generate_monthly_pdf(year: int, month: int, user_email: str) -> str:
    """
    Generate a PDF report for the given month and user.
    Returns the absolute path to the saved PDF file.
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)
    invoices = load_invoices_for_month(year, month, user_email)

    month_name = datetime(year, month, 1).strftime("%B %Y")
    # Per-user filename so concurrent reports for different users never collide on disk
    safe_user = re.sub(r"[^a-zA-Z0-9._-]", "_", user_email or "user")
    filename = f"report_{safe_user}_{year:04d}_{month:02d}.pdf"
    filepath = os.path.join(REPORTS_DIR, filename)

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_font("DejaVu", style="", fname=FONT_PATH)
    pdf.add_font("DejaVu", style="B", fname=FONT_PATH_BOLD)
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
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
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
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
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
        service = _rtl(str(inv.get("service_name", ""))[:28])
        cat = _rtl(CATEGORY_LABELS.get(inv.get("category", "Other"), inv.get("category", ""))[:22])
        inv_id = _rtl(str(inv.get("invoice_id") or "")[:18])
        desc = _rtl(str(inv.get("description") or "")[:32])
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
