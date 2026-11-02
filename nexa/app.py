"""NEXA — Flask application: pages + JSON API + proactive agent thread."""
import os
import threading
import time
from datetime import date, datetime

from flask import Flask, Response, abort, jsonify, render_template, request

from . import assistant, db, engine, paypal, reports

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(__name__, template_folder=os.path.join(ROOT, "templates"), static_folder=os.path.join(ROOT, "static"))
AGENT_INTERVAL = int(os.environ.get("NEXA_AGENT_INTERVAL", "45"))


def ok(data=None, **kw):
    return jsonify({"ok": True, **({"data": data} if data is not None else {}), **kw})


def err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


# --------------------------------------------------------------------------- pages

@app.get("/")
def landing():
    return render_template("index.html")


@app.get("/app")
def dashboard():
    return render_template("app.html")


@app.get("/pay/<number>")
def pay_page(number):
    inv = next((i for i in engine.invoices() if i["number"] == number), None)
    if not inv:
        abort(404)
    return render_template("pay.html", number=number, client_id=paypal.client_id(), mode=paypal.mode(),
                           currency=inv["currency"])


# --------------------------------------------------------------------------- meta & settings

@app.get("/api/meta")
def meta():
    last = db.query("SELECT * FROM agent_runs ORDER BY id DESC LIMIT 1", one=True)
    return ok({"settings": db.get_settings(), "paypal_mode": paypal.mode(), "ai_mode": "claude" if assistant.llm_enabled() else "engine",
               "model": assistant.MODEL if assistant.llm_enabled() else None, "today": date.today().isoformat(),
               "agent": {"interval": AGENT_INTERVAL, "last_run": last}, "currencies": db.FX_TO_USD})


@app.post("/api/settings")
def save_settings():
    body = request.get_json(force=True) or {}
    for k in db.DEFAULT_SETTINGS:
        if k in body:
            db.set_setting(k, body[k])
    return ok(db.get_settings())


@app.post("/api/reset")
def reset():
    db.seed(force=True)
    engine.run_agent()
    return ok()


# --------------------------------------------------------------------------- dashboard data

@app.get("/api/summary")
def summary():
    return ok(engine.summary())


@app.get("/api/overview")
def overview():
    return ok({"summary": engine.summary(), "revenue": engine.revenue_series(request.args.get("period", "monthly")),
               "recommendations": engine.recommendations(), "health": engine.health(),
               "recent": engine.transactions(8), "currency": engine.currency_exposure()})


@app.get("/api/revenue")
def revenue():
    return ok(engine.revenue_series(request.args.get("period", "monthly"), int(request.args.get("n", 12))))


@app.get("/api/transactions")
def transactions():
    rows = engine.transactions()
    q = (request.args.get("q") or "").lower()
    kind = request.args.get("kind")
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    if q:
        rows = [r for r in rows if q in " ".join(str(v) for v in r.values()).lower()]
    return ok(rows)


@app.get("/api/invoices")
def list_invoices():
    return ok(engine.invoices(request.args.get("status")))


@app.get("/api/invoices/<int:iid>")
def get_invoice(iid):
    inv = next((i for i in engine.invoices() if i["id"] == iid), None)
    if not inv:
        return err("Not found", 404)
    return ok({**inv, "risk": engine.risk_assessment(inv) if inv["status_view"] in ("sent", "overdue") else None})


@app.post("/api/invoices/parse")
def parse_invoice():
    text = (request.get_json(force=True) or {}).get("text", "")
    if not text.strip():
        return err("Describe the invoice first.")
    return ok(assistant.parse_invoice(text))


@app.post("/api/invoices")
def create_invoice():
    b = request.get_json(force=True) or {}
    if not b.get("approved"):
        return err("Invoice must be reviewed and approved before it is created.")
    try:
        amount = float(b.get("amount") or 0)
    except ValueError:
        return err("Amount must be a number.")
    if amount <= 0:
        return err("Amount must be greater than zero.")
    cid = b.get("customer_id")
    if not cid:
        name = (b.get("customer_name") or "").strip()
        if not name:
            return err("Choose or enter a client.")
        existing = db.query("SELECT id FROM customers WHERE lower(name)=lower(?)", (name,), one=True)
        cid = existing["id"] if existing else db.execute(
            "INSERT INTO customers(name, email, country, currency, created_at) VALUES(?,?,?,?,?)",
            (name, b.get("customer_email", ""), "", b.get("currency", "USD"), date.today().isoformat()))
    tax, disc = float(b.get("tax_rate") or 0), float(b.get("discount") or 0)
    total = round(amount * (1 - disc / 100) * (1 + tax / 100), 2)
    number = db.next_invoice_number()
    iid = db.execute(
        """INSERT INTO invoices(number, customer_id, description, subtotal, tax_rate, discount, total, currency, issue_date,
           due_date, status, terms, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (number, cid, b.get("description") or "Professional services", amount, tax, disc, total, b.get("currency", "USD"),
         b.get("issue_date") or date.today().isoformat(), b["due_date"], "sent" if b.get("send") else "draft",
         b.get("terms") or "", datetime.now().isoformat(timespec="seconds")))
    pp = None
    if b.get("send"):
        inv = next(i for i in engine.invoices() if i["id"] == iid)
        try:
            pp = paypal.create_and_send_invoice(inv, db.get_settings()["business_name"])
            db.execute("UPDATE invoices SET paypal_invoice_id=? WHERE id=?", (pp["id"], iid))
        except Exception as e:  # keep the local invoice even if PayPal is unreachable
            pp = {"error": str(e)}
    return ok({"id": iid, "number": number, "total": total, "paypal": pp, "pay_url": f"/pay/{number}"})


@app.post("/api/invoices/<int:iid>/send")
def send_invoice(iid):
    inv = next((i for i in engine.invoices() if i["id"] == iid), None)
    if not inv:
        return err("Not found", 404)
    pp = paypal.create_and_send_invoice(inv, db.get_settings()["business_name"])
    db.execute("UPDATE invoices SET status='sent', paypal_invoice_id=? WHERE id=?", (pp["id"], iid))
    return ok(pp)


@app.post("/api/invoices/<int:iid>/mark_paid")
def mark_paid(iid):
    inv = next((i for i in engine.invoices() if i["id"] == iid), None)
    if not inv:
        return err("Not found", 404)
    paid_tx = db.query("SELECT date FROM transactions WHERE invoice_id=? AND kind='payment' ORDER BY date DESC LIMIT 1", (iid,), one=True)
    if not paid_tx:
        b = request.get_json(silent=True) or {}
        if not b.get("record_payment"):
            return err("No payment found for this invoice. Confirm to record a manual payment.", 409)
        d = date.today().isoformat()
        db.execute("""INSERT INTO transactions(invoice_id, customer_id, kind, amount, currency, amount_usd, date, reference,
                      status, source, note) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                   (iid, inv["customer_id"], "payment", inv["total"], inv["currency"], inv["total_usd"], d, f"MANUAL-{iid}",
                    "completed", "manual", "Recorded manually"))
    else:
        d = paid_tx["date"]
    db.execute("UPDATE invoices SET status='paid', paid_date=? WHERE id=?", (d, iid))
    return ok()


@app.post("/api/invoices/<int:iid>/void")
def void_invoice(iid):
    db.execute("UPDATE invoices SET status='cancelled' WHERE id=?", (iid,))
    return ok()


@app.get("/api/customers")
def customers():
    return ok(engine.customer_stats())


@app.get("/api/customers/<int:cid>")
def customer(cid):
    c = next((c for c in engine.customer_stats() if c["id"] == cid), None)
    if not c:
        return err("Not found", 404)
    invs = [engine._inv_brief(i) for i in engine.invoices() if i["customer_id"] == cid]
    return ok({**c, "invoices": invs})


@app.get("/api/insights")
def insights():
    return ok({"risk": engine.at_risk(), "leaks": engine.leaks(), "recommendations": engine.recommendations()})


@app.get("/api/forecast")
def forecast():
    return ok(engine.forecast(int(request.args.get("days", 90))))


@app.post("/api/simulate")
def simulate():
    b = request.get_json(force=True) or {}
    return ok(engine.simulate(text=b.get("text"), scenario=b.get("scenario"), days=int(b.get("days", 90))))


@app.get("/api/health")
def health():
    return ok(engine.health())


@app.get("/api/currency")
def currency():
    return ok(engine.currency_exposure())


# --------------------------------------------------------------------------- alerts & agent

@app.get("/api/alerts")
def alerts():
    rows = db.query("SELECT * FROM alerts WHERE dismissed=0 ORDER BY created_at DESC, id DESC")
    last = db.query("SELECT * FROM agent_runs ORDER BY id DESC LIMIT 1", one=True)
    runs = db.query("SELECT COUNT(*) AS n FROM agent_runs", one=True)["n"]
    return ok({"alerts": rows, "last_run": last, "runs": runs, "interval": AGENT_INTERVAL})


@app.post("/api/alerts/<int:aid>/dismiss")
def dismiss(aid):
    db.execute("UPDATE alerts SET dismissed=1 WHERE id=?", (aid,))
    return ok()


@app.post("/api/agent/run")
def agent_run():
    return ok({"new": engine.run_agent()})


# --------------------------------------------------------------------------- recovery assistant

@app.get("/api/reminders/draft/<int:iid>")
def reminder_draft(iid):
    d = assistant.draft_reminder(iid, request.args.get("tone"))
    return ok(d) if d else err("Not found", 404)


@app.get("/api/reminders")
def reminders():
    return ok(db.query("""SELECT r.*, i.number, c.name AS customer FROM reminders r JOIN invoices i ON i.id=r.invoice_id
                          JOIN customers c ON c.id=i.customer_id ORDER BY r.created_at DESC, r.id DESC"""))


@app.post("/api/reminders")
def send_reminder():
    b = request.get_json(force=True) or {}
    if not b.get("confirm"):
        return err("Reminders are only sent after explicit confirmation.")
    now = datetime.now().isoformat(timespec="seconds")
    rid = db.execute("""INSERT INTO reminders(invoice_id, tone, subject, body, status, created_at, sent_at)
                        VALUES(?,?,?,?,?,?,?)""", (b["invoice_id"], b.get("tone", "friendly"), b.get("subject", ""),
                                                     b.get("body", ""), "sent", now, now))
    return ok({"id": rid, "delivery": "simulated" if not os.environ.get("SMTP_HOST") else "smtp"})


# --------------------------------------------------------------------------- Ask NEXA

@app.post("/api/ask")
def ask():
    q = ((request.get_json(force=True) or {}).get("q") or "").strip()
    if not q:
        return err("Ask me something.")
    return ok(assistant.answer(q))


# --------------------------------------------------------------------------- reports

@app.get("/api/reports")
def report():
    return ok(reports.build(request.args.get("kind", "monthly"), request.args.get("month")))


@app.get("/api/reports.csv")
def report_csv():
    rep = reports.build(request.args.get("kind", "monthly"), request.args.get("month"))
    fname = f"nexa-{rep['kind']}-report-{date.today().isoformat()}.csv"
    return Response(reports.to_csv(rep), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={fname}"})


# --------------------------------------------------------------------------- PayPal checkout

@app.get("/api/public/invoice/<number>")
def public_invoice(number):
    inv = next((i for i in engine.invoices() if i["number"] == number), None)
    if not inv:
        return err("Not found", 404)
    pay = db.query("SELECT reference, date, amount, currency, source FROM transactions WHERE invoice_id=? AND kind='payment' ORDER BY id DESC LIMIT 1",
                   (inv["id"],), one=True)
    keep = ("number", "customer", "description", "subtotal", "tax_rate", "discount", "total", "currency", "issue_date",
            "due_date", "status_view", "days_overdue", "amount_paid")
    return ok({**{k: inv[k] for k in keep}, "business": db.get_settings()["business_name"], "payment": pay,
               "paypal_mode": paypal.mode()})


@app.post("/api/paypal/orders")
def pp_create():
    number = (request.get_json(force=True) or {}).get("invoice")
    inv = next((i for i in engine.invoices() if i["number"] == number), None)
    if not inv:
        return err("Invoice not found", 404)
    if inv["status"] == "paid":
        return err("This invoice has already been paid.", 409)
    try:
        order = paypal.create_order(inv)
    except Exception as e:
        return err(f"PayPal error: {e}", 502)
    db.execute("UPDATE invoices SET paypal_order_id=? WHERE id=?", (order["id"], inv["id"]))
    return ok(order, id=order["id"])


@app.post("/api/paypal/orders/<oid>/approve-sim")
def pp_approve_sim(oid):
    if paypal.live():
        return err("Only available in demo mode", 400)
    o = paypal.approve_simulated(oid)
    return ok(o) if o else err("Unknown order", 404)


@app.post("/api/paypal/orders/<oid>/capture")
def pp_capture(oid):
    inv = db.query("SELECT * FROM invoices WHERE paypal_order_id=?", (oid,), one=True)
    if not inv:
        return err("Order not linked to an invoice", 404)
    res = paypal.capture_order(oid)
    if not res.get("ok"):
        return err(res.get("error", "Payment not completed"), 402)
    # Server-side verification: currency and amount must match what we billed.
    already = db.query("SELECT COALESCE(SUM(amount), 0) AS s FROM transactions WHERE invoice_id=? AND kind='payment'",
                       (inv["id"],), one=True)["s"]
    expected = round(inv["total"] - already, 2)
    if inv["currency"] in paypal.NO_DECIMAL:
        expected = round(expected)
    if res["currency"] != inv["currency"] or abs(res["amount"] - expected) > 0.01:
        return err(f"Verification failed: received {res['currency']} {res['amount']}, expected {inv['currency']} {expected}", 409)
    today = date.today().isoformat()
    db.execute("""INSERT INTO transactions(invoice_id, customer_id, kind, amount, currency, amount_usd, date, reference, status,
                  source, note) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
               (inv["id"], inv["customer_id"], "payment", res["amount"], res["currency"], db.to_usd(res["amount"], res["currency"]),
                today, res["capture_id"], "completed", f"paypal-{paypal.mode()}", f"Order {oid}"))
    db.execute("UPDATE invoices SET status='paid', paid_date=? WHERE id=?", (today, inv["id"]))
    db.execute("""INSERT OR IGNORE INTO alerts(key, severity, title, detail, action, target, created_at) VALUES(?,?,?,?,?,?,?)""",
               (f"paid:{inv['number']}", "good", f"Payment received for {inv['number']}",
                f"{res['currency']} {res['amount']:,.2f} captured via PayPal ({res['capture_id']}).", "transactions", "",
                datetime.now().isoformat(timespec="seconds")))
    return ok(res)


# --------------------------------------------------------------------------- agent thread

def _agent_loop():
    while True:
        try:
            engine.run_agent()
        except Exception as e:  # keep the agent alive
            print("[agent] error:", e)
        time.sleep(AGENT_INTERVAL)


def start_agent():
    t = threading.Thread(target=_agent_loop, daemon=True, name="nexa-agent")
    t.start()


def create_app():
    db.seed()
    start_agent()
    return app
