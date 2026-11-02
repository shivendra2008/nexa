"""NEXA financial intelligence engine.

Every number here is derived from stored invoices/transactions — nothing is invented.
Models are deliberately transparent (weighted factors, moving averages) so each output
can be explained back to the user.
"""
import copy
import functools
import re
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import db

TODAY = date.today


def cached(fn):
    """Memoise until the data changes (db.version) or the day rolls over. Returns copies so callers can't
    mutate the cache. Keeps request latency low on small CPUs where recomputation dominates."""
    store = {"key": None, "vals": {}}

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        stamp = (db.version(), TODAY())
        if store["key"] != stamp:
            store["key"], store["vals"] = stamp, {}
        k = repr((args, sorted(kwargs.items())))
        if k not in store["vals"]:
            store["vals"][k] = fn(*args, **kwargs)
        return copy.deepcopy(store["vals"][k])
    return wrapper


@functools.lru_cache(maxsize=4096)
def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _d(s):
    return _parse_date(s[:10]) if s else None


def _month_key(d):
    return d.strftime("%Y-%m")


def _month_label(key):
    return datetime.strptime(key + "-01", "%Y-%m-%d").strftime("%b %Y")


def _add_months(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


# --------------------------------------------------------------------------- loaders

@cached
def invoices(status=None):
    rows = db.query("""SELECT i.*, c.name AS customer, c.email AS customer_email, c.country
                       FROM invoices i JOIN customers c ON c.id = i.customer_id ORDER BY i.issue_date DESC""")
    today = TODAY()
    paid_by_invoice = defaultdict(float)
    for t in db.query("SELECT invoice_id, amount FROM transactions WHERE kind='payment' AND invoice_id IS NOT NULL"):
        paid_by_invoice[t["invoice_id"]] += t["amount"]
    reminders = defaultdict(list)
    for r in db.query("SELECT * FROM reminders ORDER BY created_at"):
        reminders[r["invoice_id"]].append(r)
    out = []
    for r in rows:
        due = _d(r["due_date"])
        r["total_usd"] = db.to_usd(r["total"], r["currency"])
        r["amount_paid"] = round(paid_by_invoice.get(r["id"], 0.0), 2)
        r["reminders"] = len(reminders.get(r["id"], []))
        r["last_reminder"] = reminders[r["id"]][-1]["created_at"] if reminders.get(r["id"]) else None
        if r["status"] in ("sent", "draft") and due and due < today and r["status"] != "draft":
            r["status_view"] = "overdue"
            r["days_overdue"] = (today - due).days
        else:
            r["status_view"] = r["status"]
            r["days_overdue"] = 0
        r["days_to_due"] = (due - today).days if due else None
        out.append(r)
    if status:
        out = [r for r in out if r["status_view"] == status]
    return out


def open_invoices():
    """Invoices still awaiting money (excludes ones already fully paid but not yet reconciled)."""
    return [i for i in invoices() if i["status_view"] in ("sent", "overdue") and i["total"] - i["amount_paid"] > 0.01]


@cached
def transactions(limit=None):
    rows = db.query("""SELECT t.*, c.name AS customer, i.number AS invoice_number FROM transactions t
                       LEFT JOIN customers c ON c.id = t.customer_id LEFT JOIN invoices i ON i.id = t.invoice_id
                       ORDER BY t.date DESC, t.id DESC""" + (f" LIMIT {int(limit)}" if limit else ""))
    return rows


def payments():
    return [t for t in transactions() if t["kind"] == "payment"]


# --------------------------------------------------------------------------- customers

@cached
def customer_stats():
    today = TODAY()
    custs = db.query("SELECT * FROM customers ORDER BY name")
    invs = invoices()
    by_c = defaultdict(list)
    for i in invs:
        by_c[i["customer_id"]].append(i)
    total_rev = sum(i["total_usd"] for i in invs if i["status"] == "paid") or 1
    out = []
    for c in custs:
        ci = sorted(by_c[c["id"]], key=lambda x: x["issue_date"])
        paid = [i for i in ci if i["status"] == "paid" and i["paid_date"]]
        days_to_pay = [(_d(i["paid_date"]) - _d(i["issue_date"])).days for i in paid]
        lateness = [(_d(i["paid_date"]) - _d(i["due_date"])).days for i in paid]
        on_time = sum(1 for x in lateness if x <= 0)
        overdue_now = [i for i in ci if i["status_view"] == "overdue"]
        pending = [i for i in ci if i["status_view"] in ("sent", "overdue")]
        recent = [l for i, l in zip(paid, lateness) if _d(i["paid_date"]) > today - timedelta(days=120)]
        earlier = [l for i, l in zip(paid, lateness) if _d(i["paid_date"]) <= today - timedelta(days=120)]
        trend_delta = (statistics.mean(recent) - statistics.mean(earlier)) if recent and earlier else 0
        avg_late = statistics.mean(lateness) if lateness else 0
        late_sd = statistics.pstdev(lateness) if len(lateness) > 1 else 0
        on_time_rate = on_time / len(lateness) if lateness else 1
        revenue = sum(i["total_usd"] for i in paid)
        monthly = defaultdict(float)
        for i in paid:
            monthly[_month_key(_d(i["paid_date"]))] += i["total_usd"]
        spark = []
        m = _add_months(date(today.year, today.month, 1), -11)
        for _ in range(12):
            spark.append(round(monthly.get(_month_key(m), 0), 2))
            m = _add_months(m, 1)
        if avg_late <= 1 and on_time_rate >= 0.8:
            label, tone = "Reliable payer", "good"
        elif avg_late <= 7:
            label, tone = "Usually on time", "ok"
        elif avg_late <= 15:
            label, tone = "Often late", "warn"
        else:
            label, tone = "Chronically late", "bad"
        if trend_delta > 4:
            trend = "slowing"
        elif trend_delta < -4:
            trend = "improving"
        else:
            trend = "stable"
        out.append({
            "id": c["id"], "name": c["name"], "email": c["email"], "country": c["country"], "currency": c["currency"],
            "total_invoices": len(ci), "paid_invoices": len(paid), "pending_invoices": len(pending),
            "overdue_invoices": len(overdue_now),
            "avg_days_to_pay": round(statistics.mean(days_to_pay), 1) if days_to_pay else None,
            "avg_days_late": round(avg_late, 1), "lateness_sd": round(late_sd, 1),
            "on_time_rate": round(on_time_rate * 100), "revenue_usd": round(revenue, 2),
            "revenue_share": round(revenue / total_rev * 100, 1),
            "outstanding_usd": round(sum(i["total_usd"] for i in pending), 2),
            "trend": trend, "trend_delta": round(trend_delta, 1), "behaviour": label, "tone": tone,
            "sparkline": spark,
            "last_invoice": ci[-1]["issue_date"] if ci else None,
        })
    return sorted(out, key=lambda x: -x["revenue_usd"])


def _customer_map():
    return {c["id"]: c for c in customer_stats()}


# --------------------------------------------------------------------------- risk

def risk_assessment(inv, cmap=None):
    """Explainable payment-delay risk. Each factor contributes points with a plain-language reason."""
    cmap = cmap or _customer_map()
    c = cmap.get(inv["customer_id"], {})
    factors = []

    def add(name, pts, why):
        factors.append({"factor": name, "points": round(pts), "why": why})

    avg_late = c.get("avg_days_late", 0) or 0
    if avg_late > 0:
        add("Payment history", min(35, avg_late * 1.8),
            f"{c.get('name')} pays on average {avg_late:.0f} days after the due date.")
    else:
        add("Payment history", 0, f"{c.get('name')} usually pays on or before the due date.")
    otr = c.get("on_time_rate", 100)
    add("On-time rate", (100 - otr) * 0.2, f"{otr}% of their past invoices were paid on time.")
    if inv["days_overdue"] > 0:
        add("Already overdue", min(30, 8 + inv["days_overdue"] * 0.8),
            f"This invoice is {inv['days_overdue']} days past due.")
    elif inv["days_to_due"] is not None and inv["days_to_due"] <= 3:
        add("Due soon", 5, f"Due in {inv['days_to_due']} days.")
    other_overdue = c.get("overdue_invoices", 0) - (1 if inv["days_overdue"] > 0 else 0)
    if other_overdue > 0:
        add("Other overdue invoices", min(15, other_overdue * 7),
            f"The client has {other_overdue} other overdue invoice(s).")
    if c.get("trend") == "slowing":
        add("Slowing trend", 10, f"Their payments have slowed by ~{c['trend_delta']:.0f} days over the last 4 months.")
    avg_ticket = (c.get("revenue_usd", 0) / c["paid_invoices"]) if c.get("paid_invoices") else 0
    if avg_ticket and inv["total_usd"] > avg_ticket * 1.4:
        add("Larger than usual", 8, f"Amount is {inv['total_usd'] / avg_ticket:.1f}× their typical invoice.")
    if inv["days_overdue"] > 7 and inv["reminders"] == 0:
        add("No follow-up yet", 6, "No reminder has been sent since it became overdue.")
    score = max(0, min(100, sum(f["points"] for f in factors)))
    level = "high" if score >= 55 else "medium" if score >= 30 else "low"
    expected_delay = max(0, round(avg_late))
    due = _d(inv["due_date"])
    expected = max(TODAY() + timedelta(days=2), due + timedelta(days=expected_delay))
    if inv["days_overdue"] > 0:
        expected = max(expected, TODAY() + timedelta(days=max(3, round(avg_late - inv["days_overdue"]))))
    prob = max(0.35, min(0.98, 1 - score / 140))
    if level == "high":
        action = "Send a firm reminder today and offer a payment link."
    elif level == "medium":
        action = "Send a friendly reminder before the due date."
    else:
        action = "No action needed — monitor."
    return {
        "score": score, "level": level, "factors": sorted(factors, key=lambda f: -f["points"]),
        "expected_payment_date": expected.isoformat(), "collection_probability": round(prob, 2),
        "suggested_action": action,
    }


@cached
def at_risk():
    cmap = _customer_map()
    out = []
    for inv in open_invoices():
        r = risk_assessment(inv, cmap)
        out.append({**_inv_brief(inv), "risk": r})
    return sorted(out, key=lambda x: -x["risk"]["score"])


def _inv_brief(i):
    keys = ("id", "number", "customer", "customer_id", "customer_email", "description", "total", "currency",
            "total_usd", "issue_date", "due_date", "status_view", "days_overdue", "days_to_due", "reminders",
            "last_reminder", "paid_date", "amount_paid")
    return {k: i.get(k) for k in keys}


# --------------------------------------------------------------------------- revenue

@cached
def revenue_series(period="monthly", n=12):
    today = TODAY()
    pays = payments()
    buckets = defaultdict(float)
    counts = defaultdict(int)
    if period == "weekly":
        start = today - timedelta(days=today.weekday()) - timedelta(weeks=n - 1)
        for p in pays:
            d = _d(p["date"])
            if d >= start:
                k = (d - start).days // 7
                buckets[k] += p["amount_usd"]
                counts[k] += 1
        labels = [(start + timedelta(weeks=k)).strftime("%d %b") for k in range(n)]
        values = [round(buckets[k], 2) for k in range(n)]
        cnt = [counts[k] for k in range(n)]
    else:
        first = _add_months(date(today.year, today.month, 1), -(n - 1))
        keys = [_month_key(_add_months(first, k)) for k in range(n)]
        for p in pays:
            buckets[_month_key(_d(p["date"]))] += p["amount_usd"]
            counts[_month_key(_d(p["date"]))] += 1
        labels = [_month_label(k)[:3] + " " + k[2:4] for k in keys]
        values = [round(buckets[k], 2) for k in keys]
        cnt = [counts[k] for k in keys]
    return {"period": period, "labels": labels, "values": values, "counts": cnt}


@cached
def month_revenue(year, month):
    key = f"{year:04d}-{month:02d}"
    return round(sum(p["amount_usd"] for p in payments() if p["date"].startswith(key)), 2)


@cached
def rolling_revenue(days, offset=0):
    end = TODAY() - timedelta(days=offset)
    start = end - timedelta(days=days)
    return round(sum(p["amount_usd"] for p in payments() if start < _d(p["date"]) <= end), 2)


# --------------------------------------------------------------------------- summary

@cached
def summary():
    invs = invoices()
    pend = [i for i in invs if i["status_view"] in ("sent", "overdue")]
    risk = at_risk()
    risky = [r for r in risk if r["risk"]["level"] in ("high", "medium")]
    last30, prev30 = rolling_revenue(30), rolling_revenue(30, 30)
    growth = ((last30 - prev30) / prev30 * 100) if prev30 else 0
    paid = [i for i in invs if i["status"] == "paid" and i["paid_date"]]
    recent_paid = [i for i in paid if _d(i["paid_date"]) > TODAY() - timedelta(days=90)]
    avg_pay = statistics.mean([(_d(i["paid_date"]) - _d(i["issue_date"])).days for i in recent_paid]) if recent_paid else 0
    fc = forecast(30)
    today = TODAY()
    return {
        "total_revenue": round(sum(p["amount_usd"] for p in payments()), 2),
        "revenue_this_month": month_revenue(today.year, today.month),
        "revenue_last_30": last30, "revenue_prev_30": prev30,
        "pending_total": round(sum(i["total_usd"] for i in pend), 2), "pending_count": len(pend),
        "overdue_count": sum(1 for i in pend if i["status_view"] == "overdue"),
        "overdue_total": round(sum(i["total_usd"] for i in pend if i["status_view"] == "overdue"), 2),
        "expected_30": fc["expected_inflow"], "at_risk_total": round(sum(r["total_usd"] for r in risky), 2),
        "at_risk_count": len(risky), "growth_pct": round(growth, 1), "avg_payment_days": round(avg_pay, 1),
    }


# --------------------------------------------------------------------------- forecasting

@cached
def _baseline_new_business():
    """Weekly expected cash from invoices not yet issued, from the trailing-6-month run-rate of each active client."""
    today = TODAY()
    since = today - timedelta(days=180)
    per_client = defaultdict(float)
    for i in invoices():
        if _d(i["issue_date"]) >= since:
            per_client[i["customer_id"]] += i["total_usd"]
    return {cid: v / 26.0 for cid, v in per_client.items()}  # weekly


@cached
def forecast(days=90, scenario=None):
    """Weekly cash-flow forecast with confidence bands.

    Inflows: open invoices at their risk-adjusted expected date × collection probability,
    plus new business at each client's trailing run-rate (lagged by their usual payment time).
    Outflows: configured monthly operating expenses.
    """
    scenario = scenario or {}
    s = db.get_settings()
    today = TODAY()
    weeks = max(1, -(-days // 7))
    cmap = _customer_map()
    inflow = [0.0] * weeks
    contrib = [[] for _ in range(weeks)]
    delay = scenario.get("delay") or {}
    rev_mult = 1 + scenario.get("revenue_change_pct", 0) / 100
    exp_mult = 1 + scenario.get("expense_change_pct", 0) / 100
    fx = scenario.get("fx") or {}

    def fx_mult(cur):
        return 1 + fx.get(cur, 0) / 100

    for inv in open_invoices():
        r = risk_assessment(inv, cmap)
        exp = _d(r["expected_payment_date"])
        if str(inv["customer_id"]) in delay or inv["customer_id"] in delay:
            exp += timedelta(days=int(delay.get(str(inv["customer_id"]), delay.get(inv["customer_id"], 0))))
        w = (exp - today).days // 7
        if 0 <= w < weeks:
            amt = inv["total_usd"] * r["collection_probability"] * fx_mult(inv["currency"])
            inflow[w] += amt
            contrib[w].append({"invoice": inv["number"], "customer": inv["customer"], "amount": round(amt, 2)})

    base = _baseline_new_business()
    for cid, weekly in base.items():
        c = cmap.get(cid, {})
        lag_weeks = max(1, round(((c.get("avg_days_to_pay") or 20)) / 7))
        d_extra = int(delay.get(str(cid), delay.get(cid, 0))) // 7
        for w in range(lag_weeks + d_extra, weeks):
            inflow[w] += weekly * rev_mult * fx_mult(c.get("currency", "USD"))
    new_clients = scenario.get("new_clients", 0)
    if new_clients:
        avg_val = scenario.get("new_client_value") or statistics.mean(
            [i["total_usd"] for i in invoices()]) or 1500
        for w in range(5, weeks):  # assume first payment lands ~5 weeks out (onboarding + net terms)
            inflow[w] += new_clients * avg_val * 0.75 / 4.33

    monthly_exp = float(s["monthly_expenses"]) * exp_mult
    outflow = [round(monthly_exp / 4.33, 2)] * weeks
    bal = float(s["opening_balance"])
    balance, lo, hi = [], [], []
    for w in range(weeks):
        bal += inflow[w] - outflow[w]
        balance.append(round(bal, 2))
        spread = 0.06 + 0.025 * w  # uncertainty widens with horizon
        lo.append(round(bal - sum(inflow[: w + 1]) * spread, 2))
        hi.append(round(bal + sum(inflow[: w + 1]) * spread * 0.6, 2))
    labels = [(today + timedelta(weeks=w)).strftime("%d %b") for w in range(weeks)]
    conf = max(40, round(92 - weeks * 1.6 - (len(delay) * 3) - abs(scenario.get("revenue_change_pct", 0)) * 0.2))
    return {
        "labels": labels, "inflow": [round(x, 2) for x in inflow], "outflow": outflow, "balance": balance,
        "low": lo, "high": hi, "expected_inflow": round(sum(inflow), 2), "expected_outflow": round(sum(outflow), 2),
        "ending_balance": balance[-1], "min_balance": min(balance), "opening_balance": float(s["opening_balance"]),
        "confidence": conf, "weeks": weeks, "contributors": contrib,
    }


@cached
def currency_exposure():
    exp = defaultdict(lambda: {"received": 0.0, "pending": 0.0, "received_usd": 0.0, "pending_usd": 0.0, "count": 0})
    for p in payments():
        e = exp[p["currency"]]
        e["received"] += p["amount"]
        e["received_usd"] += p["amount_usd"]
        e["count"] += 1
    for i in open_invoices():
        e = exp[i["currency"]]
        e["pending"] += i["total"]
        e["pending_usd"] += i["total_usd"]
    total = sum(v["received_usd"] for v in exp.values()) or 1
    return [{"currency": k, "symbol": db.CURRENCY_SYMBOL.get(k, ""), "rate_to_usd": db.FX_TO_USD.get(k, 1),
             "received": round(v["received"], 2), "pending": round(v["pending"], 2),
             "received_usd": round(v["received_usd"], 2), "pending_usd": round(v["pending_usd"], 2),
             "share": round(v["received_usd"] / total * 100, 1), "count": v["count"]}
            for k, v in sorted(exp.items(), key=lambda kv: -kv[1]["received_usd"])]


# --------------------------------------------------------------------------- what-if

WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "a": 1, "an": 1, "couple": 2, "few": 3}


def _num(tok):
    tok = tok.lower()
    return float(tok) if re.match(r"^\d+(\.\d+)?$", tok) else WORD_NUM.get(tok)


def parse_scenario(text):
    """Turn a natural-language what-if into model variables + the assumptions we made."""
    t = text.lower()
    sc, assumptions = {}, []
    custs = customer_stats()
    target = None
    for c in custs:
        first = c["name"].lower().split()[0]
        if c["name"].lower() in t or re.search(rf"\b{re.escape(first)}\b", t):
            target = c
    if not target and re.search(r"(largest|biggest|top|main) (client|customer)", t):
        target = custs[0]
        assumptions.append(f"“Largest client” = {target['name']} ({target['revenue_share']}% of revenue received).")
    if not target and re.search(r"(slowest|latest|worst) (client|customer|payer)", t):
        target = max(custs, key=lambda c: c["avg_days_late"])
        assumptions.append(f"“Slowest payer” = {target['name']} (avg {target['avg_days_late']} days late).")
    m = re.search(r"(\d+|one|two|three|four|five|six|a|an|couple|few)\s*(day|days|week|weeks|month|months)\s*(late|delay|later)?", t)
    if target and (m and re.search(r"late|delay|later|postpone|slip", t)):
        n = _num(m.group(1)) or 1
        unit = m.group(2)
        days = int(n * (7 if unit.startswith("week") else 30 if unit.startswith("month") else 1))
        sc["delay"] = {str(target["id"]): days}
        assumptions.append(f"All open and future payments from {target['name']} shift {days} days later.")
    m = re.search(r"revenue\s*(drops|decreases|falls|declines|goes down|shrinks|increases|grows|rises|goes up)\s*(by)?\s*(\d+)\s*%", t) \
        or re.search(r"(\d+)\s*%\s*(drop|decrease|fall|decline|increase|growth|rise)\s*(in)?\s*revenue", t)
    if m:
        g = m.groups()
        pct = float(g[2] if len(g) == 3 and g[2] and g[2].isdigit() else g[0])
        neg = any(w in m.group(0) for w in ("drop", "decrease", "fall", "decline", "down", "shrink"))
        sc["revenue_change_pct"] = -pct if neg else pct
        assumptions.append(f"New-business run-rate changes by {sc['revenue_change_pct']:+.0f}%; already-issued invoices are unaffected.")
    m = re.search(r"(\d+|one|two|three|four|five|six|a|an|couple|few)\s*(more|additional|new|extra)\s*(clients|customers|client|customer)", t)
    if m:
        sc["new_clients"] = int(_num(m.group(1)) or 1)
        mv = re.search(r"\$\s?([\d,]+)", t)
        if mv:
            sc["new_client_value"] = float(mv.group(1).replace(",", ""))
        avg = sc.get("new_client_value") or round(statistics.mean([i["total_usd"] for i in invoices()]))
        assumptions.append(f"{sc['new_clients']} new client(s) at ~${avg:,.0f}/month, first payment ~5 weeks out, 75% realisation.")
    m = re.search(r"expenses?\s*(increase|rise|grow|go up|drop|decrease|fall)\s*(by)?\s*(\d+)\s*%", t) or \
        re.search(r"(\d+)\s*%\s*(more|higher|less|lower)\s*expenses?", t)
    if m:
        g = m.groups()
        pct = float(g[2] if len(g) == 3 and g[2] and g[2].isdigit() else g[0])
        neg = any(w in m.group(0) for w in ("drop", "decrease", "fall", "less", "lower"))
        sc["expense_change_pct"] = -pct if neg else pct
        assumptions.append(f"Monthly operating expenses change by {sc['expense_change_pct']:+.0f}%.")
    elif re.search(r"expenses?\s*(increase|rise|go up)", t):
        sc["expense_change_pct"] = 15
        assumptions.append("No percentage given — assumed a 15% rise in operating expenses.")
    m = re.search(r"\b(eur|euro|gbp|pound|inr|rupee|cad|aud)s?\b.*?(drops|falls|weakens|rises|strengthens|gains)\s*(by)?\s*(\d+)\s*%", t)
    if m:
        cur = {"euro": "EUR", "pound": "GBP", "rupee": "INR"}.get(m.group(1), m.group(1).upper())
        pct = float(m.group(4)) * (-1 if m.group(2) in ("drops", "falls", "weakens") else 1)
        sc["fx"] = {cur: pct}
        assumptions.append(f"{cur}/USD moves {pct:+.0f}%; all {cur}-denominated receivables revalue accordingly.")
    if not sc:
        assumptions.append("I couldn't map that to a model variable. Try: “What if Acme pays 2 weeks late?”, "
                           "“revenue drops 20%”, “3 new clients”, “expenses increase 10%”, “EUR falls 8%”.")
    return sc, assumptions


def simulate(text=None, scenario=None, days=90):
    assumptions = []
    if text:
        scenario, assumptions = parse_scenario(text)
    scenario = scenario or {}
    base = forecast(days)
    alt = forecast(days, scenario)
    delta_end = round(alt["ending_balance"] - base["ending_balance"], 2)
    delta_in = round(alt["expected_inflow"] - base["expected_inflow"], 2)
    s = db.get_settings()
    monthly = float(s["monthly_expenses"]) * (1 + scenario.get("expense_change_pct", 0) / 100)
    runway_months = alt["min_balance"] / monthly if monthly else 0
    lowest_week = alt["balance"].index(alt["min_balance"])
    narrative = []
    if scenario:
        direction = "lower" if delta_end < 0 else "higher"
        narrative.append(f"Ending balance in {days} days would be ${abs(delta_end):,.0f} {direction} "
                         f"(${alt['ending_balance']:,.0f} vs ${base['ending_balance']:,.0f}).")
        narrative.append(f"Lowest projected balance: ${alt['min_balance']:,.0f} in the week of {alt['labels'][lowest_week]} "
                         f"— about {runway_months:.1f} months of operating expenses.")
        if alt["min_balance"] < monthly:
            narrative.append("⚠ Balance dips below one month of expenses. Consider collecting overdue invoices "
                             "or requesting deposits on new work.")
        elif delta_end < 0:
            narrative.append("Your cash position stays positive throughout; the impact is manageable.")
        narrative.append(f"Forecast confidence: {alt['confidence']}% (lower for longer horizons and larger assumptions).")
    return {"scenario": scenario, "assumptions": assumptions, "baseline": base, "result": alt,
            "delta_ending_balance": delta_end, "delta_inflow": delta_in, "narrative": narrative}


# --------------------------------------------------------------------------- health score

@cached
def health():
    invs = invoices()
    custs = customer_stats()
    paid = [i for i in invs if i["status"] == "paid" and i["paid_date"]]
    recent = [i for i in paid if _d(i["paid_date"]) > TODAY() - timedelta(days=180)]
    on_time = sum(1 for i in recent if _d(i["paid_date"]) <= _d(i["due_date"]) + timedelta(days=2))
    collection = (on_time / len(recent) * 100) if recent else 100
    pend = [i for i in invs if i["status_view"] in ("sent", "overdue")]
    rev90 = rolling_revenue(90) or 1
    overdue_amt = sum(i["total_usd"] for i in pend if i["status_view"] == "overdue")
    outstanding_ratio = overdue_amt / rev90 * 100
    outstanding_score = max(0, 100 - outstanding_ratio * 2.2)
    series = revenue_series("monthly", 7)["values"][:-1]  # complete months only
    cv = statistics.pstdev(series) / statistics.mean(series) if series and statistics.mean(series) else 1
    consistency = max(0, 100 - cv * 160)
    shares = [c["revenue_share"] for c in custs]
    top = max(shares) if shares else 100
    hhi = sum((s / 100) ** 2 for s in shares)
    concentration = max(0, 100 - max(0, top - 15) * 2.4)
    fc = forecast(90)
    monthly = float(db.get_settings()["monthly_expenses"]) or 1
    cover = fc["min_balance"] / monthly
    cashflow = max(0, min(100, cover * 33))
    late = [(_d(i["paid_date"]) - _d(i["due_date"])).days for i in recent]
    avg_late = statistics.mean(late) if late else 0
    delays = max(0, 100 - max(0, avg_late) * 6)

    def lab(v):
        return ("Strong", "good") if v >= 75 else ("Moderate", "ok") if v >= 55 else ("Needs attention", "warn") if v >= 35 else ("At risk", "bad")

    comps = [
        ("Invoice collection", collection, 0.22, f"{collection:.0f}% of invoices in the last 6 months were paid within 2 days of due."),
        ("Outstanding payments", outstanding_score, 0.18, f"Overdue balance is ${overdue_amt:,.0f} — {outstanding_ratio:.0f}% of the last 90 days' revenue."),
        ("Revenue consistency", consistency, 0.16, f"Monthly revenue varies by ±{cv * 100:.0f}% (coefficient of variation, last 6 months)."),
        ("Customer concentration", concentration, 0.14, f"Largest client is {top:.0f}% of revenue (HHI {hhi:.2f})."),
        ("Cash-flow stability", cashflow, 0.18, f"Lowest projected balance covers {cover:.1f} months of expenses."),
        ("Payment delays", delays, 0.12, f"Paid invoices arrive {avg_late:.1f} days after due on average."),
    ]
    score = round(sum(v * w for _, v, w, _ in comps))
    return {
        "score": score, "label": lab(score)[0], "tone": lab(score)[1],
        "components": [{"name": n, "score": round(v), "weight": w, "label": lab(v)[0], "tone": lab(v)[1], "why": why}
                       for n, v, w, why in comps],
        "disclaimer": "Operational indicator computed from your own invoice and payment records. "
                      "Not a credit rating or a guarantee of financial health.",
    }


# --------------------------------------------------------------------------- leak detector

@cached
def leaks():
    today = TODAY()
    invs = invoices()
    found = []
    pays_by_inv = defaultdict(list)
    for p in payments():
        if p["invoice_id"]:
            pays_by_inv[p["invoice_id"]].append(p)
    # 1) payment received, invoice still open
    for i in invs:
        if i["status_view"] in ("sent", "overdue") and pays_by_inv.get(i["id"]):
            p = pays_by_inv[i["id"]][0]
            found.append({"type": "unreconciled", "severity": "high", "invoice": i["number"], "invoice_id": i["id"],
                          "amount_usd": i["total_usd"],
                          "title": f"{i['number']} was paid but is still marked unpaid",
                          "detail": f"Payment {p['reference']} for {i['currency']} {p['amount']:,.2f} arrived {p['date']} "
                                    f"from {i['customer']}. Mark the invoice as paid to keep reports accurate.",
                          "fix": "mark_paid"})
    # 2) amount mismatch on paid invoices
    for i in invs:
        if i["status"] == "paid" and pays_by_inv.get(i["id"]):
            got = sum(p["amount"] for p in pays_by_inv[i["id"]])
            if abs(got - i["total"]) > max(1, i["total"] * 0.01):
                gap = i["total"] - got
                found.append({"type": "discrepancy", "severity": "high", "invoice": i["number"], "invoice_id": i["id"],
                              "amount_usd": db.to_usd(gap, i["currency"]),
                              "title": f"{i['number']} short-paid by {i['currency']} {gap:,.2f}",
                              "detail": f"Invoiced {i['total']:,.2f} but received {got:,.2f} from {i['customer']}. "
                                        f"Request the balance or issue a credit note.",
                              "fix": "remind"})
    # 3) duplicates: same customer + same total within 7 days
    seen = defaultdict(list)
    for i in invs:
        seen[(i["customer_id"], round(i["total"], 2))].append(i)
    for group in seen.values():
        group = sorted(group, key=lambda x: x["issue_date"])
        for a, b in zip(group, group[1:]):
            if abs((_d(b["issue_date"]) - _d(a["issue_date"])).days) <= 7:
                found.append({"type": "duplicate", "severity": "medium", "invoice": b["number"], "invoice_id": b["id"],
                              "amount_usd": b["total_usd"],
                              "title": f"Possible duplicate: {a['number']} and {b['number']}",
                              "detail": f"Both bill {a['customer']} {a['currency']} {a['total']:,.2f}, issued "
                                        f"{a['issue_date']} and {b['issue_date']}. Void one if it was sent twice.",
                              "fix": "void"})
    # 4) missed follow-ups
    for i in invs:
        if i["status_view"] == "overdue" and i["days_overdue"] >= 7 and not pays_by_inv.get(i["id"]):
            last = _d(i["last_reminder"]) if i["last_reminder"] else None
            if not last or (today - last).days > 7:
                found.append({"type": "missed_followup", "severity": "medium", "invoice": i["number"], "invoice_id": i["id"],
                              "amount_usd": i["total_usd"],
                              "title": f"No recent follow-up on {i['number']} ({i['days_overdue']} days overdue)",
                              "detail": f"{i['customer']} owes {i['currency']} {i['total']:,.2f}. "
                                        + (f"Last reminder {last}." if last else "No reminder has been sent."),
                              "fix": "remind"})
    # 5) unusual monthly swings
    s = revenue_series("monthly", 6)
    for k in range(1, len(s["values"]) - 1):  # skip current partial month
        a, b = s["values"][k - 1], s["values"][k]
        if a and abs(b - a) / a > 0.35:
            found.append({"type": "fluctuation", "severity": "low", "invoice": None, "invoice_id": None,
                          "amount_usd": round(b - a, 2),
                          "title": f"Revenue {'jumped' if b > a else 'fell'} {abs(b - a) / a * 100:.0f}% in {s['labels'][k]}",
                          "detail": f"${a:,.0f} → ${b:,.0f}. Check whether this reflects real demand or timing of large payments.",
                          "fix": None})
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(found, key=lambda f: (order[f["severity"]], -abs(f["amount_usd"] or 0)))


# --------------------------------------------------------------------------- proactive agent

def scan_alerts():
    """Proactive monitoring pass. Returns candidate alerts (dedup handled by caller via `key`)."""
    today = TODAY()
    out = []
    for r in at_risk():
        if r["status_view"] == "overdue":
            out.append({"key": f"overdue:{r['number']}:{r['days_overdue'] // 7}", "severity": "high" if r["days_overdue"] > 14 else "medium",
                        "title": f"Invoice {r['number']} from {r['customer']} is {r['days_overdue']} days overdue",
                        "detail": f"{r['currency']} {r['total']:,.2f} outstanding. {r['risk']['suggested_action']}",
                        "action": "remind", "target": str(r["id"])})
    due_soon = [i for i in open_invoices() if i["status_view"] == "sent" and 0 <= (i["days_to_due"] or 99) <= 7]
    if due_soon:
        out.append({"key": f"due_soon:{today.isocalendar()[1]}:{len(due_soon)}", "severity": "low",
                    "title": f"{len(due_soon)} invoice(s) approaching their due dates",
                    "detail": ", ".join(f"{i['number']} ({i['customer']}, {i['days_to_due']}d)" for i in due_soon[:5]),
                    "action": "invoices", "target": ""})
    fc = forecast(30)
    last30, prev30 = rolling_revenue(30), rolling_revenue(30, 30)
    if prev30:
        ch = (last30 - prev30) / prev30 * 100
        if ch >= 10:
            out.append({"key": f"rev_up:{_month_key(today)}", "severity": "good",
                        "title": f"Revenue up {ch:.0f}% vs the previous 30 days",
                        "detail": f"${last30:,.0f} received in the last 30 days vs ${prev30:,.0f} before.",
                        "action": "overview", "target": ""})
        elif ch <= -10:
            out.append({"key": f"rev_down:{_month_key(today)}", "severity": "medium",
                        "title": f"Revenue down {abs(ch):.0f}% vs the previous 30 days",
                        "detail": f"${last30:,.0f} vs ${prev30:,.0f}. Ask NEXA “Explain my revenue decline” for a breakdown.",
                        "action": "ask", "target": "Explain my revenue decline"})
    monthly = float(db.get_settings()["monthly_expenses"])
    if fc["min_balance"] < monthly:
        out.append({"key": f"cash_low:{today.isocalendar()[1]}", "severity": "high",
                    "title": "Projected balance dips below one month of expenses",
                    "detail": f"Lowest point ${fc['min_balance']:,.0f} in the next 30 days.", "action": "cashflow", "target": ""})
    for c in customer_stats():
        if c["trend"] == "slowing" and c["pending_invoices"]:
            out.append({"key": f"slowing:{c['id']}:{_month_key(today)}", "severity": "medium",
                        "title": f"{c['name']} is paying slower than before",
                        "detail": f"Average lateness rose by {c['trend_delta']:.0f} days over the last 4 months. "
                                  f"Consider shorter terms or a deposit.", "action": "customers", "target": str(c["id"])})
    for l in leaks():
        if l["type"] in ("unreconciled", "discrepancy", "duplicate"):
            out.append({"key": f"leak:{l['type']}:{l['invoice']}", "severity": l["severity"], "title": l["title"],
                        "detail": l["detail"], "action": "insights", "target": ""})
    return out


def run_agent():
    now = datetime.now().isoformat(timespec="seconds")
    cands = scan_alerts()
    existing = {r["key"] for r in db.query("SELECT key FROM alerts")}
    new = 0
    for a in cands:
        if a["key"] not in existing:
            db.execute("""INSERT INTO alerts(key, severity, title, detail, action, target, created_at)
                          VALUES(?,?,?,?,?,?,?)""",
                       (a["key"], a["severity"], a["title"], a["detail"], a["action"], a["target"], now))
            new += 1
    db.execute("INSERT INTO agent_runs(ran_at, new_alerts, checked) VALUES(?,?,?)", (now, new, len(cands)))
    return new


# --------------------------------------------------------------------------- recommendations

@cached
def recommendations():
    recs = []
    risk = at_risk()
    hi = [r for r in risk if r["risk"]["level"] == "high"]
    if hi:
        tot = sum(r["total_usd"] for r in hi)
        recs.append({"id": "high-risk", "priority": 1, "icon": "alert",
                     "title": f"{len(hi)} invoice(s) are likely to be delayed",
                     "body": f"${tot:,.0f} is at high risk based on historical payment patterns. Sending reminders now "
                             f"could improve your projected cash flow.",
                     "evidence": [{"label": f"{r['number']} · {r['customer']}", "value": f"${r['total_usd']:,.0f}",
                                   "note": r["risk"]["factors"][0]["why"]} for r in hi[:5]],
                     "action": {"type": "goto", "to": "alerts", "label": "Open Recovery Assistant"}})
    lk = [l for l in leaks() if l["type"] in ("unreconciled", "discrepancy", "duplicate")]
    if lk:
        recs.append({"id": "leaks", "priority": 2, "icon": "leak",
                     "title": f"{len(lk)} record issue(s) may be hiding revenue",
                     "body": "Payments and invoices don't line up in a few places. Reconciling them keeps reports accurate.",
                     "evidence": [{"label": l["title"], "value": f"${abs(l['amount_usd']):,.0f}", "note": l["detail"]} for l in lk],
                     "action": {"type": "goto", "to": "insights", "label": "Review in Leak Detector"}})
    custs = customer_stats()
    slow = [c for c in custs if c["tone"] in ("warn", "bad") and c["pending_invoices"]]
    if slow:
        recs.append({"id": "terms", "priority": 3, "icon": "clock",
                     "title": f"Shorten payment terms for {len(slow)} slow-paying client(s)",
                     "body": "These clients regularly pay well after the due date. Net-7 terms or a 30% deposit reduce exposure.",
                     "evidence": [{"label": c["name"], "value": f"{c['avg_days_late']}d late avg",
                                   "note": f"On-time rate {c['on_time_rate']}% · {c['pending_invoices']} pending"} for c in slow],
                     "action": {"type": "goto", "to": "customers", "label": "View customer intelligence"}})
    top = custs[0] if custs else None
    if top and top["revenue_share"] > 30:
        recs.append({"id": "concentration", "priority": 4, "icon": "pie",
                     "title": f"{top['name']} drives {top['revenue_share']:.0f}% of your revenue",
                     "body": "High dependence on one client increases cash-flow risk. Simulate what happens if they pay late.",
                     "evidence": [{"label": c["name"], "value": f"{c['revenue_share']}%", "note": f"${c['revenue_usd']:,.0f} received"} for c in custs[:4]],
                     "action": {"type": "simulate", "to": "cashflow", "label": "Simulate a delay",
                                "text": f"What if {top['name'].split()[0]} pays 2 weeks late?"}})
    return recs
