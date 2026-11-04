(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const lerp = (a, b, t) => a + (b - a) * t;
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  requestAnimationFrame(() => document.body.classList.add("loaded"));

  /* ---------------- starfield with depth parallax ---------------- */
  const cv = $("#stars"), ctx = cv.getContext("2d");
  let W, H, DPR, stars = [];
  function resize() {
    DPR = Math.min(2, devicePixelRatio || 1);
    W = cv.width = innerWidth * DPR; H = cv.height = innerHeight * DPR;
    stars = Array.from({ length: Math.round(innerWidth * innerHeight / 5200) }, () => ({
      x: Math.random() * W, y: Math.random() * H * 3, z: Math.random() * .9 + .1, tw: Math.random() * Math.PI * 2,
    }));
  }
  resize(); addEventListener("resize", resize);

  /* ---------------- pointer + scroll state (smoothed) ---------------- */
  const m = { x: innerWidth / 2, y: innerHeight / 2, sx: innerWidth / 2, sy: innerHeight / 2 };
  let curY = window.scrollY || 0, sScroll = curY;
  addEventListener("pointermove", e => { m.x = e.clientX; m.y = e.clientY; }, { passive: true });
  addEventListener("scroll", () => { curY = window.scrollY; }, { passive: true });

  const glow = $(".cursor-glow");
  const depthEls = $$("[data-depth]");
  const scrollEls = $$("[data-scroll]");
  const nav = $(".nav");
  const prog = $(".progress span");
  const hs = $(".hscroll"), track = $(".hscroll-track");
  const steps = $(".steps"), stepsLine = $(".steps-line line");

  function frame(t) {
    m.sx = lerp(m.sx, m.x, .08); m.sy = lerp(m.sy, m.y, .08);
    sScroll = lerp(sScroll, curY, .12);
    const nx = (m.sx / innerWidth - .5), ny = (m.sy / innerHeight - .5);

    // stars
    ctx.clearRect(0, 0, W, H);
    for (const s of stars) {
      const y = ((s.y - sScroll * DPR * s.z * .35) % (H * 3) + H * 3) % (H * 3);
      if (y > H) continue;
      const x = s.x + nx * 30 * s.z * DPR;
      const a = .25 + .55 * s.z * (.6 + .4 * Math.sin(t / 900 + s.tw));
      ctx.fillStyle = `rgba(${200 + 55 * s.z | 0},${190 + 40 * s.z | 0},255,${a})`;
      ctx.beginPath(); ctx.arc(x, y, s.z * 1.4 * DPR, 0, 6.283); ctx.fill();
    }

    if (!reduce) {
      glow.style.transform = `translate3d(${m.sx}px, ${m.sy}px, 0) translate(-50%, -50%)`;
      for (const el of depthEls) {
        const d = +el.dataset.depth, s = +(el.dataset.scroll || 0);
        const rx = el.classList.contains("float-card") ? (-ny * 10 * d) : 0, ry = el.classList.contains("float-card") ? (nx * 12 * d) : 0;
        el.style.transform = `translate3d(${nx * 40 * d}px, ${ny * 30 * d + sScroll * s}px, 0) rotateX(${rx}deg) rotateY(${ry}deg)`;
      }
    }

    // nav + progress
    nav.classList.toggle("scrolled", curY > 30);
    const max = document.documentElement.scrollHeight - innerHeight;
    prog.style.transform = `scaleX(${max > 0 ? sScroll / max : 0})`;

    // horizontal sticky track
    if (hs && innerWidth > 640) {
      const r = hs.getBoundingClientRect();
      const total = hs.offsetHeight - innerHeight;
      const p = Math.min(1, Math.max(0, -r.top / total));
      const dist = track.scrollWidth - innerWidth;
      track.style.transform = `translate3d(${-p * dist}px,0,0)`;
    }
    // steps line draw
    if (steps) {
      const r = steps.getBoundingClientRect();
      const p = Math.min(1, Math.max(0, (innerHeight * .75 - r.top) / r.height));
      stepsLine.style.setProperty("--draw", 100 - p * 100);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  /* ---------------- reveal + counters ---------------- */
  const fmt = (n, el) => (el.dataset.prefix || "") + Math.round(n).toLocaleString() + (el.dataset.suffix || "");
  function count(el) {
    const to = +el.dataset.count, t0 = performance.now(), dur = 1800;
    const step = now => {
      const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 4);
      el.textContent = fmt(to * e, el);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  const io = new IntersectionObserver(es => es.forEach(e => {
    if (!e.isIntersecting) return;
    e.target.classList.add("in");
    $$("[data-count]", e.target).forEach(count);
    if (e.target.dataset.count) count(e.target);
    io.unobserve(e.target);
  }), { threshold: .18 });
  $$(".reveal").forEach(el => io.observe(el));
  $$(".fc-value[data-count]").forEach(el => setTimeout(() => count(el), 500));

  /* ---------------- tilt + magnetic ---------------- */
  $$(".tilt").forEach(el => {
    el.addEventListener("pointermove", e => {
      const r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
      el.style.transform = `perspective(900px) rotateX(${-y * 8}deg) rotateY(${x * 10}deg) translateY(-4px)`;
    });
    el.addEventListener("pointerleave", () => { el.style.transform = ""; });
  });
  $$(".magnetic").forEach(el => {
    el.addEventListener("pointermove", e => {
      const r = el.getBoundingClientRect();
      el.style.transform = `translate(${(e.clientX - r.left - r.width / 2) * .25}px, ${(e.clientY - r.top - r.height / 2) * .35}px)`;
    });
    el.addEventListener("pointerleave", () => { el.style.transform = ""; });
  });

  /* ---------------- live What-If teaser (calls the backend) ---------------- */
  const slider = $("#simDays");
  let topClient = null, timer;
  const money = v => (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString();
  function path(vals, min, max, w = 400, h = 220, pad = 14) {
    const sx = w / (vals.length - 1), sy = v => h - pad - (v - min) / (max - min || 1) * (h - pad * 2);
    return vals.map((v, i) => `${i ? "L" : "M"}${(i * sx).toFixed(1)},${sy(v).toFixed(1)}`).join(" ");
  }
  async function runSim() {
    try {
      if (!topClient) {
        const c = await (await fetch("/api/customers")).json();
        topClient = c.data[0];
      }
      const days = +slider.value;
      $("#simDaysLabel").textContent = days === 0 ? "on time" : `${days} days`;
      const r = await (await fetch("/api/simulate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario: { delay: { [topClient.id]: days } }, days: 90 }),
      })).json();
      const b = r.data.baseline.balance, s = r.data.result.balance;
      const min = Math.min(...b, ...s) * .96, max = Math.max(...b, ...s) * 1.02;
      $("#simBase").setAttribute("d", path(b, min, max));
      const line = path(s, min, max);
      $("#simLine").setAttribute("d", line);
      $("#simArea").setAttribute("d", line + " L400,220 L0,220 Z");
      $("#simEnd").textContent = money(r.data.result.ending_balance);
      const d = r.data.delta_ending_balance;
      $("#simDelta").textContent = (d >= 0 ? "+" : "") + money(d).replace("$", "$");
      $("#simDelta").style.color = d < 0 ? "#F43F5E" : "#22C55E";
      $("#simConf").textContent = r.data.result.confidence + "%";
    } catch (e) {
      $("#simEnd").textContent = "Start the backend";
    }
  }
  slider.addEventListener("input", () => {
    $("#simDaysLabel").textContent = +slider.value === 0 ? "on time" : `${slider.value} days`;
    clearTimeout(timer); timer = setTimeout(runSim, 120);
  });
  runSim();
})();
