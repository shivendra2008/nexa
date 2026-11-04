# NEXA — AI Commerce Copilot

*Your Money. Your Decisions. One Intelligent Workspace.*

A working prototype: Flask + SQLite backend with an explainable financial-intelligence engine, a
parallax landing page, a 10-screen dashboard, and a PayPal (Sandbox) checkout.

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python run.py          # → http://localhost:5050
```

- `/` — landing page (parallax hero, starfield, sticky horizontal features, live What-If teaser)
- `/app` — Command Center (Overview, Transactions, Invoices, AI Insights, Cash Flow, Customers, Smart Alerts, Ask NEXA, Reports, Settings)
- `/pay/<invoice>` — PayPal checkout for a client, e.g. `/pay/NX-1062`

The first start seeds 12 months of realistic demo data (8 clients, 6 currencies, with deliberate
anomalies for the leak detector). Settings → *Reset demo data* regenerates it.

## Deploy to Vercel

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/shivendra2008/nexa)

`api/index.py` exposes the Flask app as a Python serverless function and `vercel.json` routes every
path to it. On Vercel the SQLite demo DB lives in `/tmp` and is re-seeded on each cold start, and the
proactive agent scans on demand (when alerts are fetched) instead of on a background thread. Separate
function instances don't share data, so changes such as a payment may not appear on every request;
use a hosted database for anything beyond a demo.

## Deploy to Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/shivendra2008/nexa)

`render.yaml` defines a free Python web service (gunicorn, Python 3.12). PayPal and Anthropic keys
are optional and prompted for at deploy time. The free plan's disk is ephemeral, so demo data is
re-seeded whenever the service restarts, and the service sleeps after ~15 minutes idle.

## Modes

| Variable | Effect |
|---|---|
| `PAYPAL_CLIENT_ID` + `PAYPAL_CLIENT_SECRET` | Real PayPal **Sandbox**: JS SDK buttons, Orders v2 create/capture, Invoicing v2 create/send. Without them, **demo mode** simulates the same flow locally. |
| `ANTHROPIC_API_KEY` (+ `pip install anthropic`) | Ask NEXA answers are rephrased by Claude (`claude-opus-5-5`) from grounded facts. Without it, the deterministic engine answers directly. |

## Architecture

```
nexa/
  db.py         SQLite schema, deterministic seed, FX reference rates
  engine.py     risk scoring (explainable factors), customer behaviour, revenue series,
                risk-weighted cash-flow forecast + confidence bands, What-If parser/simulator,
                health indicator, revenue-leak detector, proactive agent scan, recommendations
  assistant.py  Ask NEXA intent router (grounded), NL invoice parser, reminder copywriter
  reports.py    daily / weekly / monthly / outstanding / customer / cash-flow reports + CSV
  paypal.py     PayPal REST client (sandbox) with demo-mode simulation
  app.py        Flask routes, approval guards, capture verification, background agent thread
templates/ static/   landing page, dashboard SPA (vanilla JS + Chart.js), checkout
```

Safety rails: invoices require `approved: true`, reminders require `confirm: true`, and PayPal
captures are verified server-side (amount + currency) before an invoice is marked paid. Reminder
email delivery is simulated (logged to history). The health score is an operational indicator,
not a credit rating.
