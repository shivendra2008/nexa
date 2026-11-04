"""PayPal REST (Sandbox) client.

Live sandbox mode: set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET (from developer.paypal.com → Apps & Credentials).
Demo mode (no credentials): orders/captures are simulated locally with the same response shape so the
full checkout → verification → dashboard-update flow can be exercised offline.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

import requests

BASE = os.environ.get("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com")
NO_DECIMAL = {"JPY", "HUF", "TWD"}
_token = {"value": None, "exp": 0}
# Demo-mode orders are signed and self-describing, so any server instance can approve and capture them
# (serverless hosts don't share memory between requests).
_SIM_KEY = os.environ.get("NEXA_SECRET", "nexa-demo-mode").encode()


def client_id():
    return os.environ.get("PAYPAL_CLIENT_ID", "")


def live():
    return bool(os.environ.get("PAYPAL_CLIENT_ID") and os.environ.get("PAYPAL_CLIENT_SECRET"))


def mode():
    return "sandbox" if live() else "demo"


def _fmt(amount, currency):
    return f"{amount:.0f}" if currency in NO_DECIMAL else f"{amount:.2f}"


def _auth():
    if _token["value"] and _token["exp"] > time.time() + 60:
        return _token["value"]
    r = requests.post(f"{BASE}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                      auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]), timeout=20)
    r.raise_for_status()
    j = r.json()
    _token.update(value=j["access_token"], exp=time.time() + j.get("expires_in", 3000))
    return _token["value"]


def _h():
    return {"Authorization": f"Bearer {_auth()}", "Content-Type": "application/json",
            "PayPal-Request-Id": secrets.token_hex(12)}


def create_order(invoice):
    amount = _fmt(invoice["total"] - (invoice.get("amount_paid") or 0), invoice["currency"])
    if not live():
        payload = base64.urlsafe_b64encode(json.dumps(
            {"n": invoice["number"], "a": amount, "c": invoice["currency"], "t": secrets.token_hex(6)}).encode()).decode().rstrip("=")
        sig = hmac.new(_SIM_KEY, payload.encode(), hashlib.sha256).hexdigest()[:20]
        return {"id": f"SIM-{payload}.{sig}", "status": "CREATED"}
    body = {"intent": "CAPTURE", "purchase_units": [{
        "reference_id": invoice["number"], "invoice_id": f"{invoice['number']}-{secrets.token_hex(3)}",
        "description": (invoice.get("description") or "Invoice")[:127],
        "amount": {"currency_code": invoice["currency"], "value": amount}}]}
    r = requests.post(f"{BASE}/v2/checkout/orders", json=body, headers=_h(), timeout=20)
    r.raise_for_status()
    return r.json()


def parse_simulated(order_id):
    """Return the signed demo order's contents, or None if it is malformed or tampered with."""
    try:
        payload, sig = order_id[len("SIM-"):].rsplit(".", 1)
    except ValueError:
        return None
    good = hmac.new(_SIM_KEY, payload.encode(), hashlib.sha256).hexdigest()[:20]
    if not order_id.startswith("SIM-") or not hmac.compare_digest(sig, good):
        return None
    d = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    return {"id": order_id, "status": "APPROVED", "invoice": d["n"], "amount": d["a"], "currency": d["c"]}


def approve_simulated(order_id):
    return parse_simulated(order_id)


def capture_order(order_id):
    """Capture and return a normalised, verified result."""
    if not live():
        o = parse_simulated(order_id)
        if not o:
            return {"ok": False, "error": "Order not approved"}
        return {"ok": True, "status": "COMPLETED", "order_id": order_id,
                "capture_id": "CAP-" + secrets.token_hex(8).upper(), "amount": float(o["amount"]),
                "currency": o["currency"], "reference": o["invoice"], "payer": "sandbox-buyer@personal.example.com"}
    r = requests.post(f"{BASE}/v2/checkout/orders/{order_id}/capture", headers=_h(), timeout=30)
    j = r.json()
    if r.status_code >= 400:
        return {"ok": False, "error": j.get("message") or j.get("name") or "Capture failed", "raw": j}
    pu = j["purchase_units"][0]
    cap = pu["payments"]["captures"][0]
    return {"ok": j["status"] == "COMPLETED" and cap["status"] == "COMPLETED", "status": j["status"],
            "order_id": j["id"], "capture_id": cap["id"], "amount": float(cap["amount"]["value"]),
            "currency": cap["amount"]["currency_code"], "reference": pu.get("reference_id"),
            "payer": (j.get("payer") or {}).get("email_address")}


def create_and_send_invoice(inv, business_name):
    """PayPal Invoicing v2: create a draft invoice then send it. Simulated in demo mode."""
    if not live():
        return {"id": "INV2-" + "-".join(secrets.token_hex(2).upper() for _ in range(4)), "status": "SENT", "simulated": True}
    body = {
        "detail": {"invoice_number": inv["number"], "currency_code": inv["currency"], "invoice_date": inv["issue_date"],
                   "payment_term": {"due_date": inv["due_date"]}, "note": f"Thank you for your business — {business_name}"},
        "primary_recipients": [{"billing_info": {"email_address": inv["customer_email"]}}] if inv.get("customer_email") else [],
        "items": [{"name": inv["description"][:200], "quantity": "1",
                   "unit_amount": {"currency_code": inv["currency"], "value": _fmt(inv["subtotal"], inv["currency"])},
                   **({"tax": {"name": "Tax", "percent": str(inv["tax_rate"])}} if inv.get("tax_rate") else {}),
                   **({"discount": {"percent": str(inv["discount"])}} if inv.get("discount") else {})}],
    }
    r = requests.post(f"{BASE}/v2/invoicing/invoices", json=body, headers=_h(), timeout=30)
    r.raise_for_status()
    href = r.json().get("href", "")
    pid = href.rstrip("/").split("/")[-1]
    s = requests.post(f"{BASE}/v2/invoicing/invoices/{pid}/send", json={"send_to_invoicer": True}, headers=_h(), timeout=30)
    return {"id": pid, "status": "SENT" if s.status_code < 300 else "DRAFT", "simulated": False}
