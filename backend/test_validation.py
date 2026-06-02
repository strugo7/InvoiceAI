"""
Tests for the strict anti-hallucination validation gate (_validate_invoice).

Run: cd backend && .venv/bin/python3 test_validation.py
"""
from agent import _validate_invoice


def base(**overrides):
    """A fully-valid, PDF-backed invoice; override fields per test."""
    inv = {
        "is_invoice": True,
        "service_name": "Base44",
        "date": "2026-05-01",
        "amount": 104.0,
        "currency": "ILS",
        "subscription_period": "monthly",
        "confidence": 0.95,
        "source_quote": 'סה"כ לתשלום: 104 ₪',
        "source_has_pdf": True,
    }
    inv.update(overrides)
    return inv


def expect(name, inv, should_pass):
    ok, reason = _validate_invoice(inv)
    status = "PASS" if ok == should_pass else "FAIL"
    print(f"[{status}] {name}: valid={ok} reason='{reason}'")
    assert ok == should_pass, f"{name}: expected valid={should_pass}, got {ok} ({reason})"


def run():
    # Accept: a real PDF-backed receipt
    expect("pdf real receipt", base(), True)

    # Reject: Gemini said it is not an invoice (marketing / order confirmation)
    expect("not an invoice", base(is_invoice=False), False)

    # Reject: zero / negative / non-numeric amount
    expect("zero amount", base(amount=0), False)
    expect("negative amount", base(amount=-5), False)
    expect("non-numeric amount", base(amount="N/A"), False)

    # Reject: unknown currency
    expect("bad currency", base(currency="GBP"), False)

    # Reject: no verbatim source quote (amount was not literally present -> likely hallucinated)
    expect("missing source_quote", base(source_quote=""), False)

    # Reject: missing service_name / date
    expect("missing service", base(service_name=""), False)
    expect("missing date", base(date=""), False)

    # PDF-backed accepts at 0.7; inline-only requires 0.85
    expect("pdf at 0.70", base(confidence=0.70, source_has_pdf=True), True)
    expect("inline at 0.70 rejected", base(confidence=0.70, source_has_pdf=False), False)
    expect("inline at 0.85 accepted", base(confidence=0.85, source_has_pdf=False), True)

    print("\n✅ All validation gate tests passed!")


if __name__ == "__main__":
    run()
