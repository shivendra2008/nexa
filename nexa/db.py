"""SQLite storage and deterministic demo-data seeding for NEXA."""
import os
import random
import sqlite3
import threading
from datetime import date, datetime, timedelta

DB_PATH = os.environ.get("NEXA_DB", os.path.join(os.path.dirname(__file__), "..", "data", "nexa.db"))
_lock = threading.RLock()

# Reference FX rates to USD (demo values; replace with a live rates provider in production).
FX_TO_USD = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "INR": 0.012, "CAD": 0.73, "AUD": 0.66, "JPY": 0.0067}
CURRENCY_SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "CAD": "C$", "AUD": "A$", "JPY": "¥"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT, country TEXT, currency TEXT DEFAULT 'USD',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY, number TEXT UNIQUE, customer_id INTEGER REFERENCES customers(id),
    description TEXT, subtotal REAL, tax_rate REAL DEFAULT 0, discount REAL DEFAULT 0, total REAL,
    currency TEXT DEFAULT 'USD', issue_date TEXT, due_date TEXT, status TEXT, paid_date TEXT,
    paypal_invoice_id TEXT, paypal_order_id TEXT, terms TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY, invoice_id INTEGER, customer_id INTEGER, kind TEXT, amount REAL, currency TEXT,
    amount_usd REAL, date TEXT, reference TEXT, status TEXT, source TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY, invoice_id INTEGER, tone TEXT, subject TEXT, body TEXT, status TEXT,
    created_at TEXT, sent_at TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY, key TEXT UNIQUE, severity TEXT, title TEXT, detail TEXT, action TEXT,
    target TEXT, created_at TEXT, dismissed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS agent_runs (id INTEGER PRIMARY KEY, ran_at TEXT, new_alerts INTEGER, checked INTEGER);
"""

DEFAULT_SETTINGS = {
    "business_name": "Nova Studio",
    "owner_name": "Alex",
    "base_currency": "USD",
    "monthly_expenses": "6200",
    "opening_balance": "18500",
    "default_terms_days": "14",
}


def connect():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def query(sql, args=(), one=False):
    with _lock:
        conn = connect()
        try:
            rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
        finally:
            conn.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    with _lock:
        conn = connect()
        try:
            cur = conn.execute(sql, args)
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()


def get_settings():
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: r["value"] for r in query("SELECT key, value FROM settings")})
    return s


def set_setting(key, value):
    execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)))


def to_usd(amount, currency):
    return round(amount * FX_TO_USD.get(currency, 1.0), 2)


def next_invoice_number():
    row = query("SELECT number FROM invoices ORDER BY id DESC LIMIT 1", one=True)
    n = int(row["number"].split("-")[-1]) + 1 if row else 1001
    return f"NX-{n}"


# --------------------------------------------------------------------------- seeding

# (name, email, country, currency, avg_value, cadence_days, lateness_mean, lateness_sd, terms)
CUSTOMER_PROFILES = [
    ("Acme Robotics", "ap@acmerobotics.io", "US", "USD", 4200, 30, -1, 2, 14),
    ("Bluewave Media", "finance@bluewave.co", "US", "USD", 1800, 21, 14, 6, 14),
    ("Lumen Health", "billing@lumenhealth.com", "US", "USD", 3100, 35, 3, 3, 30),
    ("Kestrel GmbH", "rechnung@kestrel.de", "DE", "EUR", 2600, 45, 6, 4, 30),
    ("Orbit Labs", "pay@orbitlabs.ai", "GB", "GBP", 2200, 28, 22, 9, 14),
    ("Sundial Coffee", "owner@sundialcoffee.com", "CA", "CAD", 900, 30, 1, 2, 7),
    ("Pixelcraft India", "accounts@pixelcraft.in", "IN", "INR", 95000, 40, 9, 5, 14),
    ("Harbor & Pine", "hello@harborpine.com", "AU", "AUD", 1500, 60, 0, 1, 14),
]

SERVICES = [
    "Website design & build", "Brand identity package", "Monthly retainer — product design",
    "Landing page sprint", "UX audit & recommendations", "Mobile app UI design",
    "Content strategy workshop", "Marketing site maintenance", "Design system setup",
    "Pitch deck design", "SEO & performance optimisation", "E-commerce storefront setup",
]


def seed(force=False):
    with _lock:
        conn = connect()
        conn.executescript(SCHEMA)
        has = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        if has and not force:
            conn.close()
            return
        for t in ("transactions", "reminders", "invoices", "customers", "alerts", "agent_runs", "settings"):
            conn.execute(f"DELETE FROM {t}")
        rng = random.Random(42)
        today = date.today()
        start = today - timedelta(days=365)
        num = 1001
        now = datetime.now().isoformat(timespec="seconds")

        for (name, email, country, cur, avg_val, cadence, late_mu, late_sd, terms) in CUSTOMER_PROFILES:
            cid = conn.execute(
                "INSERT INTO customers(name, email, country, currency, created_at) VALUES(?,?,?,?,?)",
                (name, email, country, cur, start.isoformat())).lastrowid
            d = start + timedelta(days=rng.randint(0, 20))
            # Orbit Labs is a growing late-payer; Bluewave's volume is declining recently.
            while d < today - timedelta(days=2):
                value = avg_val * rng.uniform(0.7, 1.35)
                if name == "Bluewave Media" and d > today - timedelta(days=90):
                    value *= 0.55
                if name == "Acme Robotics" and d > today - timedelta(days=120):
                    value *= 1.25
                subtotal = round(value, 0 if cur in ("INR", "JPY") else 2)
                tax_rate = 0.0 if country in ("US",) else (19.0 if country == "DE" else (18.0 if country == "IN" else 0.0))
                total = round(subtotal * (1 + tax_rate / 100), 2)
                due = d + timedelta(days=terms)
                lateness = int(round(rng.gauss(late_mu, late_sd)))
                if name == "Orbit Labs" and d > today - timedelta(days=120):
                    lateness += 10
                paid = due + timedelta(days=lateness)
                if paid < d:
                    paid = d + timedelta(days=1)
                status, paid_date = ("paid", paid.isoformat()) if paid <= today else ("sent", None)
                number = f"NX-{num}"
                num += 1
                inv_id = conn.execute(
                    """INSERT INTO invoices(number, customer_id, description, subtotal, tax_rate, discount, total,
                       currency, issue_date, due_date, status, paid_date, terms, created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (number, cid, rng.choice(SERVICES), subtotal, tax_rate, 0, total, cur, d.isoformat(),
                     due.isoformat(), status, paid_date, f"Net {terms}", now)).lastrowid
                if status == "paid":
                    conn.execute(
                        """INSERT INTO transactions(invoice_id, customer_id, kind, amount, currency, amount_usd, date,
                           reference, status, source) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (inv_id, cid, "payment", total, cur, to_usd(total, cur), paid_date,
                         f"PAYID-{rng.randrange(16**10):010X}", "completed", "paypal"))
                    fee = round(total * 0.0349 + (0.49 if cur == "USD" else 0.39), 2)
                    conn.execute(
                        """INSERT INTO transactions(invoice_id, customer_id, kind, amount, currency, amount_usd, date,
                           reference, status, source, note) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (inv_id, cid, "fee", -fee, cur, -to_usd(fee, cur), paid_date,
                         f"FEE-{rng.randrange(16**8):08X}", "completed", "paypal", "PayPal processing fee"))
                d += timedelta(days=max(7, int(rng.gauss(cadence, cadence * 0.2))))

        # Monthly operating expenses (for cash-flow context)
        m = date(start.year, start.month, 1)
        while m <= today:
            for label, amt in (("Software subscriptions", 420), ("Contractor payout", 3800), ("Workspace rent", 1450)):
                amt_v = round(amt * rng.uniform(0.9, 1.1), 2)
                conn.execute(
                    """INSERT INTO transactions(customer_id, kind, amount, currency, amount_usd, date, reference,
                       status, source, note) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (None, "expense", -amt_v, "USD", -amt_v, (m + timedelta(days=rng.randint(1, 5))).isoformat(),
                     f"EXP-{rng.randrange(16**8):08X}", "completed", "bank", label))
            m = date(m.year + (m.month // 12), m.month % 12 + 1, 1)

        # --- intentional anomalies so the Revenue Leak Detector has real things to find ---
        acme = conn.execute("SELECT id FROM customers WHERE name='Acme Robotics'").fetchone()[0]
        bw = conn.execute("SELECT id FROM customers WHERE name='Bluewave Media'").fetchone()[0]
        lumen = conn.execute("SELECT id FROM customers WHERE name='Lumen Health'").fetchone()[0]
        # 1) Duplicate invoice: same client, same amount, 2 days apart
        d1 = today - timedelta(days=11)
        for k in (0, 2):
            conn.execute(
                """INSERT INTO invoices(number, customer_id, description, subtotal, tax_rate, discount, total, currency,
                   issue_date, due_date, status, terms, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f"NX-{num}", bw, "Social campaign creative", 1250, 0, 0, 1250, "USD",
                 (d1 + timedelta(days=k)).isoformat(), (d1 + timedelta(days=k + 14)).isoformat(), "sent", "Net 14", now))
            num += 1
        # 2) Payment received but invoice never marked paid
        d2 = today - timedelta(days=26)
        inv = conn.execute(
            """INSERT INTO invoices(number, customer_id, description, subtotal, tax_rate, discount, total, currency,
               issue_date, due_date, status, terms, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"NX-{num}", lumen, "Patient portal UX audit", 2800, 0, 0, 2800, "USD", d2.isoformat(),
             (d2 + timedelta(days=14)).isoformat(), "sent", "Net 14", now)).lastrowid
        num += 1
        conn.execute(
            """INSERT INTO transactions(invoice_id, customer_id, kind, amount, currency, amount_usd, date, reference,
               status, source) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (inv, lumen, "payment", 2800, "USD", 2800, (d2 + timedelta(days=12)).isoformat(),
             "PAYID-7F3A91C0DE", "completed", "paypal"))
        # 3) Partial payment discrepancy
        d3 = today - timedelta(days=40)
        inv = conn.execute(
            """INSERT INTO invoices(number, customer_id, description, subtotal, tax_rate, discount, total, currency,
               issue_date, due_date, status, paid_date, terms, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"NX-{num}", acme, "Robotics dashboard UI — phase 2", 5400, 0, 0, 5400, "USD", d3.isoformat(),
             (d3 + timedelta(days=14)).isoformat(), "paid", (d3 + timedelta(days=13)).isoformat(), "Net 14", now)).lastrowid
        num += 1
        conn.execute(
            """INSERT INTO transactions(invoice_id, customer_id, kind, amount, currency, amount_usd, date, reference,
               status, source) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (inv, acme, "payment", 4900, "USD", 4900, (d3 + timedelta(days=13)).isoformat(),
             "PAYID-55B20E7A11", "completed", "paypal"))
        # A reminder history entry for an older overdue invoice
        old = conn.execute(
            "SELECT id FROM invoices WHERE status='sent' AND due_date < ? ORDER BY due_date LIMIT 1",
            (today.isoformat(),)).fetchone()
        if old:
            conn.execute(
                "INSERT INTO reminders(invoice_id, tone, subject, body, status, created_at, sent_at) VALUES(?,?,?,?,?,?,?)",
                (old[0], "friendly", "Friendly reminder", "Hello! This is a friendly reminder regarding your pending invoice.",
                 "sent", (today - timedelta(days=9)).isoformat(), (today - timedelta(days=9)).isoformat()))
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (k, v))
        conn.commit()
        conn.close()
