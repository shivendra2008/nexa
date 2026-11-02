"""Ask NEXA, Smart Invoice Studio parsing and the Payment Recovery copywriter.

Answers are always computed from stored data first (grounded). If ANTHROPIC_API_KEY is set and the
`anthropic` package is installed, Claude rephrases the grounded facts into a conversational answer —
it is instructed never to introduce numbers that are not in the facts. Without a key, the
deterministic answer is returned as-is.
"""
import json
import os
import re
from datetime import date, datetime, timedelta

from . import db, engine

try:
    import anthropic  # optional
except ImportError:  # pragma: no cover
    anthropic = None

MODEL = os.environ.get("NEXA_MODEL", "claude-opus-5-5")


def llm_enabled():
    return bool(anthropic and os.environ.get("ANTHROPIC_API_KEY"))


def _money(v, cur="USD"):
    sym = db.CURRENCY_SYMBOL.get(cur, cur + " ")
    return f"{sym}{v:,.0f}" if cur in ("INR", "JPY") else f"{sym}{v:,.2f}"


# --------------------------------------------------------------------------- invoice parsing

CUR_HINTS = [(r"€|\beur(os?)?\b", "EUR"), (r"£|\bgbp\b|\bpounds?\b", "GBP"), (r"₹|\binr\b|\brupees?\b", "INR"),
             (r"c\$|\bcad\b", "CAD"), (r"a\$|\baud\b", "AUD"), (r"¥|\bjpy\b|\byen\b", "JPY"), (r"\$|\busd\b|\bdollars?\b", "USD")]


def parse_invoice(text):
    t = text.strip()
    low = t.lower()
    custs = db.query("SELECT * FROM customers")
    s = db.get_settings()
    notes = []

    currency = None
    for pat, cur in CUR_HINTS:
        if re.search(pat, low):
            currency = cur
            break
    m = re.search(r"(?:[$€£₹¥]|c\$|a\$)\s?([\d,]+(?:\.\d+)?)\s*(k)?", low) or \
        re.search(r"([\d,]+(?:\.\d+)?)\s*(k)?\s*(?:usd|eur|gbp|inr|cad|aud|jpy|dollars?|euros?|pounds?|rupees?)", low) or \
        re.search(r"(?:for|of|amount|total)\s+([\d,]+(?:\.\d+)?)\s*(k)?\b(?!\s*(?:days?|weeks?|%))", low)
    amount = None
    if m:
        amount = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
    else:
        notes.append("No amount found — please fill it in.")

    customer = None
    for c in custs:
        if c["name"].lower() in low or re.search(rf"\b{re.escape(c['name'].lower().split()[0])}\b", low):
            customer = c
            break
    new_client_name = None
    if not customer:
        mc = re.search(r"\b(?:to|for|bill|client|customer)\s+([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,3})", t)
        if mc and not re.match(r"(A|An|The)$", mc.group(1)):
            new_client_name = mc.group(1).strip()
            notes.append(f"“{new_client_name}” is a new client — they'll be added on approval.")
        else:
            notes.append("No client recognised — choose one.")
    if not currency:
        currency = customer["currency"] if customer else s["base_currency"]

    due_days = None
    md = re.search(r"(?:due|payable)\s+(?:in|within)\s+(\d+)\s*(day|days|week|weeks)", low) or \
        re.search(r"net\s*-?\s*(\d+)()", low) or re.search(r"(\d+)\s*(day|days|week|weeks)\s+(?:terms|to pay)", low)
    if md:
        due_days = int(md.group(1)) * (7 if md.group(2) and md.group(2).startswith("week") else 1)
    elif "end of month" in low or "eom" in low:
        today = date.today()
        due_days = (engine._add_months(date(today.year, today.month, 1), 1) - timedelta(days=1) - today).days
    else:
        mdate = re.search(r"due\s+(?:on\s+)?([a-z]{3,9}\s+\d{1,2})", low)
        if mdate:
            try:
                d = datetime.strptime(f"{mdate.group(1)} {date.today().year}", "%B %d %Y").date()
            except ValueError:
                try:
                    d = datetime.strptime(f"{mdate.group(1)} {date.today().year}", "%b %d %Y").date()
                except ValueError:
                    d = None
            if d:
                if d < date.today():
                    d = d.replace(year=d.year + 1)
                due_days = (d - date.today()).days

    tax = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:tax|vat|gst)", low)
    disc = re.search(r"(\d+(?:\.\d+)?)\s*%\s*discount|discount\s*(?:of)?\s*(\d+(?:\.\d+)?)\s*%", low)

    desc = None
    mdesc = re.search(r"for\s+(?:a|an|the)?\s*(?:[$€£₹¥][\d,.]+k?\s*)?(.+?)(?:\s+project)?(?:,|\s+due|\s+payable|\s+net|\s+with|\s+to\s+[A-Z]|$)", t, re.I)
    if mdesc:
        desc = mdesc.group(1).strip(" .")
        desc = re.sub(r"^(?:[$€£₹¥]\s?[\d,.]+k?|[\d,.]+\s*(?:usd|eur|gbp|dollars?))\s*", "", desc, flags=re.I)
        if customer:
            desc = re.sub(rf"\s*\b(?:for|to)\s+{re.escape(customer['name'])}\b.*$", "", desc, flags=re.I)
            if desc.lower().startswith(customer["name"].lower()):
                desc = None
    if not desc or len(desc) < 3:
        desc = "Professional services"
    desc = desc[0].upper() + desc[1:]
    if "project" in low and "project" not in desc.lower():
        desc += " project"

    # Suggested terms from the client's actual payment behaviour
    suggestion = {"days": int(s["default_terms_days"]), "deposit_pct": 0, "reason": "Your default terms."}
    if customer:
        stats = next((c for c in engine.customer_stats() if c["id"] == customer["id"]), None)
        if stats:
            if stats["avg_days_late"] > 12:
                suggestion = {"days": 7, "deposit_pct": 30,
                              "reason": f"{customer['name']} pays {stats['avg_days_late']:.0f} days late on average "
                                        f"({stats['on_time_rate']}% on time). Net 7 with a 30% deposit reduces exposure."}
            elif stats["avg_days_late"] > 5:
                suggestion = {"days": 10, "deposit_pct": 0,
                              "reason": f"{customer['name']} is usually {stats['avg_days_late']:.0f} days late — "
                                        f"shorter terms bring the actual payment date closer to your target."}
            else:
                suggestion = {"days": 14 if stats["avg_days_to_pay"] and stats["avg_days_to_pay"] < 20 else 30, "deposit_pct": 0,
                              "reason": f"{customer['name']} is a reliable payer ({stats['on_time_rate']}% on time)."}
    if due_days is None:
        due_days = suggestion["days"]
        notes.append(f"No due date given — applied suggested Net {due_days}.")
    issue = date.today()
    return {
        "customer_id": customer["id"] if customer else None,
        "customer_name": customer["name"] if customer else new_client_name,
        "customer_email": customer["email"] if customer else "",
        "description": desc, "amount": amount, "currency": currency,
        "tax_rate": float(tax.group(1)) if tax else 0.0,
        "discount": float(disc.group(1) or disc.group(2)) if disc else 0.0,
        "issue_date": issue.isoformat(), "due_date": (issue + timedelta(days=due_days)).isoformat(),
        "due_days": due_days, "suggested_terms": suggestion, "notes": notes,
    }


# --------------------------------------------------------------------------- reminders

def draft_reminder(invoice_id, tone=None):
    inv = next((i for i in engine.invoices() if i["id"] == int(invoice_id)), None)
    if not inv:
        return None
    s = db.get_settings()
    stats = next((c for c in engine.customer_stats() if c["id"] == inv["customer_id"]), {})
    od = inv["days_overdue"]
    if not tone:
        tone = "friendly" if od <= 7 and inv["reminders"] == 0 else "firm" if od <= 30 and inv["reminders"] < 2 else "final"
    amt = _money(inv["total"] - (inv["amount_paid"] or 0), inv["currency"])
    pay_link = f"{os.environ.get('NEXA_PUBLIC_URL') or os.environ.get('RENDER_EXTERNAL_URL', 'http://localhost:5050')}/pay/{inv['number']}"
    first = inv["customer"].split()[0]
    status_line = (f"was due on {inv['due_date']} ({od} days ago)" if od > 0 else f"is due on {inv['due_date']}")
    if tone == "friendly":
        subject = f"Friendly reminder: invoice {inv['number']}"
        body = (f"Hello {first} team!\n\nThis is a friendly reminder regarding invoice {inv['number']} for "
                f"{inv['description']}, which {status_line}. The outstanding amount is {amt}.\n\n"
                f"You can pay securely via PayPal here: {pay_link}\n\nPlease let us know if you need any "
                f"clarification. We would appreciate your payment at your earliest convenience.\n\nThank you,\n"
                f"{s['owner_name']} · {s['business_name']}")
    elif tone == "firm":
        subject = f"Payment overdue: invoice {inv['number']} ({amt})"
        body = (f"Hello {first} team,\n\nOur records show that invoice {inv['number']} ({amt}) {status_line} and "
                f"remains unpaid. We'd be grateful if you could arrange payment within the next 5 business days.\n\n"
                f"Pay via PayPal: {pay_link}\n\nIf payment has already been sent, please share the transaction "
                f"reference so we can reconcile it. If there's an issue with the invoice, just reply and we'll "
                f"sort it out.\n\nBest regards,\n{s['owner_name']} · {s['business_name']}")
    else:
        subject = f"Final notice: invoice {inv['number']} is {od} days overdue"
        body = (f"Hello {first} team,\n\nDespite previous reminders, invoice {inv['number']} ({amt}) {status_line} "
                f"remains outstanding. Please settle the balance within 7 days to avoid a pause on ongoing work.\n\n"
                f"Pay via PayPal: {pay_link}\n\nWe value working with you and are happy to discuss a payment plan "
                f"if that would help — just reply to this email.\n\nRegards,\n{s['owner_name']} · {s['business_name']}")
    # Timing: send early in the week, mid-morning; sooner for slow payers.
    today = date.today()
    send_on = today if today.weekday() < 4 else today + timedelta(days=7 - today.weekday())
    timing = (f"Send {'today' if send_on == today else send_on.strftime('%A')} around 10:00 — mid-morning, early-week "
              f"emails get the fastest responses.")
    if stats.get("avg_days_late", 0) > 10 and od <= 0:
        timing = "Send now, before the due date — this client typically pays well after it."
    history = db.query("SELECT * FROM reminders WHERE invoice_id=? ORDER BY created_at DESC", (inv["id"],))
    return {"invoice": engine._inv_brief(inv), "tone": tone, "subject": subject, "body": body,
            "timing": timing, "pay_link": pay_link, "history": history}


# --------------------------------------------------------------------------- Ask NEXA

def _table(cols, rows):
    return {"type": "table", "columns": cols, "rows": rows}


def _month_from_text(t):
    months = {m.lower(): i for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}
    today = date.today()
    for name, i in months.items():
        if re.search(rf"\b{name}\b|\b{name[:3]}\b", t):
            y = today.year if i <= today.month else today.year - 1
            return y, i
    if "last month" in t or "previous month" in t:
        d = engine._add_months(date(today.year, today.month, 1), -1)
        return d.year, d.month
    return None


INTENTS = [
    ("help", r"^(hi|hello|hey|help|what can you do)\b"),
    ("pending", r"pending|outstanding|unpaid|owe|receivable"),
    ("remind", r"remind|reminder|follow[\s-]?up|chase|nudge"),
    ("decline", r"declin|drop|why .*(down|lower|less)|explain.*revenue|revenue.*(fall|fell|decrease)"),
    ("late", r"late|slow|consistently|worst payer|delay"),
    ("prioritize", r"priorit|today|focus|what should i|next step|action"),
    ("attention", r"attention|risk|flag|problem|concern|worry"),
    ("simulate", r"what if|what happens|simulate|scenario"),
    ("cashflow", r"cash\s*flow|forecast|expect|project|runway|balance"),
    ("health", r"health|score|how am i doing|how's my business"),
    ("currency", r"currenc|fx|exchange|eur|gbp|inr|international"),
    ("leaks", r"leak|duplicate|discrepanc|mismatch|reconcil"),
    ("top", r"top|best|biggest|largest|most valuable"),
    ("revenue", r"revenue|income|earn|made|receiv|sales"),
    ("customer", r"client|customer"),
]


def _detect(q):
    t = q.lower()
    for name, pat in INTENTS:
        if re.search(pat, t):
            return name
    return "fallback"


def _find_customer(t):
    for c in engine.customer_stats():
        if c["name"].lower() in t or re.search(rf"\b{re.escape(c['name'].lower().split()[0])}\b", t):
            return c
    return None


def answer(question):
    t = question.lower().strip()
    intent = _detect(t)
    blocks, actions, facts = [], [], {}
    text = ""
    today = date.today()

    if intent == "help":
        text = ("I'm NEXA, your financial copilot. I answer from your actual invoices and PayPal payments. Try asking "
                "which invoices need attention, how much you earned this month, your expected cash flow, or "
                "“what if Acme pays 2 weeks late?”. I can also draft payment reminders — you approve before anything is sent.")

    elif intent == "pending":
        c = _find_customer(t)
        rows = engine.open_invoices()
        if c:
            rows = [r for r in rows if r["customer_id"] == c["id"]]
        by_c = {}
        for r in rows:
            e = by_c.setdefault(r["customer"], {"n": 0, "usd": 0.0, "overdue": 0})
            e["n"] += 1
            e["usd"] += r["total_usd"]
            e["overdue"] += r["status_view"] == "overdue"
        total = sum(v["usd"] for v in by_c.values())
        facts = {"clients_with_pending": len(by_c), "pending_total_usd": round(total, 2), "by_client": by_c}
        text = (f"{len(by_c)} client(s) have {len(rows)} pending invoice(s) worth ${total:,.0f} in total. "
                + (f"{sum(v['overdue'] for v in by_c.values())} of them are already overdue." if rows else ""))
        blocks.append(_table(["Client", "Invoices", "Overdue", "Amount (USD)"],
                             [[k, v["n"], v["overdue"], f"${v['usd']:,.0f}"] for k, v in sorted(by_c.items(), key=lambda kv: -kv[1]["usd"])]))

    elif intent == "revenue":
        ym = _month_from_text(t)
        if ym:
            y, mth = ym
            cur = engine.month_revenue(y, mth)
            p = engine._add_months(date(y, mth, 1), -1)
            prev = engine.month_revenue(p.year, p.month)
            label = date(y, mth, 1).strftime("%B %Y")
        elif "year" in t or "12 months" in t or "annual" in t:
            cur = engine.rolling_revenue(365)
            prev = None
            label = "the last 12 months"
        else:
            cur = engine.month_revenue(today.year, today.month)
            p = engine._add_months(date(today.year, today.month, 1), -1)
            prev = engine.month_revenue(p.year, p.month)
            label = f"{today.strftime('%B')} so far (through {today.strftime('%d %b')})"
        n = sum(1 for x in engine.payments() if (ym and x["date"].startswith(f"{ym[0]:04d}-{ym[1]:02d}")) or
                (not ym and x["date"].startswith(today.strftime("%Y-%m"))))
        facts = {"period": label, "revenue_usd": cur, "previous_month_usd": prev, "payments": n}
        text = f"You received ${cur:,.2f} in {label}" + (f" from {n} payment(s)." if "12 months" not in label else ".")
        if prev is not None:
            diff = cur - prev
            text += f" The previous month was ${prev:,.2f} ({'+' if diff >= 0 else '−'}${abs(diff):,.0f})."
        if not ym and today.day < 7 and "12 months" not in label:
            text += f" Since the month has just started, the last 30 days are more telling: ${engine.rolling_revenue(30):,.2f} received."
        s = engine.revenue_series("monthly", 6)
        blocks.append({"type": "bars", "labels": s["labels"], "values": s["values"]})

    elif intent == "cashflow":
        fc = engine.forecast(30)
        fc90 = engine.forecast(90)
        facts = {"expected_inflow_30d": fc["expected_inflow"], "expected_outflow_30d": fc["expected_outflow"],
                 "ending_balance_30d": fc["ending_balance"], "ending_balance_90d": fc90["ending_balance"],
                 "confidence_30d": fc["confidence"]}
        text = (f"Over the next 30 days I expect about ${fc['expected_inflow']:,.0f} in, against ${fc['expected_outflow']:,.0f} "
                f"of operating expenses — ending around ${fc['ending_balance']:,.0f} (confidence {fc['confidence']}%). "
                f"At 90 days the projection is ${fc90['ending_balance']:,.0f}. Inflows are risk-weighted: each open invoice "
                f"is placed on its likely payment date and discounted by its collection probability.")
        actions.append({"type": "goto", "to": "cashflow", "label": "Open Cash Flow forecast"})

    elif intent in ("attention", "prioritize"):
        risk = [r for r in engine.at_risk() if r["risk"]["level"] != "low"]
        lk = [l for l in engine.leaks() if l["severity"] == "high"]
        facts = {"risky_invoices": [{"n": r["number"], "c": r["customer"], "usd": r["total_usd"], "lvl": r["risk"]["level"]} for r in risk[:6]],
                 "record_issues": [l["title"] for l in lk]}
        if intent == "prioritize":
            steps = []
            if risk:
                steps.append(f"Chase {risk[0]['number']} ({risk[0]['customer']}, ${risk[0]['total_usd']:,.0f}) — {risk[0]['risk']['factors'][0]['why']}")
            for l in lk[:2]:
                steps.append(f"Fix: {l['title']}")
            due = [i for i in engine.open_invoices() if i["status_view"] == "sent" and 0 <= i["days_to_due"] <= 3]
            if due:
                steps.append(f"Pre-empt {len(due)} invoice(s) due within 3 days with a friendly nudge.")
            if len(risk) > 1:
                steps.append(f"Batch reminders for the other {len(risk) - 1} at-risk invoice(s).")
            text = "Here's what I'd prioritise today:\n" + "\n".join(f"{k}. {s}" for k, s in enumerate(steps, 1)) if steps else \
                "Nothing urgent today — all invoices look on track."
        else:
            text = (f"{len(risk)} invoice(s) need attention, totalling ${sum(r['total_usd'] for r in risk):,.0f}." if risk
                    else "No invoices are currently flagged.") + (f" There are also {len(lk)} record issue(s) to reconcile." if lk else "")
        blocks.append(_table(["Invoice", "Client", "Amount", "Risk", "Main reason"],
                             [[r["number"], r["customer"], _money(r["total"], r["currency"]), f"{r['risk']['level']} ({r['risk']['score']})",
                               r["risk"]["factors"][0]["why"]] for r in risk[:8]]))
        if risk:
            actions.append({"type": "remind", "invoice_id": risk[0]["id"], "label": f"Draft reminder for {risk[0]['number']}"})

    elif intent == "remind":
        c = _find_customer(t)
        mnum = re.search(r"nx-?\d+", t)
        cands = [r for r in engine.at_risk()]
        if mnum:
            num = mnum.group(0).upper().replace("NX", "NX-").replace("--", "-")
            cands = [r for r in cands if r["number"] == num]
        elif c:
            cands = [r for r in cands if r["customer_id"] == c["id"]]
        cands = sorted(cands, key=lambda r: (-r["days_overdue"], -r["risk"]["score"]))
        if not cands:
            text = "I couldn't find an open invoice to remind about" + (f" for {c['name']}." if c else ".")
        else:
            d = draft_reminder(cands[0]["id"])
            facts = {"invoice": d["invoice"]["number"], "tone": d["tone"]}
            text = (f"Here's a {d['tone']} reminder for {d['invoice']['number']} ({d['invoice']['customer']}, "
                    f"{_money(d['invoice']['total'], d['invoice']['currency'])}). {d['timing']} Review it — nothing is sent until you confirm.")
            blocks.append({"type": "draft", "subject": d["subject"], "body": d["body"], "invoice_id": d["invoice"]["id"], "tone": d["tone"]})
            actions.append({"type": "send_reminder", "invoice_id": d["invoice"]["id"], "tone": d["tone"],
                            "subject": d["subject"], "body": d["body"], "label": "Send reminder", "confirm": True})

    elif intent == "decline":
        s = engine.revenue_series("monthly", 4)
        a, b = s["values"][-3], s["values"][-2]  # last two complete months
        la, lb = s["labels"][-3], s["labels"][-2]
        pays = engine.payments()

        def by_client(lbl_idx):
            first = engine._add_months(date(today.year, today.month, 1), -(4 - 1 - lbl_idx))
            key = first.strftime("%Y-%m")
            out = {}
            for p in pays:
                if p["date"].startswith(key):
                    out[p["customer"]] = out.get(p["customer"], 0) + p["amount_usd"]
            return out
        ca, cb = by_client(1), by_client(2)
        diffs = sorted(((k, cb.get(k, 0) - ca.get(k, 0)) for k in set(ca) | set(cb)), key=lambda x: x[1])
        facts = {"months": [la, lb], "values": [a, b], "drivers": diffs[:4]}
        if b < a:
            text = f"Revenue fell from ${a:,.0f} in {la} to ${b:,.0f} in {lb} (−{(a - b) / a * 100:.0f}%). Main drivers:"
        else:
            text = (f"Revenue actually rose from ${a:,.0f} in {la} to ${b:,.0f} in {lb}. "
                    f"Over the last 30 days vs the prior 30 it's ${engine.rolling_revenue(30):,.0f} vs ${engine.rolling_revenue(30, 30):,.0f}. Biggest movers:")
        blocks.append(_table(["Client", f"{la}", f"{lb}", "Change"],
                             [[k, f"${ca.get(k, 0):,.0f}", f"${cb.get(k, 0):,.0f}", f"{'+' if d >= 0 else '−'}${abs(d):,.0f}"] for k, d in diffs[:6]]))
        slow = [c for c in engine.customer_stats() if c["trend"] == "slowing"]
        if slow:
            text += f" Note: {', '.join(c['name'] for c in slow)} {'is' if len(slow) == 1 else 'are'} paying slower, which shifts revenue into later months."

    elif intent == "late":
        custs = sorted(engine.customer_stats(), key=lambda c: -c["avg_days_late"])
        late = [c for c in custs if c["avg_days_late"] > 5]
        facts = {"late_payers": [{"name": c["name"], "avg_days_late": c["avg_days_late"], "on_time_rate": c["on_time_rate"]} for c in late]}
        text = (f"{len(late)} client(s) consistently pay late: " + ", ".join(f"{c['name']} (~{c['avg_days_late']:.0f} days)" for c in late) + "."
                if late else "None of your clients pay consistently late.")
        blocks.append(_table(["Client", "Avg days late", "On-time rate", "Trend", "Pending"],
                             [[c["name"], c["avg_days_late"], f"{c['on_time_rate']}%", c["trend"], c["pending_invoices"]] for c in custs]))

    elif intent == "simulate":
        r = engine.simulate(question)
        facts = {"assumptions": r["assumptions"], "narrative": r["narrative"]}
        text = " ".join(r["narrative"]) if r["scenario"] else r["assumptions"][0]
        if r["scenario"]:
            blocks.append({"type": "list", "title": "Assumptions", "items": r["assumptions"]})
            actions.append({"type": "simulate", "to": "cashflow", "text": question, "label": "Open in What-If Simulator"})

    elif intent == "health":
        h = engine.health()
        facts = h
        weakest = sorted(h["components"], key=lambda c: c["score"])[:2]
        text = (f"Your Financial Health indicator is {h['score']}/100 ({h['label']}). Weakest areas: "
                + "; ".join(f"{c['name']} — {c['why']}" for c in weakest) + f" {h['disclaimer']}")
        blocks.append(_table(["Area", "Status", "Why"], [[c["name"], c["label"], c["why"]] for c in h["components"]]))

    elif intent == "currency":
        ex = engine.currency_exposure()
        facts = {"exposure": ex}
        intl = [e for e in ex if e["currency"] != "USD"]
        text = (f"You transact in {len(ex)} currencies. {sum(e['share'] for e in intl):.0f}% of received revenue is non-USD. "
                f"Pending foreign-currency receivables total ${sum(e['pending_usd'] for e in intl):,.0f} at reference rates.")
        blocks.append(_table(["Currency", "Received", "Pending", "Share", "Rate→USD"],
                             [[e["currency"], _money(e["received"], e["currency"]), _money(e["pending"], e["currency"]), f"{e['share']}%", e["rate_to_usd"]] for e in ex]))

    elif intent == "leaks":
        lk = engine.leaks()
        facts = {"issues": [l["title"] for l in lk]}
        text = f"I found {len(lk)} potential revenue leak(s)." if lk else "No revenue leaks detected."
        blocks.append({"type": "list", "title": "Findings", "items": [f"{l['title']} — {l['detail']}" for l in lk[:8]]})

    elif intent in ("top", "customer"):
        c = _find_customer(t)
        if c:
            facts = c
            text = (f"{c['name']}: {c['total_invoices']} invoices ({c['paid_invoices']} paid, {c['pending_invoices']} pending). "
                    f"Average payment time {c['avg_days_to_pay']} days, {c['on_time_rate']}% on time, "
                    f"${c['revenue_usd']:,.0f} received ({c['revenue_share']}% of total), ${c['outstanding_usd']:,.0f} outstanding. "
                    f"Behaviour: {c['behaviour'].lower()}, trend {c['trend']}.")
        else:
            custs = engine.customer_stats()[:5]
            facts = {"top": [(c["name"], c["revenue_usd"]) for c in custs]}
            text = f"Your top client is {custs[0]['name']} with ${custs[0]['revenue_usd']:,.0f} received ({custs[0]['revenue_share']}% of revenue)."
            blocks.append(_table(["Client", "Revenue", "Share", "Avg pay time", "Behaviour"],
                                 [[c["name"], f"${c['revenue_usd']:,.0f}", f"{c['revenue_share']}%", f"{c['avg_days_to_pay']}d", c["behaviour"]] for c in custs]))

    else:
        sm = engine.summary()
        facts = sm
        text = ("I'm not sure how to answer that from your records yet. Here's a quick snapshot instead: "
                f"${sm['revenue_last_30']:,.0f} received in the last 30 days, {sm['pending_count']} pending invoices "
                f"(${sm['pending_total']:,.0f}), {sm['at_risk_count']} at risk. Try “which invoices need attention?”.")

    phrased = _llm_phrase(question, text, facts) if llm_enabled() and intent not in ("help", "remind") else None
    return {"intent": intent, "text": phrased or text, "blocks": blocks, "actions": actions,
            "grounded": True, "ai": "claude" if phrased else "nexa-engine"}


SYSTEM = ("You are NEXA, a concise financial copilot for a small business. You will receive a user question, "
          "a draft answer and FACTS computed from the user's real records. Rewrite the draft as a clear, friendly "
          "answer of at most 4 sentences. Use ONLY numbers that appear in the draft or FACTS — never invent, round "
          "differently, or estimate new figures. Never claim an action (sending, paying) has been performed. "
          "Plain text, no markdown headings.")


def _llm_phrase(question, draft, facts):
    try:
        client = anthropic.Anthropic()
        resp = client.beta.messages.create(
            model=MODEL, max_tokens=1024,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            system=SYSTEM,
            messages=[{"role": "user", "content": f"QUESTION: {question}\n\nDRAFT: {draft}\n\nFACTS: {json.dumps(facts, default=str)[:12000]}"}],
        )
        if resp.stop_reason == "refusal":
            return None
        out = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        return out or None
    except Exception:  # any API/network failure → grounded deterministic answer
        return None
