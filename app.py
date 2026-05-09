"""
L/S RATIO TERMINAL - Cloud-Ready Server
========================================

Render, Railway, Fly.io gibi platformlarda \xe7al\u0131\u015fmaya haz\u0131r.
Local'de de \xe7al\u0131\u015f\u0131r: python3 app.py

\xd6ZELL\u0130KLER:
- PORT environment variable'\u0131ndan okunur (cloud platformlar\u0131 bunu set eder)
- 0.0.0.0'a bind eder (cloud i\xe7in zorunlu)
- Threading ile paralel istekleri destekler
- Hi\xe7bir d\u0131\u015f paket gerektirmez (saf Python 3.7+)
"""

import http.server
import socketserver
import urllib.request
import urllib.parse
import urllib.error
import json
import os
import sys

# Cloud platformlar\u0131 PORT environment variable'\u0131 set eder.
# Local'de \xe7al\u0131\u015ft\u0131r\u0131rken default 8765 kullan\u0131l\u0131r.
PORT = int(os.environ.get("PORT", 8765))
HOST = "0.0.0.0"  # cloud i\xe7in zorunlu (localhost de\u011fil)

USER_AGENT = "Mozilla/5.0 LSRatioTerminal/1.0"


# ----------------------------------------------------------------------
# DASHBOARD HTML
# ----------------------------------------------------------------------
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#0a0e0d">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>L/S Ratio Terminal</title>
<link rel="manifest" href="/manifest.json">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Major+Mono+Display&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<style>
  :root {
    --bg: #0a0e0d; --bg-2: #0f1413; --bg-3: #161c1b;
    --border: #1f2a28; --border-strong: #2a3a37;
    --text: #d4dcd9; --text-dim: #6e7976; --text-faint: #3f4845;
    --green: #00d09c; --green-dim: #007e5e;
    --red: #ff4d6d; --red-dim: #a82d44;
    --amber: #ffb83d; --accent: #6df5d4;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
  html, body { background: var(--bg); color: var(--text);
    font-family: 'JetBrains Mono', monospace; font-size: 13px;
    line-height: 1.5; min-height: 100vh; overflow-x: hidden;
    -webkit-font-smoothing: antialiased; }
  body::before { content:''; position:fixed; inset:0;
    background: radial-gradient(ellipse at top left, rgba(0,208,156,0.04), transparent 50%),
                radial-gradient(ellipse at bottom right, rgba(255,77,109,0.03), transparent 50%);
    pointer-events:none; z-index:0; }
  body::after { content:''; position:fixed; inset:0;
    background-image: linear-gradient(rgba(255,255,255,0.012) 1px, transparent 1px),
                      linear-gradient(90deg, rgba(255,255,255,0.012) 1px, transparent 1px);
    background-size: 40px 40px; pointer-events:none; z-index:0; }
  .wrap { position:relative; z-index:1; max-width:1400px; margin:0 auto;
    padding:24px; padding-top:calc(24px + env(safe-area-inset-top));
    padding-bottom:calc(24px + env(safe-area-inset-bottom)); }

  header { display:flex; align-items:center; justify-content:space-between;
    padding-bottom:18px; border-bottom:1px solid var(--border); margin-bottom:24px;
    gap:16px; flex-wrap:wrap; }
  .logo { font-family:'Major Mono Display', monospace; font-size:22px;
    letter-spacing:0.04em; color:var(--text); }
  .logo span { color: var(--green); }
  .meta { display:flex; gap:20px; align-items:center; font-size:11px; color:var(--text-dim); }
  .meta .dot { width:6px; height:6px; border-radius:50%; background:var(--green);
    display:inline-block; margin-right:6px; box-shadow:0 0 6px var(--green);
    animation:pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.4;} }

  .controls { display:grid; grid-template-columns:1fr auto auto; gap:12px;
    margin-bottom:24px; padding:14px; background:var(--bg-2); border:1px solid var(--border); }
  .input-group { display:flex; flex-direction:column; gap:6px; }
  .input-group label { font-size:10px; letter-spacing:0.18em; color:var(--text-dim); text-transform:uppercase; }
  input[type="text"], select { background:var(--bg); border:1px solid var(--border);
    color:var(--text); font-family:'JetBrains Mono',monospace; font-size:14px;
    padding:10px 12px; outline:none; transition:border-color 0.15s; text-transform:uppercase;
    -webkit-appearance:none; border-radius:0; }
  input[type="text"]:focus, select:focus { border-color:var(--green); }
  input[type="text"]::placeholder { color:var(--text-faint); text-transform:none; }
  button.run { background:var(--green); color:var(--bg); border:none; padding:0 24px;
    font-family:'JetBrains Mono',monospace; font-weight:700; font-size:13px;
    letter-spacing:0.12em; cursor:pointer; align-self:end; height:40px;
    transition:background 0.15s, transform 0.1s; -webkit-appearance:none; border-radius:0; }
  button.run:hover { background:var(--accent); }
  button.run:active { transform:translateY(1px); }
  button.run:disabled { background:var(--border-strong); color:var(--text-dim); cursor:wait; }

  .aggregate { display:grid; grid-template-columns:2fr 1fr 1fr 1fr; gap:1px;
    margin-bottom:24px; background:var(--border); border:1px solid var(--border); }
  .agg-cell { background:var(--bg-2); padding:16px 18px; }
  .agg-label { font-size:10px; letter-spacing:0.18em; color:var(--text-dim);
    text-transform:uppercase; margin-bottom:6px; }
  .agg-value { font-size:22px; font-weight:500; }
  .agg-value.long { color:var(--green); }
  .agg-value.short { color:var(--red); }
  .bar { margin-top:10px; height:6px; background:var(--red-dim); position:relative; overflow:hidden; }
  .bar .fill { position:absolute; left:0; top:0; bottom:0; background:var(--green);
    transition:width 0.6s cubic-bezier(.2,.8,.2,1); }

  h2.section { font-size:11px; letter-spacing:0.22em; color:var(--text-dim);
    text-transform:uppercase; margin:32px 0 12px; padding-bottom:8px;
    border-bottom:1px solid var(--border); }
  h2.section::before { content:'\u25b8 '; color:var(--green); }
  .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(280px,1fr));
    gap:1px; background:var(--border); border:1px solid var(--border); }
  .card { background:var(--bg-2); padding:18px; position:relative; min-height:180px; }
  .card-head { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:14px; }
  .ex-name { font-size:14px; font-weight:700; letter-spacing:0.08em; }
  .ex-status { font-size:10px; color:var(--text-dim); }
  .ex-status.ok { color:var(--green); }
  .ex-status.err { color:var(--red); }
  .ratio-row { display:flex; justify-content:space-between; margin-top:10px; font-size:12px; }
  .ratio-row .l { color:var(--text-dim); }
  .ratio-row .v { color:var(--text); font-weight:500; }
  .pct-bar { margin-top:8px; height:4px; background:var(--red-dim); position:relative; overflow:hidden; }
  .pct-bar .fill { position:absolute; left:0; top:0; bottom:0; background:var(--green);
    transition:width 0.6s cubic-bezier(.2,.8,.2,1); }
  .pct-vals { display:flex; justify-content:space-between; margin-top:6px; font-size:11px; }
  .pct-vals .lng { color:var(--green); }
  .pct-vals .sht { color:var(--red); }
  .err-msg { color:var(--red); font-size:11px; margin-top:8px; opacity:0.7; }

  .chart-wrap { background:var(--bg-2); border:1px solid var(--border);
    padding:18px; margin-top:12px; }
  .chart-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; }
  .chart-head h3 { font-size:12px; letter-spacing:0.12em; color:var(--text); font-weight:500; }
  .timeframe { display:flex; gap:4px; }
  .timeframe button { background:transparent; border:1px solid var(--border);
    color:var(--text-dim); font-family:inherit; font-size:10px; padding:4px 10px;
    cursor:pointer; letter-spacing:0.08em; -webkit-appearance:none; border-radius:0; }
  .timeframe button.active { background:var(--green); color:var(--bg); border-color:var(--green); }
  .timeframe button:hover:not(.active) { color:var(--text); border-color:var(--border-strong); }
  .chart-canvas-box { position:relative; height:380px; }
  .legend-pills { display:flex; gap:16px; flex-wrap:wrap; margin-top:12px; font-size:11px; }
  .legend-pills span { display:flex; align-items:center; gap:6px; color:var(--text-dim); }
  .legend-pills .swatch { width:10px; height:2px; }

  .info { margin-top:32px; padding:16px; background:var(--bg-2);
    border:1px dashed var(--border-strong); font-size:11px; color:var(--text-dim); line-height:1.7; }
  .info b { color:var(--text); }
  .info code { background:var(--bg); padding:1px 6px; color:var(--accent); border:1px solid var(--border); }

  .skeleton { color:var(--text-faint); }
  .blink { animation:blink 1s infinite; }
  @keyframes blink { 50% { opacity:0.3; } }

  /* Mobile optimizations */
  @media (max-width:720px) {
    .wrap { padding:16px; }
    .controls { grid-template-columns:1fr; padding:12px; }
    button.run { height:46px; align-self:stretch; font-size:14px; }
    .aggregate { grid-template-columns:1fr 1fr; }
    .agg-value { font-size:18px; }
    .meta { font-size:10px; gap:12px; }
    .logo { font-size:18px; }
    .chart-canvas-box { height:300px; }
    h2.section { margin:24px 0 10px; }
    .grid { grid-template-columns:1fr; }
    input[type="text"], select { font-size:16px; } /* iOS zoom prevention */
  }
</style>
</head>
<body>
<div class="wrap">

  <header>
    <div class="logo">L/S<span>\xb7</span>RATIO<span>\xb7</span>TERMINAL</div>
    <div class="meta">
      <span><span class="dot"></span>LIVE</span>
      <span id="clock">--:--:-- UTC</span>
    </div>
  </header>

  <div class="controls">
    <div class="input-group">
      <label>SEMBOL / SYMBOL</label>
      <input type="text" id="symbolInput" placeholder="\xf6rn: BTC, ETH, ON, XCN, ONDO" value="BTC" autocomplete="off" autocapitalize="characters">
    </div>
    <div class="input-group">
      <label>PER\u0130YOT / PERIOD</label>
      <select id="periodSelect">
        <option value="5m">5m</option>
        <option value="15m">15m</option>
        <option value="30m">30m</option>
        <option value="1h" selected>1h</option>
        <option value="4h">4h</option>
        <option value="1d">1d</option>
      </select>
    </div>
    <button class="run" id="runBtn">FETCH \u25b8</button>
  </div>

  <div class="aggregate" id="aggregate">
    <div class="agg-cell">
      <div class="agg-label">SYMBOL</div>
      <div class="agg-value" id="aggSymbol">\u2014</div>
    </div>
    <div class="agg-cell">
      <div class="agg-label">AGG LONG %</div>
      <div class="agg-value long" id="aggLong">\u2014</div>
      <div class="bar"><div class="fill" id="aggBar" style="width:0%"></div></div>
    </div>
    <div class="agg-cell">
      <div class="agg-label">AGG SHORT %</div>
      <div class="agg-value short" id="aggShort">\u2014</div>
    </div>
    <div class="agg-cell">
      <div class="agg-label">SOURCES</div>
      <div class="agg-value" id="aggSources">0/4</div>
    </div>
  </div>

  <h2 class="section">EXCHANGE BREAKDOWN</h2>
  <div class="grid" id="cards"></div>

  <h2 class="section">TIME SERIES \xb7 LONG ACCOUNT %</h2>
  <div class="chart-wrap">
    <div class="chart-head">
      <h3>HISTORICAL RATIO</h3>
      <div class="timeframe" id="tf">
        <button data-limit="30">30P</button>
        <button data-limit="60" class="active">60P</button>
        <button data-limit="120">120P</button>
      </div>
    </div>
    <div class="chart-canvas-box"><canvas id="chart"></canvas></div>
    <div class="legend-pills" id="legendPills"></div>
  </div>

  <div class="info">
    <b>NASIL \xc7ALI\u015eIR?</b> Bu terminal Binance, Bybit, OKX ve Bitget public futures API'lerini sorgular. Hi\xe7bir API key gerekmez.<br><br>
    <b>VER\u0130:</b> G\xf6sterilen oran <i>Long/Short Account Ratio</i>'dur (toplam hesap say\u0131s\u0131 baz\u0131nda). Coin t\xfcm borsalarda futures olarak listeli olmayabilir; listelenmeyen borsa "NO DATA" d\xf6ner.<br><br>
    <b>YASAL UYARI:</b> Bu ara\xe7 finansal tavsiye de\u011fildir. L/S oran\u0131 tek ba\u015f\u0131na sinyal de\u011fildir; funding rate, open interest ve fiyat aksiyonu ile birlikte de\u011ferlendirilmelidir.
  </div>

</div>

<script>
const EXCHANGES = ['Binance', 'Bybit', 'OKX', 'Bitget'];
const COLORS = {
  Binance: '#f3ba2f',
  Bybit:   '#ffb83d',
  OKX:     '#6df5d4',
  Bitget:  '#ff4d6d',
};

let chart = null;
let lastFetch = null;

async function fetchOne(ex, sym, period, limit) {
  const url = `/api/${ex.toLowerCase()}?symbol=${encodeURIComponent(sym)}&period=${period}&limit=${limit}`;
  const r = await fetch(url);
  if (!r.ok) {
    let body;
    try { body = await r.json(); } catch { body = { error: `HTTP ${r.status}` }; }
    throw new Error(body.error || `HTTP ${r.status}`);
  }
  return await r.json();
}

function renderCards(results) {
  const grid = document.getElementById('cards');
  grid.innerHTML = '';
  EXCHANGES.forEach(ex => {
    const r = results[ex];
    const card = document.createElement('div');
    card.className = 'card';
    if (r && r.ok) {
      card.innerHTML = `
        <div class="card-head">
          <div class="ex-name">${ex.toUpperCase()}</div>
          <div class="ex-status ok">\u25cf ONLINE</div>
        </div>
        <div class="ratio-row"><span class="l">L/S RATIO</span><span class="v">${r.longShortRatio.toFixed(3)}</span></div>
        <div class="ratio-row"><span class="l">LONG ACCOUNTS</span><span class="v">${r.longPct.toFixed(2)}%</span></div>
        <div class="ratio-row"><span class="l">SHORT ACCOUNTS</span><span class="v">${r.shortPct.toFixed(2)}%</span></div>
        <div class="pct-bar"><div class="fill" style="width:${r.longPct}%"></div></div>
        <div class="pct-vals"><span class="lng">\u25b2 ${r.longPct.toFixed(1)}%</span><span class="sht">\u25bc ${r.shortPct.toFixed(1)}%</span></div>
      `;
    } else {
      const msg = r?.error || 'NO DATA';
      card.innerHTML = `
        <div class="card-head">
          <div class="ex-name">${ex.toUpperCase()}</div>
          <div class="ex-status err">\u25cf NO DATA</div>
        </div>
        <div class="err-msg">Bu coin bu borsada listeli de\u011fil ya da API yan\u0131t vermedi</div>
        <div class="err-msg" style="margin-top:6px;font-size:10px;opacity:0.5">${msg}</div>
      `;
    }
    grid.appendChild(card);
  });
}

function renderAggregate(sym, results) {
  const ok = EXCHANGES.filter(ex => results[ex]?.ok);
  document.getElementById('aggSymbol').textContent = sym.toUpperCase();
  document.getElementById('aggSources').textContent = `${ok.length}/${EXCHANGES.length}`;
  if (ok.length === 0) {
    document.getElementById('aggLong').textContent = '\u2014';
    document.getElementById('aggShort').textContent = '\u2014';
    document.getElementById('aggBar').style.width = '0%';
    return;
  }
  const avgLong = ok.reduce((s, ex) => s + results[ex].longPct, 0) / ok.length;
  const avgShort = 100 - avgLong;
  document.getElementById('aggLong').textContent = avgLong.toFixed(2) + '%';
  document.getElementById('aggShort').textContent = avgShort.toFixed(2) + '%';
  document.getElementById('aggBar').style.width = avgLong + '%';
}

function renderChart(results) {
  const ctx = document.getElementById('chart');
  const datasets = [];
  EXCHANGES.forEach(ex => {
    const r = results[ex];
    if (!r?.ok || !r.series?.length) return;
    datasets.push({
      label: ex,
      data: r.series.map(p => ({ x: p.t, y: p.longPct })),
      borderColor: COLORS[ex],
      backgroundColor: COLORS[ex] + '22',
      borderWidth: 1.6,
      pointRadius: 0,
      pointHoverRadius: 4,
      tension: 0.25,
      fill: false,
    });
  });

  if (chart) chart.destroy();

  if (datasets.length === 0) {
    document.getElementById('legendPills').innerHTML = '<span style="color:var(--text-faint)">veri yok</span>';
    return;
  }

  chart = new Chart(ctx, {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#0a0e0d', borderColor: '#2a3a37', borderWidth: 1,
          titleColor: '#d4dcd9', bodyColor: '#d4dcd9',
          titleFont: { family: 'JetBrains Mono', size: 11 },
          bodyFont: { family: 'JetBrains Mono', size: 11 },
          padding: 10,
          callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(2)}%` }
        }
      },
      scales: {
        x: { type: 'time',
          time: { displayFormats: { minute:'HH:mm', hour:'MM/dd HH:mm', day:'MM/dd' } },
          grid: { color:'#14201d', drawTicks:false },
          ticks: { color:'#6e7976', font:{ family:'JetBrains Mono', size:10 }, maxTicksLimit: 6 },
          border: { color:'#1f2a28' } },
        y: { min:0, max:100,
          grid: { color:'#14201d', drawTicks:false },
          ticks: { color:'#6e7976', font:{ family:'JetBrains Mono', size:10 },
                   callback: (v) => v + '%' },
          border: { color:'#1f2a28' } },
      },
    },
  });

  const lp = document.getElementById('legendPills');
  lp.innerHTML = datasets.map(d =>
    `<span><span class="swatch" style="background:${d.borderColor}"></span>${d.label}</span>`
  ).join('');
}

async function run() {
  const sym = document.getElementById('symbolInput').value.trim().toUpperCase();
  if (!sym) return;
  const period = document.getElementById('periodSelect').value;
  const limit = +document.querySelector('#tf button.active').dataset.limit;
  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  btn.textContent = 'FETCHING\u2026';

  document.getElementById('cards').innerHTML = EXCHANGES.map(ex => `
    <div class="card">
      <div class="card-head">
        <div class="ex-name">${ex.toUpperCase()}</div>
        <div class="ex-status blink">\u25cf LOADING</div>
      </div>
      <div class="ratio-row skeleton"><span class="l">L/S RATIO</span><span class="v">\xb7\xb7\xb7</span></div>
      <div class="ratio-row skeleton"><span class="l">LONG</span><span class="v">\xb7\xb7\xb7</span></div>
      <div class="ratio-row skeleton"><span class="l">SHORT</span><span class="v">\xb7\xb7\xb7</span></div>
    </div>
  `).join('');

  const promises = EXCHANGES.map(ex =>
    fetchOne(ex, sym, period, limit)
      .then(data => [ex, data])
      .catch(err => [ex, { ok: false, error: err.message || String(err) }])
  );
  const settled = await Promise.all(promises);
  const results = Object.fromEntries(settled);
  lastFetch = { sym, period, limit, results };

  renderAggregate(sym, results);
  renderCards(results);
  renderChart(results);

  btn.disabled = false;
  btn.textContent = 'FETCH \u25b8';
}

document.getElementById('runBtn').addEventListener('click', run);
document.getElementById('symbolInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.target.blur(); run(); }
});
document.getElementById('periodSelect').addEventListener('change', run);
document.querySelectorAll('#tf button').forEach(b => {
  b.addEventListener('click', () => {
    document.querySelectorAll('#tf button').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    if (lastFetch) run();
  });
});

function tick() {
  const d = new Date();
  const z = n => String(n).padStart(2, '0');
  document.getElementById('clock').textContent =
    `${z(d.getUTCHours())}:${z(d.getUTCMinutes())}:${z(d.getUTCSeconds())} UTC`;
}
setInterval(tick, 1000); tick();

run();
</script>
</body>
</html>
"""

# Android "Ana ekrana ekle" i\xe7in PWA manifest
MANIFEST_JSON = json.dumps({
    "name": "L/S Ratio Terminal",
    "short_name": "L/S Ratio",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#0a0e0d",
    "theme_color": "#0a0e0d",
    "orientation": "portrait",
    "icons": [
        {
            "src": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 192 192'%3E%3Crect fill='%230a0e0d' width='192' height='192'/%3E%3Ctext x='96' y='110' font-family='monospace' font-size='48' font-weight='bold' fill='%2300d09c' text-anchor='middle'%3EL/S%3C/text%3E%3C/svg%3E",
            "sizes": "192x192",
            "type": "image/svg+xml"
        }
    ]
})


# ----------------------------------------------------------------------
# EXCHANGE FETCHERS
# ----------------------------------------------------------------------

def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw)


def fetch_binance(symbol, period, limit):
    sym = symbol.upper().replace("USDT", "") + "USDT"
    period_map = {"5m":"5m","15m":"15m","30m":"30m","1h":"1h","4h":"4h","1d":"1d"}
    p = period_map.get(period, "1h")
    url = (f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
           f"?symbol={sym}&period={p}&limit={limit}")
    data = http_get(url)
    if not isinstance(data, list) or len(data) == 0:
        raise RuntimeError("NO DATA")
    series = [{"t": int(d["timestamp"]), "longPct": float(d["longAccount"]) * 100} for d in data]
    last = data[-1]
    return {
        "ok": True,
        "longPct": float(last["longAccount"]) * 100,
        "shortPct": float(last["shortAccount"]) * 100,
        "longShortRatio": float(last["longShortRatio"]),
        "series": series,
    }


def fetch_bybit(symbol, period, limit):
    sym = symbol.upper().replace("USDT", "") + "USDT"
    period_map = {"5m":"5min","15m":"15min","30m":"30min","1h":"1h","4h":"4h","1d":"1d"}
    p = period_map.get(period, "1h")
    url = (f"https://api.bybit.com/v5/market/account-ratio"
           f"?category=linear&symbol={sym}&period={p}&limit={limit}")
    j = http_get(url)
    if j.get("retCode") != 0:
        raise RuntimeError(j.get("retMsg") or "API ERROR")
    lst = (j.get("result") or {}).get("list") or []
    if not lst:
        raise RuntimeError("NO DATA")
    sorted_list = sorted(lst, key=lambda d: int(d["timestamp"]))
    series = [{"t": int(d["timestamp"]), "longPct": float(d["buyRatio"]) * 100} for d in sorted_list]
    last = sorted_list[-1]
    long_pct = float(last["buyRatio"]) * 100
    short_pct = float(last["sellRatio"]) * 100
    return {
        "ok": True,
        "longPct": long_pct,
        "shortPct": short_pct,
        "longShortRatio": (long_pct / short_pct) if short_pct else 0,
        "series": series,
    }


def fetch_okx(symbol, period, limit):
    ccy = symbol.upper().replace("USDT", "").replace("-USDT-SWAP", "")
    period_map = {"5m":"5m","15m":"15m","30m":"30m","1h":"1H","4h":"4H","1d":"1D"}
    p = period_map.get(period, "1H")
    url = (f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio"
           f"?ccy={ccy}&period={p}&limit={limit}")
    j = http_get(url)
    if j.get("code") != "0":
        raise RuntimeError(j.get("msg") or "API ERROR")
    arr = j.get("data") or []
    if not arr:
        raise RuntimeError("NO DATA")
    sorted_arr = sorted(arr, key=lambda d: int(d[0]))
    series = []
    for d in sorted_arr:
        ratio = float(d[1])
        long_pct = ratio / (1 + ratio) * 100
        series.append({"t": int(d[0]), "longPct": long_pct})
    last_ratio = float(sorted_arr[-1][1])
    long_pct = last_ratio / (1 + last_ratio) * 100
    return {
        "ok": True,
        "longPct": long_pct,
        "shortPct": 100 - long_pct,
        "longShortRatio": last_ratio,
        "series": series,
    }


def fetch_bitget(symbol, period, limit):
    sym = symbol.upper().replace("USDT", "") + "USDT"
    period_map = {"5m":"5m","15m":"15m","30m":"30m","1h":"1h","4h":"4h","1d":"1d"}
    p = period_map.get(period, "1h")
    url = (f"https://api.bitget.com/api/v2/mix/market/account-long-short"
           f"?symbol={sym}&period={p}&productType=USDT-FUTURES&limit={limit}")
    j = http_get(url)
    if j.get("code") != "00000":
        raise RuntimeError(j.get("msg") or "API ERROR")
    arr = j.get("data") or []
    if not arr:
        raise RuntimeError("NO DATA")
    sorted_arr = sorted(arr, key=lambda d: int(d["ts"]))
    series = [{"t": int(d["ts"]), "longPct": float(d["longAccountRatio"]) * 100} for d in sorted_arr]
    last = sorted_arr[-1]
    long_pct = float(last["longAccountRatio"]) * 100
    short_pct = float(last["shortAccountRatio"]) * 100
    return {
        "ok": True,
        "longPct": long_pct,
        "shortPct": short_pct,
        "longShortRatio": (long_pct / short_pct) if short_pct else 0,
        "series": series,
    }


FETCHERS = {
    "binance": fetch_binance,
    "bybit":   fetch_bybit,
    "okx":     fetch_okx,
    "bitget":  fetch_bitget,
}


# ----------------------------------------------------------------------
# HTTP HANDLER
# ----------------------------------------------------------------------

class LSHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        sys.stderr.write(f"  - {self.address_string()} - {format % args}\n")

    def _send(self, status, content_type, body_bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body_bytes)

    def _send_json(self, status, payload):
        self._send(status, "application/json; charset=utf-8",
                   json.dumps(payload).encode("utf-8"))

    def _send_html(self, html):
        self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        q = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._send_html(DASHBOARD_HTML)
            return

        if path == "/manifest.json":
            self._send(200, "application/json; charset=utf-8", MANIFEST_JSON.encode("utf-8"))
            return

        if path == "/healthz":  # cloud platformlar i\xe7in
            self._send_json(200, {"ok": True})
            return

        if path.startswith("/api/"):
            ex = path[len("/api/"):].strip("/").lower()
            if ex not in FETCHERS:
                self._send_json(404, {"ok": False, "error": f"unknown exchange: {ex}"})
                return
            symbol = (q.get("symbol", [""])[0] or "").strip()
            period = (q.get("period", ["1h"])[0] or "1h").strip()
            try:
                limit = int(q.get("limit", ["60"])[0])
            except ValueError:
                limit = 60
            limit = max(1, min(limit, 500))

            if not symbol:
                self._send_json(400, {"ok": False, "error": "symbol required"})
                return

            try:
                data = FETCHERS[ex](symbol, period, limit)
                self._send_json(200, data)
            except urllib.error.HTTPError as e:
                self._send_json(200, {"ok": False, "error": f"upstream HTTP {e.code}"})
            except urllib.error.URLError as e:
                self._send_json(200, {"ok": False, "error": f"network: {e.reason}"})
            except Exception as e:
                self._send_json(200, {"ok": False, "error": str(e)})
            return

        self._send_json(404, {"ok": False, "error": "not found"})


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    print(f"L/S Ratio Terminal listening on {HOST}:{PORT}", flush=True)
    try:
        with ThreadedServer((HOST, PORT), LSHandler) as srv:
            srv.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.", flush=True)


if __name__ == "__main__":
    main()
