"""AI Financial Report Generator — builds structured reports from stored records."""
import csv
import io
import statistics
from collections import defaultdict
from datetime import date, timedelta

from . import db, engine


def _period(kind, month=None):
    today = date.today()
    if kind == "daily":
        return today, today, "Today, " + today.strftime("%d %b %Y")
    if kind == "weekly":
        s = today - timedelta(days=6)
        return s, today, f"{s.strftime('%d %b')} – {today.strftime('%d %b %Y')}"
    if month:
        y, m = map(int, month.split("-"))
        s = date(y, m, 1)
    elif today.day < 7:  # early in the month → report on the last complete month
        s = engine._add_months(date(today.year, today.month, 1), -1)
    else:
        s = date(today.year, today.month, 1)
    e = min(engine._add_months(s, 1) - timedelta(days=1), today)
    return s, e, s.strftime("%B %Y")


def build(kind="monthly", month=None):
    if kind in ("outstanding", "customers", "cashflow"):
        return _special(kind)
    s, e, label = _period(kind, month)
    span = (e - s).days + 1
    ps, pe = s - timedelta(days=span), s - timedelta(days=1)
    tx = engine.transactions()
    in_range = lambda d: s.isoformat() <= d[:10] <= e.isoformat()
    in_prev = lambda d: ps.isoformat() <= d[:10] <= pe.isoformat()
    pays = [t for t in tx if t["kind"] == "payment" and in_range(t["date"])]
    prev = sum(t["amount_usd"] for t in tx if t["kind"] == "payment" and in_prev(t["date"]))
    fees = -sum(t["amount_usd"] for t in tx if t["kind"] == "fee" and in_range(t["date"]))
    expenses = -sum(t["amount_usd"] for t in tx if t["kind"] == "expense" and in_range(t["date"]))
    revenue = sum(p["amount_usd"] for p in pays)
    invs = engine.invoices()
    issued = [i for i in invs if in_range(i["issue_date"])]
    outstanding = [i for i in invs if i["status_view"] in ("sent", "overdue")]
    paid_in = [i for i in invs if i["paid_date"] and in_range(i["paid_date"])]
    days = [(engine._d(i["paid_date"]) - engine._d(i["issue_date"])).days for i in paid_in]
    by_c = defaultdict(float)
    for p in pays:
        by_c[p["customer"]] += p["amount_usd"]
    contrib = sorted(by_c.items(), key=lambda kv: -kv[1])
    growth = ((revenue - prev) / prev * 100) if prev else None
    obs = []
    if growth is not None:
        obs.append(f"Revenue {'grew' if growth >= 0 else 'declined'} {abs(growth):.0f}% vs the previous {span}-day period (${prev:,.0f}).")
    if contrib:
        top, val = contrib[0]
        obs.append(f"{top} was the largest contributor at ${val:,.0f} ({val / revenue * 100:.0f}% of the period).")
    if days:
        obs.append(f"Invoices paid this period took {statistics.mean(days):.1f} days on average from issue to payment.")
    od = [i for i in outstanding if i["status_view"] == "overdue"]
    if od:
        obs.append(f"{len(od)} invoice(s) are overdue, totalling ${sum(i['total_usd'] for i in od):,.0f}.")
    if fees:
        obs.append(f"PayPal processing fees were ${fees:,.0f} ({fees / revenue * 100 if revenue else 0:.1f}% of revenue).")
    net = revenue - fees - expenses
    obs.append(f"Net cash after fees and operating expenses: {'+' if net >= 0 else '−'}${abs(net):,.0f}.")
    return {
        "kind": kind, "title": f"{kind.capitalize()} financial report", "period": label,
        "business": db.get_settings()["business_name"], "generated": date.today().isoformat(),
        "metrics": [
            {"label": "Revenue received", "value": revenue, "fmt": "usd"},
            {"label": "Growth vs prior period", "value": growth, "fmt": "pct"},
            {"label": "Invoices issued", "value": len(issued), "fmt": "int"},
            {"label": "Outstanding (all)", "value": sum(i["total_usd"] for i in outstanding), "fmt": "usd"},
            {"label": "PayPal fees", "value": fees, "fmt": "usd"},
            {"label": "Operating expenses", "value": expenses, "fmt": "usd"},
        ],
        "contribution": [{"customer": k, "usd": round(v, 2), "share": round(v / revenue * 100, 1) if revenue else 0} for k, v in contrib],
        "observations": obs,
        "table": {"columns": ["Date", "Customer", "Invoice", "Currency", "Amount", "USD"],
                  "rows": [[p["date"], p["customer"], p["invoice_number"], p["currency"], round(p["amount"], 2), round(p["amount_usd"], 2)] for p in pays]},
    }


def _special(kind):
    today = date.today().isoformat()
    biz = db.get_settings()["business_name"]
    if kind == "outstanding":
        rows = engine.at_risk()
        tot = sum(r["total_usd"] for r in rows)
        od = [r for r in rows if r["status_view"] == "overdue"]
        return {"kind": kind, "title": "Outstanding payments report", "period": f"As of {today}", "business": biz, "generated": today,
                "metrics": [{"label": "Open invoices", "value": len(rows), "fmt": "int"},
                            {"label": "Outstanding", "value": tot, "fmt": "usd"},
                            {"label": "Overdue", "value": sum(r["total_usd"] for r in od), "fmt": "usd"},
                            {"label": "High risk", "value": sum(1 for r in rows if r["risk"]["level"] == "high"), "fmt": "int"}],
                "contribution": [], "observations": [f"{r['number']} ({r['customer']}): {r['risk']['factors'][0]['why']}" for r in rows[:5]],
                "table": {"columns": ["Invoice", "Customer", "Due", "Days overdue", "Currency", "Amount", "Risk"],
                          "rows": [[r["number"], r["customer"], r["due_date"], r["days_overdue"], r["currency"], r["total"],
                                    f"{r['risk']['level']} ({r['risk']['score']})"] for r in rows]}}
    if kind == "customers":
        cs = engine.customer_stats()
        return {"kind": kind, "title": "Customer revenue report", "period": "Last 12 months", "business": biz, "generated": today,
                "metrics": [{"label": "Active clients", "value": len(cs), "fmt": "int"},
                            {"label": "Revenue received", "value": sum(c["revenue_usd"] for c in cs), "fmt": "usd"},
                            {"label": "Top-client share", "value": cs[0]["revenue_share"] if cs else 0, "fmt": "pct"}],
                "contribution": [{"customer": c["name"], "usd": c["revenue_usd"], "share": c["revenue_share"]} for c in cs],
                "observations": [f"{c['name']}: {c['behaviour'].lower()}, avg {c['avg_days_to_pay']} days to pay, trend {c['trend']}." for c in cs],
                "table": {"columns": ["Customer", "Currency", "Invoices", "Paid", "Pending", "Avg days to pay", "On-time %", "Revenue USD", "Outstanding USD"],
                          "rows": [[c["name"], c["currency"], c["total_invoices"], c["paid_invoices"], c["pending_invoices"], c["avg_days_to_pay"],
                                    c["on_time_rate"], c["revenue_usd"], c["outstanding_usd"]] for c in cs]}}
    fc = engine.forecast(90)
    return {"kind": kind, "title": "Cash-flow projection", "period": "Next 90 days", "business": biz, "generated": today,
            "metrics": [{"label": "Expected inflow", "value": fc["expected_inflow"], "fmt": "usd"},
                        {"label": "Expected outflow", "value": fc["expected_outflow"], "fmt": "usd"},
                        {"label": "Ending balance", "value": fc["ending_balance"], "fmt": "usd"},
                        {"label": "Confidence", "value": fc["confidence"], "fmt": "pct"}],
            "contribution": [], "observations": [
                f"Lowest projected balance ${fc['min_balance']:,.0f}.",
                "Inflows are risk-weighted by each invoice's collection probability; new business uses each client's 6-month run-rate."],
            "table": {"columns": ["Week of", "Inflow", "Outflow", "Balance", "Low", "High"],
                      "rows": [[l, i, o, b, lo, hi] for l, i, o, b, lo, hi in zip(fc["labels"], fc["inflow"], fc["outflow"], fc["balance"], fc["low"], fc["high"])]}}


def to_csv(rep):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([rep["title"], rep["period"], rep["business"]])
    w.writerow([])
    for m in rep["metrics"]:
        w.writerow([m["label"], "" if m["value"] is None else round(m["value"], 2)])
    w.writerow([])
    w.writerow(rep["table"]["columns"])
    w.writerows(rep["table"]["rows"])
    return buf.getvalue()
