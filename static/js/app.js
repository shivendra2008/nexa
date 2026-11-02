/* NEXA Command Center — single-page app (vanilla JS + Chart.js) */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const SYM = { USD: "$", EUR: "€", GBP: "£", INR: "₹", CAD: "C$", AUD: "A$", JPY: "¥" };
  const money = (v, cur = "USD", dp) => {
    if (v == null || isNaN(v)) return "—";
    const d = dp ?? (["INR", "JPY"].includes(cur) || Math.abs(v) >= 10000 ? 0 : 2);
    return (v < 0 ? "−" : "") + (SYM[cur] ?? cur + " ") + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  };
  const fdate = s => s ? new Date(s.slice(0, 10) + "T00:00:00").toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }) : "—";
  const ago = s => {
    const m = Math.round((Date.now() - new Date(s).getTime()) / 60000);
    return m < 1 ? "just now" : m < 60 ? `${m}m ago` : m < 1440 ? `${Math.round(m / 60)}h ago` : `${Math.round(m / 1440)}d ago`;
  };
  async function api(path, opts = {}) {
    const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts, body: opts.body ? JSON.stringify(opts.body) : undefined });
    const j = await r.json().catch(() => ({ ok: false, error: "Bad response" }));
    if (!j.ok) throw Object.assign(new Error(j.error || "Request failed"), { status: r.status });
    return j.data;
  }

  /* ------------------------------------------------------------------ icons & nav */
  const I = p => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
  const ROUTES = [
    ["overview", "Overview", "AI Financial Command Center", I('<rect x="3" y="3" width="7" height="9" rx="2"/><rect x="14" y="3" width="7" height="5" rx="2"/><rect x="14" y="12" width="7" height="9" rx="2"/><rect x="3" y="16" width="7" height="5" rx="2"/>')],
    ["transactions", "Transactions", "Every PayPal payment, fee and expense", I('<path d="M7 7h13l-3-3M17 17H4l3 3"/>')],
    ["invoices", "Invoices", "Smart Invoice Studio", I('<path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6M9 13h7M9 17h5"/>')],
    ["insights", "AI Insights", "Payment intelligence & revenue leak detector", I('<path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4z"/><path d="M19 17l.8 2.2L22 20l-2.2.8L19 23l-.8-2.2L16 20l2.2-.8z"/>')],
    ["cashflow", "Cash Flow", "Forecasting & What-If simulator", I('<path d="M3 17l5-5 4 4 8-8"/><path d="M14 8h6v6"/>')],
    ["customers", "Customer Intelligence", "How each client pays", I('<circle cx="9" cy="8" r="4"/><path d="M2 21c0-4 3-6 7-6s7 2 7 6"/><path d="M16 4a4 4 0 010 8M22 21c0-3-2-5-4-5.5"/>')],
    ["alerts", "Smart Alerts", "Proactive agent & payment recovery", I('<path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 01-3.4 0"/>')],
    ["ask", "Ask NEXA", "Your AI financial assistant", I('<path d="M21 12a8 8 0 01-11.6 7.1L3 21l1.9-6.4A8 8 0 1121 12z"/>')],
    ["reports", "Reports", "AI financial report generator", I('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>')],
    ["settings", "Settings", "Business, PayPal & AI configuration", I('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"/>')],
  ];
  const nav = $("#sideNav");
  nav.insertAdjacentHTML("beforeend", ROUTES.map(([id, label, , icon]) =>
    `<a class="nav-item" href="#${id}" data-route="${id}">${icon}<span>${label}</span>${id === "alerts" ? '<span class="badge" id="alertBadge"></span>' : ""}</a>`).join(""));

  /* ------------------------------------------------------------------ overlays */
  function toast(title, body = "", tone = "good") {
    const el = document.createElement("div");
    el.className = "toast";
    el.innerHTML = `<span class="sev ${tone}" style="width:10px;height:10px;border-radius:50%;margin-top:5px;flex:none"></span><div><b>${esc(title)}</b><span class="t2">${esc(body)}</span></div>`;
    $("#toasts").appendChild(el);
    setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 400); }, 5200);
  }
  function overlay(onClose) {
    const o = document.createElement("div");
    o.className = "overlay"; document.body.appendChild(o);
    requestAnimationFrame(() => o.classList.add("show"));
    o.onclick = onClose;
    return o;
  }
  function confirmBox(title, body, okLabel = "Confirm", tone = "primary") {
    return new Promise(res => {
      const m = document.createElement("div");
      m.className = "modal";
      m.innerHTML = `<h3>${esc(title)}</h3><p>${body}</p><div class="actions"><button class="btn ghost" data-no>Cancel</button><button class="btn ${tone}" data-yes>${esc(okLabel)}</button></div>`;
      const close = v => { m.classList.remove("show"); o.classList.remove("show"); setTimeout(() => { m.remove(); o.remove(); }, 400); res(v); };
      const o = overlay(() => close(false));
      document.body.appendChild(m);
      requestAnimationFrame(() => m.classList.add("show"));
      $("[data-no]", m).onclick = () => close(false);
      $("[data-yes]", m).onclick = () => close(true);
      $("[data-yes]", m).focus();
    });
  }
  let drawerEl, drawerOv;
  function drawer(html) {
    closeDrawer(true);
    drawerEl = document.createElement("aside");
    drawerEl.className = "drawer";
    drawerEl.innerHTML = `<button class="x" aria-label="Close">✕</button>${html}`;
    drawerOv = overlay(() => closeDrawer());
    document.body.appendChild(drawerEl);
    requestAnimationFrame(() => drawerEl.classList.add("show"));
    $(".x", drawerEl).onclick = () => closeDrawer();
    return drawerEl;
  }
  function closeDrawer(now) {
    if (!drawerEl) return;
    const d = drawerEl, o = drawerOv; drawerEl = drawerOv = null;
    d.classList.remove("show"); o.classList.remove("show");
    setTimeout(() => { d.remove(); o.remove(); }, now ? 0 : 500);
  }
  addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });

  /* ------------------------------------------------------------------ charts */
  let charts = [];
  if (window.Chart) {
    Chart.defaults.color = "#8B84AE";
    Chart.defaults.font.family = "Inter, system-ui, sans-serif";
    Chart.defaults.borderColor = "rgba(167,139,250,.08)";
    Chart.defaults.plugins.legend.labels.usePointStyle = true;
    Chart.defaults.plugins.tooltip.backgroundColor = "rgba(18,15,42,.95)";
    Chart.defaults.plugins.tooltip.borderColor = "rgba(167,139,250,.3)";
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.padding = 12;
    Chart.defaults.plugins.tooltip.cornerRadius = 10;
    Chart.defaults.animation.duration = 1200;
    Chart.defaults.animation.easing = "easeOutQuart";
  }
  function grad(ctx, a = "rgba(124,58,237,.55)", b = "rgba(124,58,237,0)") {
    const g = ctx.createLinearGradient(0, 0, 0, ctx.canvas.clientHeight || 300);
    g.addColorStop(0, a); g.addColorStop(1, b); return g;
  }
  function mkChart(canvas, cfg) {
    if (!window.Chart) { canvas.parentElement.innerHTML = '<div class="empty">Chart library unavailable offline.</div>'; return null; }
    const c = new Chart(canvas, cfg); charts.push(c); return c;
  }
  const usdTick = v => "$" + (Math.abs(v) >= 1000 ? (v / 1000).toFixed(0) + "k" : v);

  /* ------------------------------------------------------------------ helpers */
  function countUp(root = document) {
    $$("[data-count]", root).forEach(el => {
      const to = +el.dataset.count, fmt = el.dataset.fmt || "usd", t0 = performance.now(), dur = 1300;
      const out = v => fmt === "usd" ? money(v, "USD", Math.abs(to) >= 1000 ? 0 : 2) : fmt === "pct" ? (v >= 0 ? "+" : "") + v.toFixed(1) + "%" : fmt === "days" ? v.toFixed(1) + " days" : Math.round(v).toLocaleString();
      const step = now => { const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 4); el.textContent = out(to * e); if (p < 1) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    });
  }
  const chip = (s, label) => `<span class="chip ${esc(s)}">${esc(label ?? s)}</span>`;
  const skeleton = (n = 3, h = 120) => `<div class="grid g-3">${Array.from({ length: n }, () => `<div class="skeleton" style="height:${h}px"></div>`).join("")}</div>`;
  function spotlight(root) {
    $$(".card", root).forEach(c => c.addEventListener("pointermove", e => {
      const r = c.getBoundingClientRect();
      c.style.setProperty("--mx", e.clientX - r.left + "px"); c.style.setProperty("--my", e.clientY - r.top + "px");
    }));
  }
  function sparkSVG(vals, color = "#A78BFA") {
    const max = Math.max(...vals, 1), w = 200, h = 40;
    const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * w},${h - 3 - (v / max) * (h - 6)}`).join(" ");
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
  }

  /* ------------------------------------------------------------------ router */
  const view = $("#view");
  let META = null, pendingSim = null, pendingAsk = null, pendingRemind = null;
  const views = {};

  function moveIndicator(id) {
    const a = $(`.nav-item[data-route="${id}"]`), ind = $("#navInd");
    $$(".nav-item").forEach(n => n.classList.toggle("active", n === a));
    if (a) ind.style.transform = `translateY(${a.offsetTop}px)`;
  }
  async function route() {
    const id = (location.hash.slice(1) || "overview").split("?")[0];
    const r = ROUTES.find(x => x[0] === id) || ROUTES[0];
    charts.forEach(c => c.destroy()); charts = [];
    closeDrawer(true);
    $("#side").classList.remove("open");
    moveIndicator(r[0]);
    $("#viewTitle").textContent = r[1];
    $("#viewSub").textContent = r[2];
    document.title = `NEXA · ${r[1]}`;
    view.classList.remove("view-enter"); void view.offsetWidth; view.classList.add("view-enter");
    view.innerHTML = skeleton(6);
    $("#main").scrollTo({ top: 0 });
    try { await views[r[0]](view); spotlight(view); countUp(view); }
    catch (e) { console.error(e); view.innerHTML = `<div class="card empty">Couldn't load this view: ${esc(e.message)}</div>`; }
  }
  addEventListener("hashchange", route);
  $("#menuBtn").onclick = () => $("#side").classList.toggle("open");
  $("#askQuick").onclick = () => { location.hash = "ask"; };
  const go = (to, extra) => {
    if (extra?.simulate) pendingSim = extra.simulate;
    if (extra?.ask) pendingAsk = extra.ask;
    if (extra?.remind) pendingRemind = extra.remind;
    if (location.hash === "#" + to) route(); else location.hash = to;
  };

  /* ================================================================== OVERVIEW */
  views.overview = async el => {
    const d = await api("/api/overview");
    const s = d.summary;
    const kpis = [
      ["💰", "Total revenue received", s.total_revenue, "usd", `${money(s.revenue_last_30, "USD", 0)} in last 30 days`, ""],
      ["🧾", "Pending invoices", s.pending_total, "usd", `${s.pending_count} open · ${s.overdue_count} overdue`, s.overdue_count ? "warn-t" : ""],
      ["🌊", "Expected cash in (30d)", s.expected_30, "usd", "Risk-weighted forecast", ""],
      ["⚠️", "At-risk payments", s.at_risk_total, "usd", `${s.at_risk_count} invoice(s) flagged`, s.at_risk_count ? "down" : "up"],
      ["📈", "Revenue growth (30d)", s.growth_pct, "pct", `vs previous 30 days`, s.growth_pct >= 0 ? "up" : "down"],
      ["⏱️", "Avg payment time", s.avg_payment_days, "days", "Issue → paid, last 90 days", ""],
    ];
    el.innerHTML = `
      <div class="grid g-6 stagger">${kpis.map(([ic, l, v, f, sub, cls]) => `
        <div class="card hover kpi"><div class="label"><i>${ic}</i>${l}</div>
        <div class="value" data-count="${v}" data-fmt="${f}">0</div><div class="delta ${cls}">${sub}</div></div>`).join("")}</div>
      <div class="grid g-main stagger" style="margin-top:18px">
        <div class="card">
          <div class="card-h"><h3>Revenue analytics</h3>
            <div class="seg" id="revSeg"><button data-p="weekly">Weekly</button><button data-p="monthly" class="on">Monthly</button></div></div>
          <div class="chart-box tall"><canvas id="revChart"></canvas></div>
        </div>
        <div class="card ai-card">
          <div class="ai-head"><span class="sparkle">✦</span><div><h3 style="margin:0;font-size:15px">AI Intelligence Panel</h3><div class="muted xs">Click a recommendation for supporting data</div></div></div>
          <div id="recs">${d.recommendations.map((r, i) => `
            <div class="rec" data-rec="${i}"><b>${esc(r.title)}</b><p>${esc(r.body)}</p><span class="go">View evidence →</span></div>`).join("") || '<div class="empty">All clear — nothing needs your attention.</div>'}</div>
        </div>
      </div>
      <div class="grid g-main stagger" style="margin-top:18px">
        <div class="card"><div class="card-h"><h3>Recent activity</h3><a class="btn sm ghost" href="#transactions">All transactions →</a></div>
          <div class="table-wrap"><table><thead><tr><th>Date</th><th>Description</th><th>Type</th><th class="num">Amount</th></tr></thead><tbody>
          ${d.recent.map(t => `<tr><td>${fdate(t.date)}</td><td>${esc(t.customer || t.note || "—")}${t.invoice_number ? ` <span class="muted xs">${esc(t.invoice_number)}</span>` : ""}</td>
            <td>${chip(t.kind === "payment" ? "good" : t.kind === "fee" ? "neutral" : "warn", t.kind)}</td>
            <td class="num ${t.amount >= 0 ? "up" : ""}">${money(t.amount, t.currency)}</td></tr>`).join("")}
          </tbody></table></div></div>
        ${healthCard(d.health)}
      </div>`;
    const recs = d.recommendations;
    $$("[data-rec]", el).forEach(n => n.onclick = () => openRec(recs[+n.dataset.rec]));
    let rc;
    const draw = rev => {
      rc?.destroy(); charts = charts.filter(c => c !== rc);
      const ctx = $("#revChart").getContext("2d");
      rc = mkChart($("#revChart"), {
        data: { labels: rev.labels, datasets: [
          { type: "line", label: "Trend", data: rev.values, borderColor: "#A78BFA", backgroundColor: grad(ctx, "rgba(167,139,250,.35)"), fill: true, tension: .42, pointRadius: 0, pointHoverRadius: 6, borderWidth: 2.5, order: 1 },
          { type: "bar", label: "Revenue (USD)", data: rev.values, backgroundColor: grad(ctx, "rgba(124,58,237,.9)", "rgba(124,58,237,.2)"), borderRadius: 8, maxBarThickness: 34, order: 2 },
        ] },
        options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${money(c.raw, "USD", 0)} · ${rev.counts[c.dataIndex]} payment(s)` } } },
          scales: { y: { ticks: { callback: usdTick }, grid: { color: "rgba(167,139,250,.06)" } }, x: { grid: { display: false } } } },
      });
    };
    draw(d.revenue);
    $$("#revSeg button", el).forEach(b => b.onclick = async () => {
      $$("#revSeg button").forEach(x => x.classList.toggle("on", x === b));
      draw(await api("/api/revenue?period=" + b.dataset.p));
    });
    animateHealth(el);
  };

  function healthCard(h) {
    const col = { good: "#22C55E", ok: "#38BDF8", warn: "#F59E0B", bad: "#F43F5E" }[h.tone];
    return `<div class="card"><div class="card-h"><h3>Financial health indicator</h3>${chip(h.tone, h.label)}</div>
      <div class="health"><div class="ring"><svg viewBox="0 0 120 120"><circle class="bg" cx="60" cy="60" r="54"/><circle class="fg" cx="60" cy="60" r="54" stroke="${col}" data-p="${h.score / 100}"/></svg>
      <div class="c"><div><b data-count="${h.score}" data-fmt="int">0</b><span class="muted xs">/ 100</span></div></div></div>
      <div class="bars">${h.components.map(c => `<div class="bar-row" title="${esc(c.why)}"><span class="t2">${esc(c.name)}</span><span class="muted" style="text-align:right">${c.score}</span>
        <div class="bar"><span class="tone-${c.tone}" style="width:${c.score}%"></span></div></div>`).join("")}</div></div>
      <p class="muted xs" style="margin:14px 0 0">${esc(h.disclaimer)}</p></div>`;
  }
  function animateHealth(root) {
    setTimeout(() => $$(".ring .fg", root).forEach(c => c.style.strokeDashoffset = 339.3 * (1 - +c.dataset.p)), 80);
  }
  function openRec(r) {
    const d = drawer(`<span class="muted xs">AI recommendation · supporting data</span><h2>${esc(r.title)}</h2><p class="t2">${esc(r.body)}</p><hr class="sep">
      <div class="table-wrap"><table><thead><tr><th>Item</th><th class="num">Value</th></tr></thead><tbody>
      ${r.evidence.map(e => `<tr><td><b>${esc(e.label)}</b><div class="muted xs" style="white-space:normal">${esc(e.note)}</div></td><td class="num">${esc(e.value)}</td></tr>`).join("")}
      </tbody></table></div><div style="margin-top:20px"><button class="btn primary" id="recGo">${esc(r.action.label)} →</button></div>`);
    $("#recGo", d).onclick = () => { closeDrawer(); go(r.action.to, r.action.type === "simulate" ? { simulate: r.action.text } : null); };
  }

  /* ================================================================== TRANSACTIONS */
  views.transactions = async el => {
    el.innerHTML = `<div class="card"><div class="card-h"><div class="row">
      <input class="input" id="txQ" placeholder="Search client, reference, invoice…" style="width:300px">
      <div class="seg" id="txKind"><button data-k="" class="on">All</button><button data-k="payment">Payments</button><button data-k="fee">Fees</button><button data-k="expense">Expenses</button></div></div>
      <div class="muted xs" id="txSum"></div></div><div class="table-wrap" id="txTable">${skeleton(1, 300)}</div></div>`;
    let kind = "", q = "", t;
    const load = async () => {
      const rows = await api(`/api/transactions?kind=${kind}&q=${encodeURIComponent(q)}`);
      const sum = rows.reduce((a, r) => a + r.amount_usd, 0);
      $("#txSum").textContent = `${rows.length} transactions · net ${money(sum, "USD", 0)} (USD at reference rates)`;
      $("#txTable").innerHTML = `<table><thead><tr><th>Date</th><th>Reference</th><th>Counterparty</th><th>Invoice</th><th>Type</th><th>Source</th><th class="num">Amount</th><th class="num">USD</th></tr></thead><tbody>
        ${rows.slice(0, 400).map(r => `<tr><td>${fdate(r.date)}</td><td class="muted">${esc(r.reference)}</td><td>${esc(r.customer || r.note || "—")}</td><td>${esc(r.invoice_number || "—")}</td>
        <td>${chip(r.kind === "payment" ? "good" : r.kind === "fee" ? "neutral" : "warn", r.kind)}</td><td class="muted">${esc(r.source)}</td>
        <td class="num ${r.amount >= 0 ? "up" : ""}">${money(r.amount, r.currency)}</td><td class="num">${money(r.amount_usd, "USD")}</td></tr>`).join("")}</tbody></table>`;
    };
    $("#txQ").oninput = e => { q = e.target.value; clearTimeout(t); t = setTimeout(load, 200); };
    $$("#txKind button").forEach(b => b.onclick = () => { $$("#txKind button").forEach(x => x.classList.toggle("on", x === b)); kind = b.dataset.k; load(); });
    await load();
  };

  /* ================================================================== INVOICES (Smart Invoice Studio) */
  views.invoices = async el => {
    const [custs, invs] = await Promise.all([api("/api/customers"), api("/api/invoices")]);
    let draft = null;
    el.innerHTML = `
      <div class="studio stagger">
        <div class="card ai-card">
          <div class="ai-head" style="margin-bottom:14px"><span class="sparkle">✦</span><div><h3 style="margin:0;font-size:15px">Describe the invoice</h3><div class="muted xs">NEXA drafts it — you review and approve before anything is created or sent.</div></div></div>
          <div class="prompt-box"><textarea class="input" id="nlText" placeholder="e.g. Create an invoice for a $750 website design project, due in 14 days.">Create an invoice for a $750 website design project for Harbor & Pine, due in 14 days.</textarea>
            <button class="btn primary sm" id="genBtn">✦ Generate</button></div>
          <div class="examples">${["Bill Orbit Labs £2,400 for mobile app UI design with 20% VAT", "Invoice Kestrel €3,200 for design system setup, net 30", "Pixelcraft ₹85,000 for landing page sprint, 10% discount", "Create an invoice for a $750 website design project, due in 14 days."]
              .map(x => `<button class="ex">${esc(x)}</button>`).join("")}</div>
          <div id="draftForm" style="margin-top:18px"></div>
        </div>
        <div id="preview"><div class="card empty" style="padding:80px 20px">Your invoice preview will appear here.</div></div>
      </div>
      <div class="card" style="margin-top:18px">
        <div class="card-h"><h3>All invoices</h3><div class="seg" id="invSeg">${["all", "draft", "sent", "overdue", "paid"].map((s, i) => `<button data-s="${s}" class="${i ? "" : "on"}">${s[0].toUpperCase() + s.slice(1)}</button>`).join("")}</div></div>
        <div class="table-wrap" id="invTable"></div></div>`;

    const renderTable = (filter = "all") => {
      const rows = invs.filter(i => filter === "all" || i.status_view === filter);
      $("#invTable").innerHTML = `<table><thead><tr><th>Invoice</th><th>Client</th><th>Description</th><th>Issued</th><th>Due</th><th>Status</th><th class="num">Total</th><th></th></tr></thead><tbody>
        ${rows.map(i => `<tr><td><b>${esc(i.number)}</b></td><td>${esc(i.customer)}</td><td class="t2" style="max-width:240px;overflow:hidden;text-overflow:ellipsis">${esc(i.description)}</td><td>${fdate(i.issue_date)}</td><td>${fdate(i.due_date)}</td>
          <td>${chip(i.status_view, i.status_view === "overdue" ? `overdue ${i.days_overdue}d` : i.status_view)}</td><td class="num">${money(i.total, i.currency)}</td>
          <td class="num"><div class="row" style="justify-content:flex-end;gap:6px;flex-wrap:nowrap">
            ${["sent", "overdue"].includes(i.status_view) ? `<a class="btn sm ghost" href="/pay/${esc(i.number)}" target="_blank" rel="noopener">Pay link ↗</a><button class="btn sm ghost" data-remind="${i.id}">Remind</button><button class="btn sm ghost" data-paid="${i.id}">Mark paid</button>` : ""}
            ${i.status_view === "draft" ? `<button class="btn sm primary" data-send="${i.id}">Send via PayPal</button>` : ""}
          </div></td></tr>`).join("")}</tbody></table>`;
    };
    renderTable();
    $$("#invSeg button").forEach(b => b.onclick = () => { $$("#invSeg button").forEach(x => x.classList.toggle("on", x === b)); renderTable(b.dataset.s); });
    $("#invTable").onclick = async e => {
      const b = e.target.closest("button"); if (!b) return;
      if (b.dataset.remind) return go("alerts", { remind: +b.dataset.remind });
      if (b.dataset.paid) return markPaid(+b.dataset.paid);
      if (b.dataset.send) {
        if (!await confirmBox("Send invoice via PayPal?", "NEXA will create the invoice in PayPal and email it to the client.", "Send invoice")) return;
        const r = await api(`/api/invoices/${b.dataset.send}/send`, { method: "POST" });
        toast("Invoice sent", `PayPal invoice ${r.id}${r.simulated ? " (demo mode)" : ""}`); route();
      }
    };
    $$(".ex", el).forEach(b => b.onclick = () => { $("#nlText").value = b.textContent; generate(); });
    $("#genBtn").onclick = generate;
    $("#nlText").onkeydown = e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) generate(); };

    async function generate() {
      const btn = $("#genBtn"); btn.disabled = true; btn.innerHTML = '<span class="dots"><span></span><span></span><span></span></span>';
      try {
        draft = await api("/api/invoices/parse", { method: "POST", body: { text: $("#nlText").value } });
        renderForm();
      } catch (e) { toast("Couldn't draft", e.message, "high"); }
      btn.disabled = false; btn.innerHTML = "✦ Generate";
    }
    function renderForm() {
      const st = draft.suggested_terms;
      const opts = custs.map(c => `<option value="${c.id}" ${c.id === draft.customer_id ? "selected" : ""}>${esc(c.name)}</option>`).join("");
      $("#draftForm").innerHTML = `
        ${draft.notes.length ? `<div class="muted xs" style="margin-bottom:10px">${draft.notes.map(esc).join(" · ")}</div>` : ""}
        <div class="form-grid stagger">
          <label class="f">Client<select class="input" id="fCust"><option value="">+ New client…</option>${opts}</select></label>
          <label class="f" id="fNewWrap" style="${draft.customer_id ? "display:none" : ""}">New client name<input class="input" id="fNew" value="${esc(draft.customer_id ? "" : draft.customer_name || "")}"></label>
          <label class="f">Client email<input class="input" id="fEmail" value="${esc(draft.customer_email)}"></label>
          <label class="f full">Service description<input class="input" id="fDesc" value="${esc(draft.description)}"></label>
          <label class="f">Amount<input class="input" id="fAmt" type="number" step="0.01" value="${draft.amount ?? ""}"></label>
          <label class="f">Currency<select class="input" id="fCur">${Object.keys(SYM).map(c => `<option ${c === draft.currency ? "selected" : ""}>${c}</option>`).join("")}</select></label>
          <label class="f">Tax %<input class="input" id="fTax" type="number" step="0.1" value="${draft.tax_rate}"></label>
          <label class="f">Discount %<input class="input" id="fDisc" type="number" step="0.1" value="${draft.discount}"></label>
          <label class="f">Issue date<input class="input" id="fIssue" type="date" value="${draft.issue_date}"></label>
          <label class="f">Due date<input class="input" id="fDue" type="date" value="${draft.due_date}"></label>
          <div class="suggest full">✦ <b>Suggested terms: Net ${st.days}${st.deposit_pct ? ` + ${st.deposit_pct}% deposit` : ""}.</b> ${esc(st.reason)}
            <button class="btn sm ghost" id="applyTerms" style="margin-left:6px">Apply</button></div>
          <div class="full row" style="justify-content:flex-end;margin-top:4px">
            <button class="btn" id="saveDraft">Approve & save draft</button>
            <button class="btn primary" id="sendPP">Approve & send via PayPal</button></div>
        </div>`;
      const f = () => ({
        customer_id: +$("#fCust").value || null, customer_name: $("#fCust").value ? $("#fCust").selectedOptions[0].text : $("#fNew").value,
        customer_email: $("#fEmail").value, description: $("#fDesc").value, amount: +$("#fAmt").value, currency: $("#fCur").value,
        tax_rate: +$("#fTax").value || 0, discount: +$("#fDisc").value || 0, issue_date: $("#fIssue").value, due_date: $("#fDue").value,
        terms: `Net ${Math.round((new Date($("#fDue").value) - new Date($("#fIssue").value)) / 864e5)}`,
      });
      const upd = () => renderPreview(f());
      $$("#draftForm input, #draftForm select").forEach(i => i.addEventListener("input", upd));
      $("#fCust").onchange = () => {
        const c = custs.find(c => c.id === +$("#fCust").value);
        $("#fNewWrap").style.display = c ? "none" : "";
        if (c) { $("#fEmail").value = c.email; $("#fCur").value = c.currency; }
        upd();
      };
      $("#applyTerms").onclick = () => {
        const d = new Date($("#fIssue").value); d.setDate(d.getDate() + st.days);
        $("#fDue").value = d.toISOString().slice(0, 10); upd(); toast("Terms applied", `Net ${st.days}`);
      };
      const submit = async send => {
        const body = f();
        if (!body.amount) return toast("Amount required", "Enter an amount before approving.", "high");
        const total = body.amount * (1 - body.discount / 100) * (1 + body.tax_rate / 100);
        if (!await confirmBox(send ? "Approve & send via PayPal?" : "Approve & save draft?",
          `${esc(body.customer_name || "New client")} · ${money(total, body.currency)} due ${fdate(body.due_date)}.${send ? " The invoice will be created in PayPal and emailed to the client." : ""}`,
          send ? "Approve & send" : "Approve")) return;
        try {
          const r = await api("/api/invoices", { method: "POST", body: { ...body, approved: true, send } });
          toast(send ? "Invoice sent via PayPal" : "Draft saved", `${r.number} · ${money(r.total, body.currency)}${r.paypal?.simulated ? " (demo mode)" : ""}`);
          route();
        } catch (e) { toast("Couldn't create invoice", e.message, "high"); }
      };
      $("#saveDraft").onclick = () => submit(false);
      $("#sendPP").onclick = () => submit(true);
      upd();
    }
    function renderPreview(v) {
      const sub = v.amount || 0, disc = sub * v.discount / 100, tax = (sub - disc) * v.tax_rate / 100, tot = sub - disc + tax;
      $("#preview").innerHTML = `<div class="paper">
        <div class="row" style="justify-content:space-between;align-items:flex-start"><div><h2>Invoice</h2><div class="muted">${esc(META.settings.business_name)}</div></div><span class="stamp">DRAFT · awaiting approval</span></div>
        <div class="row" style="justify-content:space-between;margin:22px 0;align-items:flex-start"><div><div class="muted" style="font-size:12px">Bill to</div><b>${esc(v.customer_name || "—")}</b><div class="muted">${esc(v.customer_email || "")}</div></div>
        <div style="text-align:right"><div class="muted" style="font-size:12px">Issued ${fdate(v.issue_date)}</div><div><b>Due ${fdate(v.due_date)}</b></div><div class="muted" style="font-size:12px">${esc(v.terms)}</div></div></div>
        <table><thead><tr><th>Description</th><th class="num">Amount</th></tr></thead><tbody><tr><td style="white-space:normal">${esc(v.description)}</td><td class="num">${money(sub, v.currency)}</td></tr>
        ${v.discount ? `<tr><td class="muted">Discount (${v.discount}%)</td><td class="num">−${money(disc, v.currency)}</td></tr>` : ""}
        ${v.tax_rate ? `<tr><td class="muted">Tax (${v.tax_rate}%)</td><td class="num">${money(tax, v.currency)}</td></tr>` : ""}</tbody></table>
        <div class="row" style="justify-content:space-between;margin-top:18px"><span class="muted">Total due</span><span class="tot">${money(tot, v.currency)}</span></div>
        <div style="margin-top:20px;padding:12px;border-radius:10px;background:#f5f3ff;font-size:12px;color:#5b21b6">Pay securely with <b>PayPal</b> — link included when sent.</div></div>`;
    }
  };
  async function markPaid(id) {
    try { await api(`/api/invoices/${id}/mark_paid`, { method: "POST", body: {} }); toast("Marked as paid", "Matched to the PayPal payment on record."); route(); }
    catch (e) {
      if (e.status === 409 && await confirmBox("No payment found", "There's no payment recorded for this invoice. Record a manual payment for the full amount?", "Record payment")) {
        await api(`/api/invoices/${id}/mark_paid`, { method: "POST", body: { record_payment: true } }); toast("Payment recorded", "Invoice marked as paid."); route();
      } else if (e.status !== 409) toast("Error", e.message, "high");
    }
  }

  /* ================================================================== AI INSIGHTS */
  views.insights = async el => {
    const d = await api("/api/insights");
    const risky = d.risk;
    el.innerHTML = `
      <div class="grid g-4 stagger">
        <div class="card kpi"><div class="label"><i>📄</i>Open invoices</div><div class="value" data-count="${risky.length}" data-fmt="int">0</div></div>
        <div class="card kpi"><div class="label"><i>🔥</i>High risk</div><div class="value down" data-count="${risky.filter(r => r.risk.level === "high").length}" data-fmt="int">0</div></div>
        <div class="card kpi"><div class="label"><i>💸</i>Outstanding</div><div class="value" data-count="${risky.reduce((a, r) => a + r.total_usd, 0)}" data-fmt="usd">0</div></div>
        <div class="card kpi"><div class="label"><i>🕳️</i>Leak findings</div><div class="value warn-t" data-count="${d.leaks.length}" data-fmt="int">0</div></div>
      </div>
      <h3 style="margin:28px 0 12px;font-family:var(--display)">Payment delay risk · explained</h3>
      <div class="grid stagger">${risky.map(r => `
        <div class="card risk-card hover">
          <div><div class="row" style="justify-content:space-between"><div><b style="font-size:16px">${esc(r.number)}</b> <span class="muted">· ${esc(r.customer)}</span></div>${chip(r.risk.level, r.risk.level + " risk")}</div>
            <div class="row" style="margin:14px 0;gap:22px;align-items:flex-end"><div><div class="muted xs">Risk score</div><div class="risk-score ${r.risk.level === "high" ? "down" : r.risk.level === "medium" ? "warn-t" : "up"}">${r.risk.score}</div></div>
            <div><div class="muted xs">Amount</div><b>${money(r.total, r.currency)}</b></div><div><div class="muted xs">Due</div><b>${fdate(r.due_date)}</b></div>
            <div><div class="muted xs">Likely paid</div><b>${fdate(r.risk.expected_payment_date)}</b></div><div><div class="muted xs">Collection prob.</div><b>${Math.round(r.risk.collection_probability * 100)}%</b></div></div>
            <div class="suggest">✦ <b>Next action:</b> ${esc(r.risk.suggested_action)}</div>
            <div class="row" style="margin-top:12px"><button class="btn sm primary" data-remind="${r.id}">Draft reminder</button><a class="btn sm ghost" href="/pay/${esc(r.number)}" target="_blank">Pay link ↗</a></div></div>
          <div><div class="muted xs" style="margin-bottom:6px">Why NEXA flagged this</div>${r.risk.factors.map(f => `
            <div class="factor"><span>${esc(f.factor)}</span><div class="fbar"><span style="width:${Math.min(100, f.points / 35 * 100)}%"></span></div><span class="muted" style="text-align:right">+${f.points}</span><div class="why">${esc(f.why)}</div></div>`).join("")}</div>
        </div>`).join("") || '<div class="card empty">No open invoices.</div>'}</div>
      <h3 style="margin:28px 0 12px;font-family:var(--display)">Revenue Leak Detector</h3>
      <div class="card">${d.leaks.map((l, i) => `<div class="leak"><span class="sev ${l.severity}"></span><div style="flex:1"><b>${esc(l.title)}</b><p>${esc(l.detail)}</p></div>
        ${l.fix === "mark_paid" ? `<button class="btn sm" data-fixpaid="${l.invoice_id}">Mark paid</button>` : l.fix === "remind" ? `<button class="btn sm" data-remind="${l.invoice_id}">Follow up</button>` : l.fix === "void" ? `<button class="btn sm" data-void="${l.invoice_id}" data-n="${esc(l.invoice)}">Void duplicate</button>` : ""}</div>`).join("") || '<div class="empty">No leaks detected 🎉</div>'}</div>`;
    el.onclick = async e => {
      const b = e.target.closest("button"); if (!b) return;
      if (b.dataset.remind) go("alerts", { remind: +b.dataset.remind });
      if (b.dataset.fixpaid) markPaid(+b.dataset.fixpaid);
      if (b.dataset.void && await confirmBox(`Void ${b.dataset.n}?`, "The invoice will be cancelled and excluded from receivables.", "Void invoice")) {
        await api(`/api/invoices/${b.dataset.void}/void`, { method: "POST" }); toast("Invoice voided", b.dataset.n); route();
      }
    };
  };

  /* ================================================================== CASH FLOW + WHAT-IF */
  views.cashflow = async el => {
    const [fc, custs, fx] = await Promise.all([api("/api/forecast?days=90"), api("/api/customers"), api("/api/currency")]);
    const top = custs[0];
    el.innerHTML = `
      <div class="grid g-4 stagger">
        <div class="card kpi"><div class="label"><i>⬇️</i>Expected inflow (90d)</div><div class="value up" data-count="${fc.expected_inflow}" data-fmt="usd">0</div></div>
        <div class="card kpi"><div class="label"><i>⬆️</i>Operating outflow (90d)</div><div class="value" data-count="${fc.expected_outflow}" data-fmt="usd">0</div></div>
        <div class="card kpi"><div class="label"><i>🏦</i>Projected balance</div><div class="value" data-count="${fc.ending_balance}" data-fmt="usd">0</div><div class="delta muted">from ${money(fc.opening_balance, "USD", 0)} today</div></div>
        <div class="card kpi"><div class="label"><i>🎯</i>Forecast confidence</div><div class="value" data-count="${fc.confidence}" data-fmt="int">0</div><div class="delta muted">% · narrows with horizon</div></div>
      </div>
      <div class="card" style="margin-top:18px"><div class="card-h"><h3>12-week cash-flow forecast</h3><span class="muted xs">Shaded band = confidence range · bars = weekly inflow</span></div>
        <div class="chart-box tall"><canvas id="fcChart"></canvas></div></div>
      <div class="grid g-main" style="margin-top:18px">
        <div class="card ai-card">
          <div class="ai-head" style="margin-bottom:14px"><span class="sparkle">✦</span><div><h3 style="margin:0;font-size:15px">What-If Financial Simulator</h3><div class="muted xs">Ask in plain English or use the sliders</div></div></div>
          <div class="row" style="flex-wrap:nowrap"><input class="input" id="simText" placeholder="What happens if my largest client pays two weeks late?"><button class="btn primary" id="simGo">Simulate</button></div>
          <div class="examples">${["What if my largest client pays two weeks late?", "What if my monthly revenue decreases by 20%?", "What if I get three additional clients?", "What if expenses increase by 15%?", "What if EUR falls 10%?"].map(x => `<button class="ex">${esc(x)}</button>`).join("")}</div>
          <hr class="sep">
          <div class="slider-row"><span>${esc(top.name)} pays late</span><input type="range" id="sDelay" min="0" max="60" value="0"><b id="vDelay">0d</b></div>
          <div class="slider-row"><span>New-business revenue</span><input type="range" id="sRev" min="-50" max="50" value="0"><b id="vRev">0%</b></div>
          <div class="slider-row"><span>Operating expenses</span><input type="range" id="sExp" min="-30" max="60" value="0"><b id="vExp">0%</b></div>
          <div class="slider-row"><span>Additional clients</span><input type="range" id="sNew" min="0" max="6" value="0"><b id="vNew">0</b></div>
          <div id="simOut" style="margin-top:14px"></div>
        </div>
        <div class="card"><div class="card-h"><h3>Multi-currency exposure</h3><span class="muted xs">Reference rates → USD</span></div>
          <div class="chart-box" style="height:180px"><canvas id="fxChart"></canvas></div>
          <div class="table-wrap"><table><thead><tr><th>Ccy</th><th class="num">Received</th><th class="num">Pending</th><th class="num">Share</th></tr></thead><tbody>
          ${fx.map(x => `<tr><td><b>${x.currency}</b> <span class="muted xs">@${x.rate_to_usd}</span></td><td class="num">${money(x.received, x.currency, 0)}</td><td class="num">${money(x.pending, x.currency, 0)}</td><td class="num">${x.share}%</td></tr>`).join("")}</tbody></table></div></div>
      </div>`;
    const ctx = $("#fcChart").getContext("2d");
    const fcc = mkChart($("#fcChart"), {
      data: { labels: fc.labels, datasets: [
        { type: "line", label: "High", data: fc.high, borderWidth: 0, pointRadius: 0, fill: "+1", backgroundColor: "rgba(167,139,250,.12)", order: 3 },
        { type: "line", label: "Low", data: fc.low, borderWidth: 0, pointRadius: 0, fill: false, order: 3 },
        { type: "line", label: "Projected balance", data: fc.balance, borderColor: "#A78BFA", borderWidth: 3, tension: .4, pointRadius: 3, pointBackgroundColor: "#A78BFA", fill: false, order: 1 },
        { type: "line", label: "Scenario", data: [], borderColor: "#22C55E", borderDash: [6, 5], borderWidth: 2.5, tension: .4, pointRadius: 0, fill: false, order: 0, hidden: true },
        { type: "bar", label: "Inflow", data: fc.inflow, backgroundColor: grad(ctx, "rgba(124,58,237,.7)", "rgba(124,58,237,.1)"), borderRadius: 6, maxBarThickness: 26, order: 2, yAxisID: "y" },
      ] },
      options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        plugins: { legend: { labels: { filter: i => !["High", "Low"].includes(i.text) } }, tooltip: { filter: i => !["High", "Low"].includes(i.dataset.label), callbacks: { label: c => ` ${c.dataset.label}: ${money(c.raw, "USD", 0)}` } } },
        scales: { y: { ticks: { callback: usdTick } }, x: { grid: { display: false } } } },
    });
    const fxc = $("#fxChart").getContext("2d");
    mkChart($("#fxChart"), { type: "doughnut", data: { labels: fx.map(x => x.currency), datasets: [{ data: fx.map(x => x.received_usd), borderWidth: 0,
      backgroundColor: ["#7C3AED", "#A78BFA", "#22C55E", "#38BDF8", "#F59E0B", "#F43F5E", "#C4B5FD"] }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: "68%", plugins: { legend: { position: "right" } } } });

    const show = r => {
      if (fcc && r.result) { fcc.data.datasets[3].data = r.result.balance; fcc.data.datasets[3].hidden = !Object.keys(r.scenario).length; fcc.update(); }
      const d = r.delta_ending_balance;
      $("#simOut").innerHTML = Object.keys(r.scenario).length ? `
        <div class="compare stagger"><div><span class="muted xs">Baseline (90d)</span><b>${money(r.baseline.ending_balance, "USD", 0)}</b></div>
        <div><span class="muted xs">Scenario (90d)</span><b>${money(r.result.ending_balance, "USD", 0)}</b></div>
        <div><span class="muted xs">Impact</span><b class="${d < 0 ? "down" : "up"}">${d >= 0 ? "+" : ""}${money(d, "USD", 0)}</b></div></div>
        <div style="margin-top:14px"><div class="muted xs">Assumptions</div><ul class="assume">${r.assumptions.map(a => `<li>${esc(a)}</li>`).join("")}</ul>
        <div class="muted xs">What it means</div><ul class="assume">${r.narrative.map(a => `<li>${esc(a)}</li>`).join("")}</ul></div>`
        : `<div class="muted">${esc(r.assumptions[0] || "Adjust a slider or ask a question to run a scenario.")}</div>`;
    };
    const runText = async text => { $("#simText").value = text; show(await api("/api/simulate", { method: "POST", body: { text, days: 90 } })); };
    let t;
    const runSliders = () => {
      const dly = +$("#sDelay").value, rev = +$("#sRev").value, exp = +$("#sExp").value, nw = +$("#sNew").value;
      $("#vDelay").textContent = dly + "d"; $("#vRev").textContent = (rev > 0 ? "+" : "") + rev + "%"; $("#vExp").textContent = (exp > 0 ? "+" : "") + exp + "%"; $("#vNew").textContent = nw;
      const sc = {};
      if (dly) sc.delay = { [top.id]: dly };
      if (rev) sc.revenue_change_pct = rev;
      if (exp) sc.expense_change_pct = exp;
      if (nw) sc.new_clients = nw;
      const as = [dly && `${top.name} pays ${dly} days later than usual.`, rev && `New-business run-rate ${rev > 0 ? "+" : ""}${rev}%.`, exp && `Operating expenses ${exp > 0 ? "+" : ""}${exp}%.`, nw && `${nw} additional client(s).`].filter(Boolean);
      clearTimeout(t);
      t = setTimeout(async () => { const r = await api("/api/simulate", { method: "POST", body: { scenario: sc, days: 90 } }); r.assumptions = as; show(r); }, 150);
    };
    $$("#sDelay,#sRev,#sExp,#sNew").forEach(s => s.oninput = runSliders);
    $("#simGo").onclick = () => runText($("#simText").value);
    $("#simText").onkeydown = e => { if (e.key === "Enter") runText(e.target.value); };
    $$(".ex", el).forEach(b => b.onclick = () => runText(b.textContent));
    if (pendingSim) { const s = pendingSim; pendingSim = null; setTimeout(() => { runText(s); $("#simText").scrollIntoView({ behavior: "smooth", block: "center" }); }, 400); }
    else show({ scenario: {}, assumptions: [] });
  };

  /* ================================================================== CUSTOMERS */
  views.customers = async el => {
    const cs = await api("/api/customers");
    el.innerHTML = `<div class="grid g-3 stagger">${cs.map(c => `
      <div class="card hover cust" data-c="${c.id}">
        <div class="top"><div class="avatar">${esc(c.name.split(" ").map(w => w[0]).join("").slice(0, 2))}</div>
          <div style="flex:1;min-width:0"><b>${esc(c.name)}</b><div class="muted xs">${esc(c.country)} · ${esc(c.currency)} · ${c.revenue_share}% of revenue</div></div>${chip(c.tone, c.behaviour)}</div>
        <div class="stats"><div>Avg pay time<b>${c.avg_days_to_pay ?? "—"}d</b></div><div>On-time<b>${c.on_time_rate}%</b></div><div>Outstanding<b>${money(c.outstanding_usd, "USD", 0)}</b></div></div>
        ${sparkSVG(c.sparkline, c.tone === "bad" ? "#F43F5E" : c.tone === "warn" ? "#F59E0B" : "#A78BFA")}
        <div class="row xs muted" style="justify-content:space-between;margin-top:6px"><span>${c.total_invoices} invoices · ${c.paid_invoices} paid · ${c.pending_invoices} pending</span><span class="${c.trend === "slowing" ? "down" : c.trend === "improving" ? "up" : ""}">${c.trend === "slowing" ? "▼ slowing" : c.trend === "improving" ? "▲ improving" : "● stable"}</span></div>
      </div>`).join("")}</div>`;
    el.onclick = async e => {
      const card = e.target.closest("[data-c]"); if (!card) return;
      const c = await api("/api/customers/" + card.dataset.c);
      const summary = `${c.name} has ${c.total_invoices} invoices: ${c.paid_invoices} paid and ${c.pending_invoices} pending. They pay in ${c.avg_days_to_pay ?? "—"} days on average (${c.avg_days_late > 0 ? c.avg_days_late + " days after due" : "on or before the due date"}), with ${c.on_time_rate}% on time and a ${c.trend} trend.`;
      const d = drawer(`<div class="row"><div class="avatar">${esc(c.name.slice(0, 2))}</div><div><h2>${esc(c.name)}</h2><div class="muted">${esc(c.email)}</div></div></div>
        <div class="suggest" style="margin:18px 0">✦ ${esc(summary)}</div>
        <div class="kv"><span>Total revenue</span><b>${money(c.revenue_usd, "USD")}</b><span>Outstanding</span><b>${money(c.outstanding_usd, "USD")}</b>
        <span>Avg days late</span><b>${c.avg_days_late}</b><span>Lateness variability</span><b>±${c.lateness_sd} days</b><span>Overdue now</span><b>${c.overdue_invoices}</b><span>Behaviour</span><b>${esc(c.behaviour)}</b></div>
        <div class="chart-box" style="height:180px;margin-top:18px"><canvas id="custChart"></canvas></div><hr class="sep">
        <div class="table-wrap"><table><thead><tr><th>Invoice</th><th>Issued</th><th>Status</th><th class="num">Total</th></tr></thead><tbody>
        ${c.invoices.map(i => `<tr><td>${esc(i.number)}</td><td>${fdate(i.issue_date)}</td><td>${chip(i.status_view)}</td><td class="num">${money(i.total, i.currency)}</td></tr>`).join("")}</tbody></table></div>`);
      const cx = $("#custChart", d).getContext("2d");
      mkChart($("#custChart", d), { type: "bar", data: { labels: Array.from({ length: 12 }, (_, i) => { const t = new Date(); t.setMonth(t.getMonth() - 11 + i); return t.toLocaleString(undefined, { month: "short" }); }),
        datasets: [{ label: "Paid (USD)", data: c.sparkline, backgroundColor: grad(cx), borderRadius: 6 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { ticks: { callback: usdTick } }, x: { grid: { display: false } } } } });
    };
  };

  /* ================================================================== ALERTS + RECOVERY */
  views.alerts = async el => {
    const [a, invs, hist] = await Promise.all([api("/api/alerts"), api("/api/insights"), api("/api/reminders")]);
    const open = invs.risk;
    el.innerHTML = `
      <div class="grid g-2">
        <div class="card"><div class="card-h"><div><h3>Proactive agent feed</h3><div class="muted xs" id="agentInfo">Scans every ${a.interval}s · ${a.runs} scans · last ${a.last_run ? ago(a.last_run.ran_at) : "—"}</div></div>
          <button class="btn sm" id="scanNow">↻ Scan now</button></div><div id="alertList" class="stagger">
          ${a.alerts.map(x => `<div class="alert-item" data-id="${x.id}"><span class="sev ${x.severity}" style="width:10px;height:10px;border-radius:50%;margin-top:6px;flex:none"></span>
            <div class="body"><b>${esc(x.title)}</b><p>${esc(x.detail)}</p><div class="when">${ago(x.created_at)}</div></div>
            <div class="row" style="flex-direction:column;gap:6px">${x.action === "remind" ? `<button class="btn sm primary" data-remind="${x.target}">Recover</button>` : x.action === "ask" ? `<button class="btn sm" data-ask="${esc(x.target)}">Ask NEXA</button>` : `<button class="btn sm" data-go="${x.action}">Open</button>`}
            <button class="btn sm ghost" data-dismiss="${x.id}">Dismiss</button></div></div>`).join("") || '<div class="empty">No active alerts — the agent is watching.</div>'}</div></div>
        <div class="card ai-card"><div class="ai-head" style="margin-bottom:14px"><span class="sparkle">✦</span><div><h3 style="margin:0;font-size:15px">AI Payment Recovery Assistant</h3><div class="muted xs">Personalised reminders · you review and confirm every send</div></div></div>
          <label class="f">Invoice<select class="input" id="recInv">${open.map(r => `<option value="${r.id}">${esc(r.number)} · ${esc(r.customer)} · ${money(r.total, r.currency)} ${r.days_overdue ? `· ${r.days_overdue}d overdue` : `· due ${fdate(r.due_date)}`}</option>`).join("")}</select></label>
          <div class="row" style="margin:12px 0"><div class="seg" id="tone"><button data-t="">Auto</button><button data-t="friendly">Friendly</button><button data-t="firm">Firm</button><button data-t="final">Final</button></div><span class="muted xs" id="timing"></span></div>
          <label class="f">Subject<input class="input" id="rSub"></label>
          <label class="f" style="margin-top:10px">Message<textarea class="input" id="rBody" rows="11"></textarea></label>
          <div class="row" style="justify-content:space-between;margin-top:12px"><span class="muted xs" id="rHist"></span><button class="btn primary" id="rSend">Review & send</button></div>
        </div>
      </div>
      <div class="card" style="margin-top:18px"><div class="card-h"><h3>Reminder history</h3></div><div class="table-wrap"><table><thead><tr><th>Sent</th><th>Invoice</th><th>Client</th><th>Tone</th><th>Subject</th><th>Status</th></tr></thead><tbody>
        ${hist.map(h => `<tr><td>${fdate(h.sent_at || h.created_at)}</td><td>${esc(h.number)}</td><td>${esc(h.customer)}</td><td>${chip(h.tone === "final" ? "high" : h.tone === "firm" ? "medium" : "low", h.tone)}</td><td class="t2">${esc(h.subject)}</td><td>${chip("good", h.status)}</td></tr>`).join("") || '<tr><td colspan="6" class="empty">No reminders sent yet.</td></tr>'}</tbody></table></div></div>`;

    let tone = "", cur = null;
    const loadDraft = async () => {
      if (!$("#recInv").value) return;
      cur = await api(`/api/reminders/draft/${$("#recInv").value}${tone ? "?tone=" + tone : ""}`);
      $("#rSub").value = cur.subject;
      const body = $("#rBody"); body.value = "";
      body.classList.add("typing");
      let i = 0; const txt = cur.body;
      const tick = () => { i += 6; body.value = txt.slice(0, i); if (i < txt.length) requestAnimationFrame(tick); else body.classList.remove("typing"); };
      tick();
      $$("#tone button").forEach(b => b.classList.toggle("on", b.dataset.t === tone || (!tone && b.dataset.t === "")));
      $("#timing").textContent = "⏰ " + cur.timing;
      $("#rHist").textContent = cur.history.length ? `${cur.history.length} previous reminder(s), last ${fdate(cur.history[0].created_at)} · suggested tone: ${cur.tone}` : `No previous reminders · suggested tone: ${cur.tone}`;
    };
    if (pendingRemind) { $("#recInv").value = pendingRemind; pendingRemind = null; }
    $("#recInv").onchange = loadDraft;
    $$("#tone button").forEach(b => b.onclick = () => { tone = b.dataset.t; loadDraft(); });
    $("#rSend").onclick = async () => {
      if (!cur) return;
      const ok = await confirmBox(`Send reminder to ${cur.invoice.customer}?`, `<b>${esc($("#rSub").value)}</b><br><span class="muted">To: ${esc(cur.invoice.customer_email || "client")}</span>`, "Send reminder");
      if (!ok) return;
      const r = await api("/api/reminders", { method: "POST", body: { confirm: true, invoice_id: cur.invoice.id, tone: cur.tone, subject: $("#rSub").value, body: $("#rBody").value } });
      toast("Reminder sent", `${cur.invoice.number} · ${r.delivery === "simulated" ? "delivery simulated (no SMTP configured)" : "emailed"}`);
      route();
    };
    $("#scanNow").onclick = async () => { const r = await api("/api/agent/run", { method: "POST" }); toast("Scan complete", `${r.new} new alert(s)`, r.new ? "medium" : "good"); route(); };
    $("#alertList").onclick = async e => {
      const b = e.target.closest("button"); if (!b) return;
      if (b.dataset.dismiss) {
        const it = b.closest(".alert-item"); it.classList.add("out");
        await api(`/api/alerts/${b.dataset.dismiss}/dismiss`, { method: "POST" }); setTimeout(() => it.remove(), 450); pollAlerts();
      }
      if (b.dataset.remind) { $("#recInv").value = b.dataset.remind; tone = ""; loadDraft(); $("#recInv").scrollIntoView({ behavior: "smooth", block: "center" }); }
      if (b.dataset.go) go(b.dataset.go);
      if (b.dataset.ask) go("ask", { ask: b.dataset.ask });
    };
    await loadDraft();
  };

  /* ================================================================== ASK NEXA */
  let chatLog = [];
  views.ask = async el => {
    const SUG = ["Which clients have pending invoices?", "How much revenue did I receive this month?", "What is my expected cash flow?", "Which invoices need attention?",
      "Generate a payment reminder", "Explain my revenue decline", "Which customers consistently pay late?", "What financial actions should I prioritize today?"];
    el.innerHTML = `<div class="card chat"><div class="msgs" id="msgs"></div>
      <div><div class="sugs">${SUG.map(s => `<button class="ex">${esc(s)}</button>`).join("")}</div>
      <form class="composer" id="askForm"><input class="input" id="askIn" placeholder="Ask about revenue, invoices, clients, cash flow, or “what if…”" autocomplete="off"><button class="btn primary">Send ↵</button></form></div></div>`;
    const msgs = $("#msgs");
    const renderBlocks = r => (r.blocks || []).map(b => {
      if (b.type === "table") return `<div class="blk table-wrap"><table><thead><tr>${b.columns.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${b.rows.map(row => `<tr>${row.map(c => `<td style="white-space:normal">${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
      if (b.type === "list") return `<div class="blk"><div class="muted xs">${esc(b.title)}</div><ul class="assume">${b.items.map(i => `<li>${esc(i)}</li>`).join("")}</ul></div>`;
      if (b.type === "draft") return `<div class="blk"><div class="muted xs">Subject: ${esc(b.subject)}</div><div class="draft">${esc(b.body)}</div></div>`;
      if (b.type === "bars") { const mx = Math.max(...b.values, 1); return `<div class="blk minibars">${b.values.map((v, i) => `<div><i style="height:${Math.max(3, v / mx * 70)}px;animation-delay:${i * .05}s" title="${money(v, "USD", 0)}"></i>${esc(b.labels[i])}</div>`).join("")}</div>`; }
      return "";
    }).join("") + ((r.actions || []).length ? `<div class="blk row">${r.actions.map((a, i) => `<button class="btn sm ${a.confirm ? "primary" : ""}" data-act="${i}">${esc(a.label)}</button>`).join("")}</div>` : "");
    const add = (role, html, r) => {
      const m = document.createElement("div"); m.className = "msg " + role; m.innerHTML = html; msgs.appendChild(m);
      if (r) $$("[data-act]", m).forEach(b => b.onclick = () => doAction(r.actions[+b.dataset.act], b));
      msgs.scrollTo({ top: msgs.scrollHeight, behavior: "smooth" });
      return m;
    };
    const botHTML = r => `<span class="ans"></span>${renderBlocks(r)}<div class="meta">${r.ai === "claude" ? "✦ Claude-phrased" : "✦ NEXA engine"} · grounded in your records</div>`;
    async function doAction(a, btn) {
      if (a.type === "goto") return go(a.to);
      if (a.type === "simulate") return go("cashflow", { simulate: a.text });
      if (a.type === "remind") return go("alerts", { remind: a.invoice_id });
      if (a.type === "send_reminder") {
        if (!await confirmBox("Send this reminder?", `<b>${esc(a.subject)}</b><br><span class="muted">Nothing is sent until you confirm.</span>`, "Send reminder")) return;
        await api("/api/reminders", { method: "POST", body: { confirm: true, invoice_id: a.invoice_id, tone: a.tone, subject: a.subject, body: a.body } });
        btn.disabled = true; btn.textContent = "✓ Sent"; toast("Reminder sent", "Logged in reminder history.");
      }
    }
    const typeInto = (node, text) => new Promise(res => {
      let i = 0; const step = () => { i += 3; node.textContent = text.slice(0, i); if (i < text.length) requestAnimationFrame(step); else res(); }; step();
    });
    async function ask(q) {
      if (!q.trim()) return;
      $("#askIn").value = "";
      add("user", esc(q)); chatLog.push({ role: "user", q });
      const wait = add("bot", '<span class="dots"><span></span><span></span><span></span></span>');
      try {
        const r = await api("/api/ask", { method: "POST", body: { q } });
        wait.innerHTML = botHTML(r);
        $$("[data-act]", wait).forEach(b => b.onclick = () => doAction(r.actions[+b.dataset.act], b));
        $$(".blk", wait).forEach(b => b.style.opacity = 0);
        await typeInto($(".ans", wait), r.text);
        $$(".blk", wait).forEach(b => { b.style.transition = "opacity .5s"; b.style.opacity = 1; });
        chatLog.push({ role: "bot", r });
        msgs.scrollTo({ top: msgs.scrollHeight, behavior: "smooth" });
      } catch (e) { wait.textContent = "Sorry — " + e.message; }
    }
    if (!chatLog.length) add("bot", `Hi${META ? " " + esc(META.settings.owner_name) : ""} 👋 I'm NEXA. I answer using your actual invoices and PayPal payments — and I'll always ask before taking any payment-related action. What would you like to know?`);
    else chatLog.forEach(m => m.role === "user" ? add("user", esc(m.q)) : (() => { const n = add("bot", botHTML(m.r), m.r); $(".ans", n).textContent = m.r.text; })());
    $$(".ex", el).forEach(b => b.onclick = () => ask(b.textContent));
    $("#askForm").onsubmit = e => { e.preventDefault(); ask($("#askIn").value); };
    $("#askIn").focus();
    if (pendingAsk) { const q = pendingAsk; pendingAsk = null; ask(q); }
  };

  /* ================================================================== REPORTS */
  views.reports = async el => {
    const months = Array.from({ length: 12 }, (_, i) => { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - i); return [d.toISOString().slice(0, 7), d.toLocaleString(undefined, { month: "long", year: "numeric" })]; });
    el.innerHTML = `<div class="card no-print"><div class="row">
      <label class="f">Report<select class="input" id="rKind"><option value="monthly">Monthly performance</option><option value="weekly">Weekly revenue</option><option value="daily">Daily summary</option><option value="outstanding">Outstanding payments</option><option value="customers">Customer revenue</option><option value="cashflow">Cash-flow projection</option></select></label>
      <label class="f">Month<select class="input" id="rMonth"><option value="">Auto</option>${months.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
      <div style="flex:1"></div><button class="btn primary" id="rGen">✦ Generate report</button><a class="btn" id="rCsv">Export CSV</a><button class="btn" id="rPdf">Export PDF</button></div></div>
      <div id="rOut" style="margin-top:18px"></div>`;
    const gen = async () => {
      const k = $("#rKind").value, m = $("#rMonth").value;
      $("#rCsv").href = `/api/reports.csv?kind=${k}${m ? "&month=" + m : ""}`;
      $("#rOut").innerHTML = skeleton(1, 400);
      const r = await api(`/api/reports?kind=${k}${m ? "&month=" + m : ""}`);
      const fm = x => x.value == null ? "—" : x.fmt === "usd" ? money(x.value, "USD", 0) : x.fmt === "pct" ? x.value.toFixed(1) + "%" : x.value.toLocaleString();
      $("#rOut").innerHTML = `<div class="report-paper view-enter">
        <div class="row" style="justify-content:space-between;align-items:flex-start"><div><span class="muted xs">${esc(r.business)} · generated ${fdate(r.generated)}</span><h2>${esc(r.title)}</h2><div class="t2">${esc(r.period)}</div></div><span class="logo"><span class="logo-mark"></span>NEXA</span></div>
        <div class="metric-grid stagger">${r.metrics.map(x => `<div class="metric"><span class="muted xs">${esc(x.label)}</span><b>${fm(x)}</b></div>`).join("")}</div>
        <h3 style="font-family:var(--display)">Key observations</h3><ul class="obs">${r.observations.map(o => `<li>${esc(o)}</li>`).join("")}</ul>
        ${r.contribution.length ? `<h3 style="font-family:var(--display);margin-top:22px">Customer contribution</h3>${r.contribution.map(c => `<div class="bar-row" style="margin-bottom:8px"><span class="t2">${esc(c.customer)} · ${money(c.usd, "USD", 0)}</span><span class="muted" style="text-align:right">${c.share}%</span><div class="bar"><span class="tone-ok" style="width:${c.share}%;background:linear-gradient(90deg,#7C3AED,#A78BFA)"></span></div></div>`).join("")}` : ""}
        <h3 style="font-family:var(--display);margin-top:22px">Detail</h3><div class="table-wrap"><table><thead><tr>${r.table.columns.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>
        ${r.table.rows.map(row => `<tr>${row.map(c => `<td>${esc(typeof c === "number" ? c.toLocaleString() : c ?? "—")}</td>`).join("")}</tr>`).join("") || `<tr><td colspan="${r.table.columns.length}" class="empty">No records in this period.</td></tr>`}</tbody></table></div></div>`;
    };
    $("#rGen").onclick = gen; $("#rKind").onchange = gen; $("#rMonth").onchange = gen;
    $("#rPdf").onclick = () => window.print();
    await gen();
  };

  /* ================================================================== SETTINGS */
  views.settings = async el => {
    META = await api("/api/meta");
    const s = META.settings;
    el.innerHTML = `<div class="grid g-2 stagger">
      <div class="card"><div class="card-h"><h3>Business profile</h3></div><div class="form-grid">
        <label class="f">Business name<input class="input" data-k="business_name" value="${esc(s.business_name)}"></label>
        <label class="f">Your name<input class="input" data-k="owner_name" value="${esc(s.owner_name)}"></label>
        <label class="f">Base currency<select class="input" data-k="base_currency">${Object.keys(SYM).map(c => `<option ${c === s.base_currency ? "selected" : ""}>${c}</option>`).join("")}</select></label>
        <label class="f">Default payment terms (days)<input class="input" type="number" data-k="default_terms_days" value="${esc(s.default_terms_days)}"></label>
        <label class="f">Monthly operating expenses (USD)<input class="input" type="number" data-k="monthly_expenses" value="${esc(s.monthly_expenses)}"></label>
        <label class="f">Current cash balance (USD)<input class="input" type="number" data-k="opening_balance" value="${esc(s.opening_balance)}"></label>
        <div class="full row" style="justify-content:flex-end"><button class="btn primary" id="saveS">Save settings</button></div></div></div>
      <div class="grid">
        <div class="card"><div class="card-h"><h3>PayPal connection</h3>${chip(META.paypal_mode === "sandbox" ? "good" : "warn", META.paypal_mode === "sandbox" ? "Sandbox connected" : "Demo mode")}</div>
          <p class="t2" style="margin-top:0">${META.paypal_mode === "sandbox" ? "Using PayPal REST Sandbox for checkout, captures and invoicing." : "Checkout and invoicing are simulated locally with the same verification flow."}</p>
          <p class="muted xs">To connect the Sandbox, set <code>PAYPAL_CLIENT_ID</code> and <code>PAYPAL_CLIENT_SECRET</code> in your environment (from developer.paypal.com → Apps & Credentials) and restart the server.</p></div>
        <div class="card"><div class="card-h"><h3>AI engine</h3>${chip(META.ai_mode === "claude" ? "good" : "ok", META.ai_mode === "claude" ? "Claude · " + META.model : "NEXA engine")}</div>
          <p class="t2" style="margin-top:0">All numbers come from NEXA's deterministic analytics over your records. ${META.ai_mode === "claude" ? "Claude rephrases grounded answers conversationally." : "Set <code>ANTHROPIC_API_KEY</code> and install <code>anthropic</code> to have Claude phrase answers."}</p></div>
        <div class="card"><div class="card-h"><h3>Demo data</h3></div><p class="t2" style="margin-top:0">Regenerate 12 months of realistic invoices, payments and anomalies.</p><button class="btn" id="resetD">Reset demo data</button></div>
      </div></div>`;
    $("#saveS").onclick = async () => {
      const body = {}; $$("[data-k]", el).forEach(i => body[i.dataset.k] = i.value);
      await api("/api/settings", { method: "POST", body }); toast("Settings saved", "Forecasts updated."); loadMeta();
    };
    $("#resetD").onclick = async () => {
      if (!await confirmBox("Reset demo data?", "All invoices, payments, reminders and alerts will be regenerated.", "Reset")) return;
      await api("/api/reset", { method: "POST" }); seen = new Set(); toast("Demo data reset", ""); loadMeta(); pollAlerts(true);
    };
  };

  /* ------------------------------------------------------------------ meta + agent polling */
  async function loadMeta() {
    META = await api("/api/meta");
    const pp = $("#ppMode"), ai = $("#aiMode");
    pp.classList.toggle("on", META.paypal_mode === "sandbox"); pp.querySelector("span").textContent = "PayPal: " + (META.paypal_mode === "sandbox" ? "Sandbox" : "Demo mode");
    ai.classList.toggle("on", META.ai_mode === "claude"); ai.querySelector("span").textContent = "AI: " + (META.ai_mode === "claude" ? "Claude" : "NEXA engine");
    $("#bizName").textContent = META.settings.business_name;
  }
  let seen = null;
  async function pollAlerts(silent) {
    try {
      const a = await api("/api/alerts");
      const urgent = a.alerts.filter(x => ["high", "medium"].includes(x.severity)).length;
      $("#alertBadge").textContent = urgent || "";
      $("#agentText").textContent = a.last_run ? `Agent · scanned ${ago(a.last_run.ran_at)}` : "Agent starting…";
      if (seen && !silent) a.alerts.filter(x => !seen.has(x.id)).slice(0, 3).forEach(x => toast(x.title, x.detail, x.severity));
      seen = new Set(a.alerts.map(x => x.id));
    } catch { /* server restarting */ }
  }

  (async () => {
    await loadMeta().catch(() => {});
    await pollAlerts(true);
    setInterval(pollAlerts, 15000);
    route();
    addEventListener("resize", () => moveIndicator((location.hash.slice(1) || "overview")));
  })();
})();
