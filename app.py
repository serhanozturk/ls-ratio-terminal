"""
L/S RATIO TERMINAL - Cloud-Ready Server (v2)
=============================================

Bu versiyon su duzeltmeleri icerir:
- HTML icinde escape karakter sorunu giderildi (artik gercek Unicode/entity)
- Tum borsalar icin ortak zaman penceresi (grafik hizali)
- Sabit borsa renkleri: Binance sari, Bybit kirmizi, OKX beyaz, Bitget turkuaz
- Binance OI icin 3 fallback yolu

Calistirma:
  python3 app.py
"""

import http.server
import socketserver
import urllib.request
import urllib.parse
import urllib.error
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

PORT = int(os.environ.get("PORT", 8765))
HOST = "0.0.0.0"
USER_AGENT = "Mozilla/5.0 LSRatioTerminal/2.0"


# ======================================================================
# DASHBOARD HTML
# Not: r-string DEGIL normal string. HTML entity ile sembol kullaniyoruz.
# ======================================================================

DASHBOARD_HTML = """<!DOCTYPE html>
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
    --bg: #0a0e0d; --bg-2: #0f1413;
    --border: #1f2a28; --border-strong: #2a3a37;
    --text: #d4dcd9; --text-dim: #6e7976; --text-faint: #3f4845;
    --green: #00d09c; --red: #ff4d6d; --red-dim: #a82d44;
    --accent: #6df5d4;
    --binance: #f3ba2f;
    --bybit:   #ff4d6d;
    --okx:     #ffffff;
    --bitget:  #6df5d4;
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
  h2.section .arrow { color:var(--green); margin-right:6px; }

  .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(280px,1fr));
    gap:1px; background:var(--border); border:1px solid var(--border); }
  .card { background:var(--bg-2); padding:18px; position:relative; min-height:240px;
    border-top:2px solid transparent; }
  .card.ex-binance { border-top-color: var(--binance); }
  .card.ex-bybit   { border-top-color: var(--bybit); }
  .card.ex-okx     { border-top-color: var(--okx); }
  .card.ex-bitget  { border-top-color: var(--bitget); }
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
  .divider { height:1px; background:var(--border); margin:14px 0 8px; }
  .v.fr-pos { color:var(--green); }
  .v.fr-neg { color:var(--red); }
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
  .legend-pills .swatch { width:14px; height:3px; }

  .info { margin-top:32px; padding:16px; background:var(--bg-2);
    border:1px dashed var(--border-strong); font-size:11px; color:var(--text-dim); line-height:1.7; }
  .info b { color:var(--text); }
  .info code { background:var(--bg); padding:1px 6px; color:var(--accent); border:1px solid var(--border); }

  .skeleton { color:var(--text-faint); }
  .blink { animation:blink 1s infinite; }
  @keyframes blink { 50% { opacity:0.3; } }

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
    input[type="text"], select { font-size:16px; }
  }
</style>
</head>
<body>
<div class="wrap">

  <header>
    <div class="logo">L/S<span>&middot;</span>RATIO<span>&middot;</span>TERMINAL</div>
    <div class="meta">
      <span><span class="dot"></span>LIVE</span>
      <span id="clock">--:--:-- UTC</span>
    </div>
  </header>

  <div class="controls">
    <div class="input-group">
      <label>SEMBOL / SYMBOL</label>
      <input type="text" id="symbolInput" placeholder="orn: BTC, ETH, ON, XCN, ONDO" value="BTC" autocomplete="off" autocapitalize="characters">
    </div>
    <div class="input-group">
      <label>PERIYOT / PERIOD</label>
      <select id="periodSelect">
        <option value="5m">5m</option>
        <option value="15m">15m</option>
        <option value="30m">30m</option>
        <option value="1h" selected>1h</option>
        <option value="4h">4h</option>
        <option value="1d">1d</option>
      </select>
    </div>
    <button class="run" id="runBtn">FETCH &gt;</button>
  </div>

  <div class="aggregate" id="aggregate">
    <div class="agg-cell">
      <div class="agg-label">SYMBOL</div>
      <div class="agg-value" id="aggSymbol">&mdash;</div>
    </div>
    <div class="agg-cell">
      <div class="agg-label">AGG LONG %</div>
      <div class="agg-value long" id="aggLong">&mdash;</div>
      <div class="bar"><div class="fill" id="aggBar" style="width:0%"></div></div>
    </div>
    <div class="agg-cell">
      <div class="agg-label">AGG SHORT %</div>
      <div class="agg-value short" id="aggShort">&mdash;</div>
    </div>
    <div class="agg-cell">
      <div class="agg-label">SOURCES</div>
      <div class="agg-value" id="aggSources">0/4</div>
    </div>
  </div>

  <h2 class="section"><span class="arrow">&#9656;</span>EXCHANGE BREAKDOWN</h2>
  <div class="grid" id="cards"></div>

  <h2 class="section"><span class="arrow">&#9656;</span>TIME SERIES &middot; LONG ACCOUNT %</h2>
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
    <b>NASIL CALISIR?</b> Bu terminal Binance, Bybit, OKX ve Bitget public futures API'lerini sorgular. Hicbir API key gerekmez.<br><br>
    <b>METRIKLER:</b><br>
    &bull; <b>L/S Ratio</b>: Long/Short hesap orani. &gt;1 = long baskin, &lt;1 = short baskin.<br>
    &bull; <b>Open Interest (OI)</b>: Acik pozisyonlarin toplam USD degeri. Yukselen OI = yeni para giriyor; dusen OI = pozisyonlar kapaniyor.<br>
    &bull; <b>Funding Rate</b>: Pozitif = longlar shortlara oduyor (asiri boga); negatif = shortlar longlara oduyor (asiri ayi). Genelde 8 saatte bir.<br><br>
    <b>YORUMLAMA:</b> Yuksek long orani + yuksek pozitif funding = asiri boga, duzeltme riski. Yuksek short orani + negatif funding = short squeeze potansiyeli.<br><br>
    <b>YASAL UYARI:</b> Bu arac finansal tavsiye degildir. Metrikler tek baslarina sinyal degildir; fiyat aksiyonu ve diger veri kaynaklari ile birlikte degerlendirilmelidir.
  </div>

</div>

<script>
const EXCHANGES = ['Binance', 'Bybit', 'OKX', 'Bitget'];

const COLORS = {
  Binance: '#f3ba2f',
  Bybit:   '#ff4d6d',
  OKX:     '#ffffff',
  Bitget:  '#6df5d4',
};

let chart = null;
let lastFetch = null;

function cleanSymbol(raw) {
  return (raw || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
}

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

function fmtUSD(n) {
  if (n == null || isNaN(n)) return '\u2014';
  const abs = Math.abs(n);
  if (abs >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
  if (abs >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
  if (abs >= 1e3) return '$' + (n / 1e3).toFixed(2) + 'K';
  return '$' + n.toFixed(2);
}

function fmtFunding(pct) {
  if (pct == null || isNaN(pct)) return { text: '\u2014', cls: '' };
  const sign = pct >= 0 ? '+' : '';
  return {
    text: sign + pct.toFixed(4) + '%',
    cls: pct > 0 ? 'fr-pos' : (pct < 0 ? 'fr-neg' : '')
  };
}

function renderCards(results) {
  const grid = document.getElementById('cards');
  grid.innerHTML = '';
  EXCHANGES.forEach(ex => {
    const r = results[ex];
    const card = document.createElement('div');
    card.className = 'card ex-' + ex.toLowerCase();
    if (r && r.ok) {
      const fr = fmtFunding(r.fundingRate);
      const oi = fmtUSD(r.openInterest);
      card.innerHTML = `
        <div class="card-head">
          <div class="ex-name">${ex.toUpperCase()}</div>
          <div class="ex-status ok">\u25CF ONLINE</div>
        </div>
        <div class="ratio-row"><span class="l">L/S RATIO</span><span class="v">${r.longShortRatio.toFixed(3)}</span></div>
        <div class="ratio-row"><span class="l">LONG ACCOUNTS</span><span class="v">${r.longPct.toFixed(2)}%</span></div>
        <div class="ratio-row"><span class="l">SHORT ACCOUNTS</span><span class="v">${r.shortPct.toFixed(2)}%</span></div>
        <div class="pct-bar"><div class="fill" style="width:${r.longPct}%"></div></div>
        <div class="pct-vals"><span class="lng">\u25B2 ${r.longPct.toFixed(1)}%</span><span class="sht">\u25BC ${r.shortPct.toFixed(1)}%</span></div>
        <div class="divider"></div>
        <div class="ratio-row"><span class="l">OPEN INTEREST</span><span class="v">${oi}</span></div>
        <div class="ratio-row"><span class="l">FUNDING RATE</span><span class="v ${fr.cls}">${fr.text}</span></div>
      `;
    } else {
      const msg = r?.error || 'NO DATA';
      card.innerHTML = `
        <div class="card-head">
          <div class="ex-name">${ex.toUpperCase()}</div>
          <div class="ex-status err">\u25CF NO DATA</div>
        </div>
        <div class="err-msg">Bu coin bu borsada listeli degil ya da API yanit vermedi</div>
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

function periodHours(p) {
  return { '5m':5/60, '15m':15/60, '30m':30/60, '1h':1, '4h':4, '1d':24 }[p] || 1;
}

function renderChart(results, period, limit) {
  const ctx = document.getElementById('chart');
  const datasets = [];

  // Ortak zaman penceresi: simdiden geriye limit * periyot kadar
  const now = Date.now();
  const windowMs = limit * periodHours(period) * 3600 * 1000;
  const cutoff = now - windowMs;

  EXCHANGES.forEach(ex => {
    const r = results[ex];
    if (!r?.ok || !r.series?.length) return;
    // Pencere icindeki noktalari al
    const filtered = r.series.filter(p => p.t >= cutoff);
    if (filtered.length === 0) return;
    datasets.push({
      label: ex,
      data: filtered.map(p => ({ x: p.t, y: p.longPct })),
      borderColor: COLORS[ex],
      backgroundColor: COLORS[ex] + '22',
      borderWidth: 1.8,
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
          min: cutoff,
          max: now,
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
  const rawInput = document.getElementById('symbolInput').value;
  const sym = cleanSymbol(rawInput);
  if (sym !== rawInput.trim().toUpperCase()) {
    document.getElementById('symbolInput').value = sym;
  }
  if (!sym) return;

  const period = document.getElementById('periodSelect').value;
  const limit = +document.querySelector('#tf button.active').dataset.limit;
  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  btn.textContent = 'FETCHING...';

  document.getElementById('cards').innerHTML = EXCHANGES.map(ex => `
    <div class="card ex-${ex.toLowerCase()}">
      <div class="card-head">
        <div class="ex-name">${ex.toUpperCase()}</div>
        <div class="ex-status blink">\u25CF LOADING</div>
      </div>
      <div class="ratio-row skeleton"><span class="l">L/S RATIO</span><span class="v">...</span></div>
      <div class="ratio-row skeleton"><span class="l">LONG</span><span class="v">...</span></div>
      <div class="ratio-row skeleton"><span class="l">SHORT</span><span class="v">...</span></div>
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
  renderChart(results, period, limit);

  btn.disabled = false;
  btn.textContent = 'FETCH >';
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

setInterval(() => { if (!document.hidden && lastFetch) run(); }, 60000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && lastFetch) run();
});

run();
</script>
</body>
</html>
"""

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


# ======================================================================
# EXCHANGE FETCHERS
# ======================================================================

def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw)


def safe(fn):
    try:
        return fn()
    except Exception:
        return None


# ============== BINANCE ==============

def _binance_oi(sym):
    try:
        oi_j = http_get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}")
        qty = float(oi_j.get("openInterest") or 0)
        if qty > 0:
            try:
                pj = http_get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}")
                price = float(pj.get("markPrice") or 0)
                if price > 0:
                    return qty * price
            except Exception:
                pass
            try:
                tj = http_get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}")
                price = float(tj.get("price") or 0)
                if price > 0:
                    return qty * price
            except Exception:
                pass
    except Exception:
        pass

    try:
        j = http_get(f"https://fapi.binance.com/futures/data/openInterestHist?symbol={sym}&period=5m&limit=1")
        if isinstance(j, list) and j:
            v = float(j[0].get("sumOpenInterestValue") or 0)
            if v > 0:
                return v
    except Exception:
        pass
    return None


def _binance_funding(sym):
    try:
        j = http_get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}")
        fr = j.get("lastFundingRate")
        if fr is not None and fr != "":
            return float(fr) * 100
    except Exception:
        pass
    try:
        j = http_get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&limit=1")
        if isinstance(j, list) and j:
            return float(j[0].get("fundingRate") or 0) * 100
    except Exception:
        pass
    return None


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

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_oi = ex.submit(safe, lambda: _binance_oi(sym))
        f_fr = ex.submit(safe, lambda: _binance_funding(sym))
        oi_usd = f_oi.result()
        funding = f_fr.result()

    return {
        "ok": True,
        "longPct": float(last["longAccount"]) * 100,
        "shortPct": float(last["shortAccount"]) * 100,
        "longShortRatio": float(last["longShortRatio"]),
        "series": series,
        "openInterest": oi_usd,
        "fundingRate": funding,
    }


# ============== BYBIT ==============

def _bybit_metrics(sym):
    j = http_get(f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={sym}")
    if j.get("retCode") != 0:
        return (None, None)
    lst = (j.get("result") or {}).get("list") or []
    if not lst:
        return (None, None)
    t = lst[0]
    oi = None
    try:
        oi_val = t.get("openInterestValue")
        if oi_val:
            oi = float(oi_val)
        elif t.get("openInterest") and t.get("lastPrice"):
            oi = float(t["openInterest"]) * float(t["lastPrice"])
    except Exception:
        pass
    fr = None
    try:
        if t.get("fundingRate"):
            fr = float(t["fundingRate"]) * 100
    except Exception:
        pass
    return (oi, fr)


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

    metrics = safe(lambda: _bybit_metrics(sym))
    oi_usd, funding = metrics if metrics else (None, None)

    return {
        "ok": True,
        "longPct": long_pct,
        "shortPct": short_pct,
        "longShortRatio": (long_pct / short_pct) if short_pct else 0,
        "series": series,
        "openInterest": oi_usd,
        "fundingRate": funding,
    }


# ============== OKX ==============

def _okx_metrics(inst_id):
    oi = None
    fr = None
    try:
        j = http_get(f"https://www.okx.com/api/v5/public/open-interest?instId={inst_id}")
        if j.get("code") == "0" and j.get("data"):
            d = j["data"][0]
            if d.get("oiUsd"):
                oi = float(d["oiUsd"])
            elif d.get("oiCcy"):
                pj = http_get(f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}")
                if pj.get("code") == "0" and pj.get("data"):
                    price = float(pj["data"][0]["last"])
                    oi = float(d["oiCcy"]) * price
    except Exception:
        pass
    try:
        j = http_get(f"https://www.okx.com/api/v5/public/funding-rate?instId={inst_id}")
        if j.get("code") == "0" and j.get("data"):
            fr = float(j["data"][0]["fundingRate"]) * 100
    except Exception:
        pass
    return (oi, fr)


def fetch_okx(symbol, period, limit):
    ccy = symbol.upper().replace("USDT", "").replace("-USDT-SWAP", "")
    inst_id = f"{ccy}-USDT-SWAP"
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

    metrics = safe(lambda: _okx_metrics(inst_id))
    oi_usd, funding = metrics if metrics else (None, None)

    return {
        "ok": True,
        "longPct": long_pct,
        "shortPct": 100 - long_pct,
        "longShortRatio": last_ratio,
        "series": series,
        "openInterest": oi_usd,
        "fundingRate": funding,
    }


# ============== BITGET ==============

def _bitget_metrics(sym):
    oi = None
    fr = None
    try:
        j = http_get(f"https://api.bitget.com/api/v2/mix/market/open-interest?symbol={sym}&productType=USDT-FUTURES")
        if j.get("code") == "00000":
            data = j.get("data") or {}
            ol = data.get("openInterestList") or []
            if ol:
                qty = float(ol[0].get("size") or 0)
                tj = http_get(f"https://api.bitget.com/api/v2/mix/market/ticker?symbol={sym}&productType=USDT-FUTURES")
                if tj.get("code") == "00000" and tj.get("data"):
                    tdata = tj["data"]
                    if isinstance(tdata, list) and tdata:
                        tdata = tdata[0]
                    price = float(tdata.get("lastPr") or 0)
                    oi = qty * price if price else None
    except Exception:
        pass
    try:
        j = http_get(f"https://api.bitget.com/api/v2/mix/market/current-fund-rate?symbol={sym}&productType=USDT-FUTURES")
        if j.get("code") == "00000":
            data = j.get("data") or []
            if isinstance(data, list) and data:
                fr = float(data[0].get("fundingRate") or 0) * 100
            elif isinstance(data, dict):
                fr = float(data.get("fundingRate") or 0) * 100
    except Exception:
        pass
    return (oi, fr)


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

    metrics = safe(lambda: _bitget_metrics(sym))
    oi_usd, funding = metrics if metrics else (None, None)

    return {
        "ok": True,
        "longPct": long_pct,
        "shortPct": short_pct,
        "longShortRatio": (long_pct / short_pct) if short_pct else 0,
        "series": series,
        "openInterest": oi_usd,
        "fundingRate": funding,
    }


FETCHERS = {
    "binance": fetch_binance,
    "bybit":   fetch_bybit,
    "okx":     fetch_okx,
    "bitget":  fetch_bitget,
}


# ======================================================================
# HTTP HANDLER
# ======================================================================

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

        if path == "/healthz":
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


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    print(f"L/S Ratio Terminal v2 listening on {HOST}:{PORT}", flush=True)
    try:
        with ThreadedServer((HOST, PORT), LSHandler) as srv:
            srv.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.", flush=True)


if __name__ == "__main__":
    main()
