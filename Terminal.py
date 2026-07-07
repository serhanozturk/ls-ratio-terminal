"""
L/S RATIO TERMINAL - Cloud-Ready Server (v4.4)

v4.4: Whale Tracker duzeltmeleri:
- Pasif taraf takibi: her trade'de ALICI + SATICI cuzdanlari islenir
  (maker whale'ler artik kacmaz - kritik mantik duzeltmesi)
- WS FIN biti takibi: bozuk mesaj buffer'i zehirlemez, akis olmez
- Heartbeat: 30s sessizlikte ping (gereksiz reconnect biter)
- Socket sizintisi kapatildi (finally'de close)
- Cuzdan budama: >5000 kayitta 250K alti + 6h eski silinir; API sadece >=250K doner
- stats'a reconnects + status eklendi ("Yeniden: undefined" duzeldi)
- MEGA WHALE (>=5M) ayri bolum, en ustte, mor vurgu
=============================================
v4.3: Gece/gunduz modu eklendi (Screener ile ayni sistem). Tema butonu (header),
  localStorage'da saklanir (lst_theme), varsayilan KOYU. CSS degiskenleri ile
  acik/koyu palet; grafikler (Chart.js) tema-duyarli (themeColors helper, CSS
  degiskeninden okur). Sadece arayuz - Binance/veri mantigi DEGISMEDI, ban riski YOK.
=============================================
v4.2 (M2): account ve position ayrisma panelinde AYNI mumda hizalama.
- Iki ayri Binance endpoint'inin son noktalari farkli saate denk gelebilirdi
  -> ayrisma yaniltici oluyordu. Artik ortak en son mumda hizalanir.
- Hizalanamazsa (ortak mum yok) '⚠ uyumsuz saat'; 2 periyottan eskiyse '⚠ BAYAT';
  olusan mumsa 'canli mum', degilse 'kapanmis mum' etiketi.

v4 yenilikleri:
- Binance ban korumasi (418/429 yerel takip, max 30dk, otomatik toparlanma)
- TTL cache (90s) - tum borsa cagrilari; yenilemeler ve cift cagrilar bedava
- premiumIndex tek cagri (OI markPrice + funding birlesti)
- Gecici hatalarda 1 retry (5xx + ag hatasi)
- Divergence paneli hizalanmis mum etiketi (v4.2)
- OKX periyot fallback (15m/30m->5m, 4h->1H) + kartta not

v3: position ratio, ayrisma paneli, Binance grafigi, TR+UTC saat
Calistirma: python3 lst_app.py
"""

import http.server
import socketserver
import urllib.request
import urllib.parse
import urllib.error
import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor

PORT = int(os.environ.get("PORT", 8765))
HOST = "0.0.0.0"
USER_AGENT = "Mozilla/5.0 LSRatioTerminal/4.0"

# ===== Binance yerel ban takibi (K1) =====
# 418/429 yenirse Binance'e gitmeyi keser; ustune istek yagdirip bani uzatmaz.
# v4.1: Retry-After header'i VARSA tamamina uyulur (30dk cap YOK) - uzun banlarda
# 30dk'da bir yoklamak Binance tarafinda bani uzatiyordu. Header yoksa eski davranis.
_ban_until = 0.0
_BAN_DEFAULT_MAX = 1800    # header YOKSA varsayilan ust sinir (30dk)
_BAN_HEADER_MAX = 86400    # header VARSA bile mantikli ust sinir (1 gun, sacma degerlere karsi)

def _binance_banned():
    return time.time() < _ban_until

def _set_binance_ban(secs, from_header=False):
    global _ban_until
    cap = _BAN_HEADER_MAX if from_header else _BAN_DEFAULT_MAX
    secs = min(max(int(secs), 10), cap)
    until = time.time() + secs
    if until > _ban_until:
        _ban_until = until

# ===== TTL cache (K2) =====
_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL = 90  # saniye - 5dk yenileme + elle FETCH tekrarlarini bedavaya getirir


def http_get(url, timeout=10, retries=1):
    """Ham istek. Binance banliysa hic gitmez; 418/429'da ban koyar;
    5xx ve ag hatalarinda 1 kez tekrar dener (K4)."""
    is_binance = "fapi.binance.com" in url
    if is_binance and _binance_banned():
        raise RuntimeError("Binance gecici banli (yerel takip), istek atlandi")
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if is_binance and e.code in (418, 429):
                ra = 0
                try:
                    ra = int(e.headers.get("Retry-After") or 0)
                except Exception:
                    pass
                if ra > 0:
                    _set_binance_ban(ra, from_header=True)  # header'a TAM uy (v4.1)
                else:
                    _set_binance_ban(300 if e.code == 418 else 60)
                raise
            if e.code >= 500 and attempt < retries:
                time.sleep(0.5)
                continue
            raise
        except Exception:
            if attempt < retries:
                time.sleep(0.5)
                continue
            raise


def http_get_cached(url, timeout=10, ttl=CACHE_TTL):
    """TTL'li cache. Taze varsa istek atmaz. Istek basarisiz olursa ve eski
    cache varsa onu doner (izleme araci - eski veri hicten iyidir)."""
    now = time.time()
    with _cache_lock:
        ent = _cache.get(url)
        if ent and now < ent[0]:
            return ent[1]
    try:
        data = http_get(url, timeout=timeout)
        with _cache_lock:
            _cache[url] = (now + ttl, data)
        return data
    except Exception:
        with _cache_lock:
            ent = _cache.get(url)
            if ent:
                return ent[1]  # bayat ama mevcut
        raise


def safe(fn):
    try:
        return fn()
    except Exception:
        return None


# ============== BINANCE ==============
def _binance_metrics(sym):
    """OI (USD) + funding TEK premiumIndex cagrisiyla (K3 - eskiden 2 kez cekiliyordu).
    markPrice -> OI degerleme, lastFundingRate -> funding. Fallback'ler korundu."""
    oi = None
    fr = None
    mark = None
    prem = safe(lambda: http_get_cached(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}"))
    if prem:
        try:
            v = prem.get("lastFundingRate")
            if v not in (None, ""):
                fr = float(v) * 100
        except Exception:
            pass
        try:
            m = float(prem.get("markPrice") or 0)
            if m > 0:
                mark = m
        except Exception:
            pass
    # OI: miktar x fiyat (markPrice yoksa ticker fallback)
    try:
        oi_j = http_get_cached(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}")
        qty = float(oi_j.get("openInterest") or 0)
        if qty > 0:
            price = mark
            if not price:
                tj = safe(lambda: http_get_cached(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={sym}"))
                if tj:
                    try:
                        p = float(tj.get("price") or 0)
                        if p > 0:
                            price = p
                    except Exception:
                        pass
            if price:
                oi = qty * price
    except Exception:
        pass
    # OI fallback: notional hist
    if oi is None:
        j = safe(lambda: http_get_cached(f"https://fapi.binance.com/futures/data/openInterestHist?symbol={sym}&period=5m&limit=1"))
        if isinstance(j, list) and j:
            try:
                v = float(j[0].get("sumOpenInterestValue") or 0)
                if v > 0:
                    oi = v
            except Exception:
                pass
    # Funding fallback
    if fr is None:
        j = safe(lambda: http_get_cached(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={sym}&limit=1"))
        if isinstance(j, list) and j:
            try:
                fr = float(j[0].get("fundingRate") or 0) * 100
            except Exception:
                pass
    return (oi, fr)


def _binance_position(sym, period, limit):
    """Top trader POSITION ratio = pozisyon buyuklugu (para nerede).
    topLongShortPositionRatio: top trader'larin pozisyon notional oranı.
    Account ratio (kac hesap) ile FARKI ayrisma sinyali verir.
    Donus: (last_long_pct, series) veya (None, []) - bazi altcoinlerde yok."""
    try:
        url = (f"https://fapi.binance.com/futures/data/topLongShortPositionRatio"
               f"?symbol={sym}&period={period}&limit={limit}")
        data = http_get_cached(url)
        if not isinstance(data, list) or len(data) == 0:
            return (None, [])
        series = [{"t": int(d["timestamp"]), "longPct": float(d["longAccount"]) * 100} for d in data]
        last_long = float(data[-1]["longAccount"]) * 100
        return (last_long, series)
    except Exception:
        return (None, [])


# ===== M2: account/position ayni mumda hizalama + tazelik =====
_PERIOD_MS = {"5m": 300000, "15m": 900000, "30m": 1800000,
              "1h": 3600000, "4h": 14400000, "1d": 86400000}


def _align_account_position(acc_series, pos_series, period,
                            acc_last, pos_last, acc_last_t):
    """account ve position serilerini AYNI mumda hizala.
    Iki ayri Binance endpoint'i; son noktalari farkli saate denk gelebilir,
    hizasiz cikarma yaniltici ayrisma uretir.
    Donus: (acc_pct, pos_pct|None, last_ts_ms, aligned_bool)
      - position yoksa            -> (acc_last, None, acc_last_t, True)  account-only
      - ortak mum varsa           -> o mumun acc/pos degeri, aligned=True
      - ortak mum yoksa           -> bagimsiz [-1]'ler, aligned=False (uyari ile gosterilir)
    Zaman damgalari periyot kovasina yuvarlanir (ayni grid icin guvence)."""
    if not pos_series or pos_last is None:
        return (acc_last, None, acc_last_t, True)
    step = _PERIOD_MS.get(period, 3600000)

    def bucket(t):
        return int(t) - (int(t) % step)

    acc_by_t = {}
    for p in acc_series:
        acc_by_t[bucket(p["t"])] = p["longPct"]
    pos_by_t = {}
    for p in pos_series:
        pos_by_t[bucket(p["t"])] = p["longPct"]
    common = sorted(set(acc_by_t) & set(pos_by_t))
    if common:
        t = common[-1]
        return (acc_by_t[t], pos_by_t[t], t, True)
    # ortak mum yok: hizasiz, bagimsiz son noktalar (UI uyari rozetiyle gosterir)
    return (acc_last, pos_last, acc_last_t, False)


def _freshness(last_ts, period, now_ms):
    """Hizalanmis mumun tazeligi. (forming, stale):
      forming = su an olusan (canli) mum   -> yas < 1 periyot
      stale   = 2 periyottan eski (bayat)  -> yas > 2 periyot
    Aradaki (son kapanmis mum) ikisi de False."""
    if not last_ts:
        return (False, False)
    step = _PERIOD_MS.get(period, 3600000)
    age = now_ms - last_ts
    return (age < step, age > step * 2)


def fetch_binance(symbol, period, limit):
    sym = symbol.upper().replace("USDT", "") + "USDT"
    period_map = {"5m":"5m","15m":"15m","30m":"30m","1h":"1h","4h":"4h","1d":"1d"}
    p = period_map.get(period, "1h")
    url = (f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
           f"?symbol={sym}&period={p}&limit={limit}")
    data = http_get_cached(url)
    if not isinstance(data, list) or len(data) == 0:
        raise RuntimeError("NO DATA")
    series = [{"t": int(d["timestamp"]), "longPct": float(d["longAccount"]) * 100} for d in data]
    acc_last_t = series[-1]["t"]
    acc_last_long = float(data[-1]["longAccount"]) * 100
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_m = ex.submit(safe, lambda: _binance_metrics(sym))
        f_pos = ex.submit(lambda: _binance_position(sym, p, limit))
        metrics = f_m.result()
        oi_usd, funding = metrics if metrics else (None, None)
        pos_long, pos_series = f_pos.result()

    # M2: account ve position'i AYNI mumda hizala (bagimsiz [-1]'ler farkli saatte olabilir)
    acc, pos_aligned, last_ts, aligned = _align_account_position(
        series, pos_series, p, acc_last_long, pos_long, acc_last_t)

    # Ayrisma: position - account (pozitif = para hesaplardan daha long = whale long/retail short)
    divergence = None
    if pos_aligned is not None:
        divergence = pos_aligned - acc

    # Account karti da hizalanmis muma gore (longShortRatio = long%/short%, tam)
    short_pct = 100 - acc
    lsr = (acc / short_pct) if short_pct > 0 else None

    # Tazelik: yalniz hizali ise anlamli (hizasizda UI '⚠ uyumsuz saat' gosterir)
    now_ms = int(time.time() * 1000)
    forming, stale = _freshness(last_ts, p, now_ms) if aligned else (False, False)
    pos_last_t = pos_series[-1]["t"] if pos_series else None

    return {
        "ok": True,
        "longPct": acc,
        "shortPct": short_pct,
        "longShortRatio": lsr,
        "series": series,
        "openInterest": oi_usd,
        "fundingRate": funding,
        # position (pozisyon buyuklugu) + ayrisma
        "positionLongPct": pos_aligned,
        "positionShortPct": (100 - pos_aligned) if pos_aligned is not None else None,
        "positionSeries": pos_series,
        "divergence": divergence,
        # M2: hizalama + tazelik
        "lastTs": last_ts,     # hizalanmis mumun zamani (ms)
        "aligned": aligned,    # account+position ayni mumda mi
        "forming": forming,    # hizali mum su an olusan (canli) mu
        "stale": stale,        # 2 periyottan eski mi (bayat)
        "accTs": acc_last_t,   # teshis: account son noktasi
        "posTs": pos_last_t,   # teshis: position son noktasi
    }


# ============== BYBIT ==============
def _bybit_metrics(sym):
    j = http_get_cached(f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={sym}")
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
    j = http_get_cached(url)
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
        "ok": True, "longPct": long_pct, "shortPct": short_pct,
        "longShortRatio": (long_pct / short_pct) if short_pct else 0,
        "series": series, "openInterest": oi_usd, "fundingRate": funding,
    }


# ============== OKX ==============
def _okx_metrics(inst_id):
    oi = None; fr = None
    try:
        j = http_get_cached(f"https://www.okx.com/api/v5/public/open-interest?instId={inst_id}")
        if j.get("code") == "0" and j.get("data"):
            d = j["data"][0]
            if d.get("oiUsd"):
                oi = float(d["oiUsd"])
            elif d.get("oiCcy"):
                pj = http_get_cached(f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}")
                if pj.get("code") == "0" and pj.get("data"):
                    price = float(pj["data"][0]["last"])
                    oi = float(d["oiCcy"]) * price
    except Exception:
        pass
    try:
        j = http_get_cached(f"https://www.okx.com/api/v5/public/funding-rate?instId={inst_id}")
        if j.get("code") == "0" and j.get("data"):
            fr = float(j["data"][0]["fundingRate"]) * 100
    except Exception:
        pass
    return (oi, fr)


def fetch_okx(symbol, period, limit):
    ccy = symbol.upper().replace("USDT", "").replace("-USDT-SWAP", "")
    inst_id = f"{ccy}-USDT-SWAP"
    # OKX rubik endpoint'i SADECE 5m / 1H / 1D destekler (M3).
    # Desteklenmeyen periyotlarda en yakina dus + ayni zaman penceresini korumak
    # icin limit'i carparak iste (15m->5m: x3, 30m->5m: x6, 4h->1H: x4).
    okx_map = {"5m": "5m", "15m": "5m", "30m": "5m", "1h": "1H", "4h": "1H", "1d": "1D"}
    factor_map = {"15m": 3, "30m": 6, "4h": 4}
    p = okx_map.get(period, "1H")
    eff_limit = min(limit * factor_map.get(period, 1), 500)
    period_note = None
    if period in factor_map:
        period_note = f"OKX {period} desteklemiyor - {p} verisi gosteriliyor"
    url = (f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio"
           f"?ccy={ccy}&period={p}&limit={eff_limit}")
    j = http_get_cached(url)
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
        "ok": True, "longPct": long_pct, "shortPct": 100 - long_pct,
        "longShortRatio": last_ratio, "series": series,
        "openInterest": oi_usd, "fundingRate": funding,
        "periodNote": period_note,
    }


# ============== BITGET ==============
def _bitget_metrics(sym):
    oi = None; fr = None
    try:
        j = http_get_cached(f"https://api.bitget.com/api/v2/mix/market/open-interest?symbol={sym}&productType=USDT-FUTURES")
        if j.get("code") == "00000":
            data = j.get("data") or {}
            ol = data.get("openInterestList") or []
            if ol:
                qty = float(ol[0].get("size") or 0)
                tj = http_get_cached(f"https://api.bitget.com/api/v2/mix/market/ticker?symbol={sym}&productType=USDT-FUTURES")
                if tj.get("code") == "00000" and tj.get("data"):
                    tdata = tj["data"]
                    if isinstance(tdata, list) and tdata:
                        tdata = tdata[0]
                    price = float(tdata.get("lastPr") or 0)
                    oi = qty * price if price else None
    except Exception:
        pass
    try:
        j = http_get_cached(f"https://api.bitget.com/api/v2/mix/market/current-fund-rate?symbol={sym}&productType=USDT-FUTURES")
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
    j = http_get_cached(url)
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
        "ok": True, "longPct": long_pct, "shortPct": short_pct,
        "longShortRatio": (long_pct / short_pct) if short_pct else 0,
        "series": series, "openInterest": oi_usd, "fundingRate": funding,
    }


FETCHERS = {
    "binance": fetch_binance,
    "bybit": fetch_bybit,
    "okx": fetch_okx,
    "bitget": fetch_bitget,
}


DASHBOARD_HTML = '''<!DOCTYPE html>
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
--accent: #6df5d4; --amber: #ffb83d;
--binance: #f3ba2f; --bybit: #ff4d6d; --okx: #ffffff; --bitget: #6df5d4;
}
body.light {
--bg: #f4f6f5; --bg-2: #ffffff;
--border: #dde3e1; --border-strong: #c4cecb;
--text: #1a2422; --text-dim: #6e7976; --text-faint: #a8b2af;
--green: #00a37a; --red: #e0334f; --red-dim: #c42d44;
--accent: #0a9b7d; --amber: #d4920f;
--binance: #c99617; --bybit: #e0334f; --okx: #1a2422; --bitget: #0a9b7d;
}
body.light::before { background: radial-gradient(ellipse at top left, rgba(0,163,122,0.05), transparent 50%),
radial-gradient(ellipse at bottom right, rgba(224,51,79,0.04), transparent 50%); }
body.light::after { background-image: linear-gradient(rgba(0,0,0,0.025) 1px, transparent 1px),
linear-gradient(90deg, rgba(0,0,0,0.025) 1px, transparent 1px); }
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
.theme-btn { background:transparent; border:1px solid var(--border-strong); color:var(--text);
border-radius:6px; width:30px; height:30px; cursor:pointer; font-size:14px; line-height:1;
display:flex; align-items:center; justify-content:center; transition:border-color 0.2s; }
.theme-btn:hover { border-color:var(--text-dim); }
.meta .clocks { display:flex; flex-direction:column; gap:2px; text-align:right; }
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
.card.ex-bybit { border-top-color: var(--bybit); }
.card.ex-okx { border-top-color: var(--okx); }
.card.ex-bitget { border-top-color: var(--bitget); }
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
.chart-canvas-box.small { height:300px; }
.legend-pills { display:flex; gap:16px; flex-wrap:wrap; margin-top:12px; font-size:11px; }
.legend-pills span { display:flex; align-items:center; gap:6px; color:var(--text-dim); }
.legend-pills .swatch { width:14px; height:3px; }
/* AYRISMA PANELI */
.diverge { background:var(--bg-2); border:1px solid var(--border);
border-left:3px solid var(--binance); padding:18px; margin-top:12px; }
.diverge-head { font-size:12px; letter-spacing:0.1em; color:var(--text); font-weight:700; margin-bottom:14px; }
.diverge-head .sub { color:var(--text-dim); font-weight:400; font-size:10px; letter-spacing:0.05em; }
.dv-rows { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
.dv-block { }
.dv-label { font-size:10px; letter-spacing:0.12em; color:var(--text-dim); text-transform:uppercase; margin-bottom:6px; }
.dv-val { font-size:16px; font-weight:500; }
.dv-val .lng { color:var(--green); }
.dv-val .sep { color:var(--text-faint); margin:0 6px; }
.dv-val .sht { color:var(--red); }
.dv-bar { margin-top:6px; height:4px; background:var(--red-dim); position:relative; overflow:hidden; }
.dv-bar .fill { position:absolute; left:0; top:0; bottom:0; background:var(--green); transition:width 0.6s; }
.dv-summary { margin-top:16px; padding-top:14px; border-top:1px solid var(--border);
display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; }
.dv-diff { font-size:13px; }
.dv-diff b { font-size:18px; }
.dv-tag { font-size:11px; font-weight:700; letter-spacing:0.08em; padding:6px 12px; border:1px solid; }
.dv-tag.whale-long { color:var(--green); border-color:var(--green); }
.dv-tag.whale-short { color:var(--red); border-color:var(--red); }
.dv-tag.aligned { color:var(--text-dim); border-color:var(--border-strong); }
.dv-tag.strong { box-shadow:0 0 12px currentColor; }
.dv-none { color:var(--text-faint); font-size:11px; padding:8px 0; }
.dv-fresh-warn { color:var(--red); font-weight:700; }
.dv-fresh-live { color:var(--green); }
.dv-fresh-dim { color:var(--text-dim); }
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
.chart-canvas-box.small { height:260px; }
.dv-rows { grid-template-columns:1fr; }
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
<button class="theme-btn" id="themeBtn" title="Tema">&#9789;</button>
<span><span class="dot"></span>LIVE</span>
<div class="clocks">
<span id="clockTR">--.-- --:--:-- TR</span>
<span id="clockUTC">--.-- --:--:-- UTC</span>
</div>
</div>
</header>

<div style="display:flex;gap:0;border-bottom:1px solid var(--border);margin-bottom:20px">
<a href="/" style="display:block;padding:9px 16px;font-size:11px;letter-spacing:0.08em;text-decoration:none;color:var(--green);border-bottom:2px solid var(--green);margin-bottom:-1px;font-weight:700">L/S TERMINAL</a>
<a href="/whale" style="display:block;padding:9px 16px;font-size:11px;letter-spacing:0.08em;text-decoration:none;color:var(--text-dim);border-bottom:2px solid transparent;margin-bottom:-1px">&#x1F40B; WHALE</a>
</div>

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

<h2 class="section"><span class="arrow">&#9656;</span>POZISYON vs HESAP AYRISMASI</h2>
<div class="diverge" id="divergePanel">
<div class="diverge-head">BINANCE &mdash; KALABALIK (HESAP) vs PARA (POZISYON) <span class="sub">top trader pozisyon buyuklugu</span></div>
<div id="divergeBody">
<div class="dv-none">Veri bekleniyor...</div>
</div>
</div>

<h2 class="section"><span class="arrow">&#9656;</span>EXCHANGE BREAKDOWN</h2>
<div class="grid" id="cards"></div>

<h2 class="section"><span class="arrow">&#9656;</span>TIME SERIES &middot; LONG ACCOUNT % (TUM BORSALAR)</h2>
<div class="chart-wrap">
<div class="chart-head">
<h3>HISTORICAL ACCOUNT RATIO</h3>
<div class="timeframe" id="tf">
<button data-limit="30">30P</button>
<button data-limit="60" class="active">60P</button>
<button data-limit="120">120P</button>
</div>
</div>
<div class="chart-canvas-box"><canvas id="chart"></canvas></div>
<div class="legend-pills" id="legendPills"></div>
</div>

<h2 class="section"><span class="arrow">&#9656;</span>BINANCE &middot; HESAP vs POZISYON AYRISMA GRAFIGI</h2>
<div class="chart-wrap">
<div class="chart-head">
<h3>ACCOUNT (kalabalik) vs POSITION (para)</h3>
</div>
<div class="chart-canvas-box small"><canvas id="chartBinance"></canvas></div>
<div class="legend-pills" id="legendPillsBinance"></div>
</div>

<div class="info">
<b>NASIL CALISIR?</b> Bu terminal Binance, Bybit, OKX ve Bitget public futures API'lerini sorgular. Hicbir API key gerekmez.<br><br>
<b>METRIKLER:</b><br>
&bull; <b>Account L/S</b>: Long/Short HESAP orani (kac kisi). Her hesap 1 oy, pozisyon buyuklugu onemsiz.<br>
&bull; <b>Position L/S (sadece Binance)</b>: Top trader'larin POZISYON buyuklugu (para nerede). Notional agirlikli.<br>
&bull; <b>AYRISMA</b>: Position - Account farki. Buyuk fark = kalabalik ile para ters yonde. Pozitif = whale long/retail short.<br>
&bull; <b>Open Interest</b>: Acik pozisyonlarin toplam USD degeri.<br>
&bull; <b>Funding Rate</b>: Pozitif = longlar oduyor (asiri boga); negatif = shortlar oduyor (asiri ayi).<br><br>
<b>NEDEN ONEMLI?</b> Account %70 short ama funding pozitif olabilir: cok sayida kucuk hesap short (retail), az sayida buyuk para long (whale). Ayrisma bunu yakalar.<br><br>
<b>YASAL UYARI:</b> Bu arac finansal tavsiye degildir. Metrikler tek baslarina sinyal degildir; fiyat aksiyonu ile birlikte degerlendirilmelidir.
</div>
</div>
<script>
const EXCHANGES = ['Binance', 'Bybit', 'OKX', 'Bitget'];
const COLORS = { Binance: '#f3ba2f', Bybit: '#ff4d6d', OKX: '#ffffff', Bitget: '#6df5d4' };
let chart = null;
let chartBinance = null;
let lastFetch = null;

function cleanSymbol(raw) { return (raw || '').toUpperCase().replace(/[^A-Z0-9]/g, ''); }

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
if (n == null || isNaN(n)) return '—';
const abs = Math.abs(n);
if (abs >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
if (abs >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
if (abs >= 1e3) return '$' + (n / 1e3).toFixed(2) + 'K';
return '$' + n.toFixed(2);
}

function fmtFunding(pct) {
if (pct == null || isNaN(pct)) return { text: '—', cls: '' };
const sign = pct >= 0 ? '+' : '';
return { text: sign + pct.toFixed(4) + '%', cls: pct > 0 ? 'fr-pos' : (pct < 0 ? 'fr-neg' : '') };
}

// ===== AYRISMA PANELI =====
function renderDivergence(binance) {
const body = document.getElementById('divergeBody');
if (!binance || !binance.ok) {
body.innerHTML = '<div class="dv-none">Binance verisi alinamadi</div>';
return;
}
const acc = binance.longPct;
const pos = binance.positionLongPct;
const fr = fmtFunding(binance.fundingRate);

// M2: hizalanmis mum zamani (TR). account ve position AYNI mumdan alinir.
// Hizasizsa '⚠ uyumsuz saat'; bayatsa '⚠ BAYAT'; olusan mumsa 'canli mum'.
let lastTxt = '';
if (binance.lastTs) {
const ld = new Date(binance.lastTs + 3*3600*1000);
const z = n => String(n).padStart(2, '0');
let tag, cls;
if (binance.aligned === false) { tag = '⚠ uyumsuz saat'; cls = 'dv-fresh-warn'; }
else if (binance.stale) { tag = '⚠ BAYAT'; cls = 'dv-fresh-warn'; }
else if (binance.forming) { tag = 'canli mum'; cls = 'dv-fresh-live'; }
else { tag = 'kapanmis mum'; cls = 'dv-fresh-dim'; }
lastTxt = `<div style="margin-top:10px;font-size:10px;color:var(--text-faint)">son veri: ${z(ld.getUTCDate())}.${z(ld.getUTCMonth()+1)} ${z(ld.getUTCHours())}:${z(ld.getUTCMinutes())} TR <span class="${cls}">(${tag})</span></div>`;
}

// Position yoksa: account goster, position bos
if (pos == null) {
body.innerHTML = `
<div class="dv-rows">
<div class="dv-block">
<div class="dv-label">HESAP (kalabalik)</div>
<div class="dv-val"><span class="lng">L ${acc.toFixed(1)}%</span><span class="sep">/</span><span class="sht">S ${(100-acc).toFixed(1)}%</span></div>
<div class="dv-bar"><div class="fill" style="width:${acc}%"></div></div>
</div>
<div class="dv-block">
<div class="dv-label">POZISYON (para)</div>
<div class="dv-val" style="color:var(--text-faint)">bu coinde yok</div>
</div>
</div>
<div class="dv-summary">
<div class="dv-diff">FUNDING: <b class="${fr.cls}" style="font-size:13px">${fr.text}</b></div>
<div class="dv-tag aligned">POSITION VERISI YOK</div>
</div>${lastTxt}`;
return;
}

const diff = pos - acc; // pozitif = position daha long = whale long
const absDiff = Math.abs(diff);
// Kademeli: 0-5 uyumlu, 5-10 hafif, 10+ guclu
let level, levelTxt;
if (absDiff < 5) { level = 'aligned'; levelTxt = 'UYUMLU'; }
else if (absDiff < 10) { level = (diff > 0 ? 'whale-long' : 'whale-short'); levelTxt = 'HAFIF AYRISMA'; }
else { level = (diff > 0 ? 'whale-long' : 'whale-short') + ' strong'; levelTxt = 'GUCLU AYRISMA'; }

let dirTxt;
if (absDiff < 5) dirTxt = 'KALABALIK = PARA';
else if (diff > 0) dirTxt = 'WHALE LONG, RETAIL SHORT';
else dirTxt = 'WHALE SHORT, RETAIL LONG';

const diffSign = diff >= 0 ? '+' : '';
body.innerHTML = `
<div class="dv-rows">
<div class="dv-block">
<div class="dv-label">HESAP (kalabalik)</div>
<div class="dv-val"><span class="lng">L ${acc.toFixed(1)}%</span><span class="sep">/</span><span class="sht">S ${(100-acc).toFixed(1)}%</span></div>
<div class="dv-bar"><div class="fill" style="width:${acc}%"></div></div>
</div>
<div class="dv-block">
<div class="dv-label">POZISYON (para, top trader)</div>
<div class="dv-val"><span class="lng">L ${pos.toFixed(1)}%</span><span class="sep">/</span><span class="sht">S ${(100-pos).toFixed(1)}%</span></div>
<div class="dv-bar"><div class="fill" style="width:${pos}%"></div></div>
</div>
</div>
<div class="dv-summary">
<div class="dv-diff">AYRISMA: <b class="${diff>0?'lng':'sht'}" style="color:${diff>0?'var(--green)':'var(--red)'}">${diffSign}${diff.toFixed(1)}%</b>
<span style="color:var(--text-dim);margin-left:10px">FUNDING: <span class="${fr.cls}">${fr.text}</span></span></div>
<div class="dv-tag ${level}">${dirTxt} &middot; ${levelTxt}</div>
</div>${lastTxt}`;
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
// Binance icin position satiri da ekle
let posRow = '';
if (ex === 'Binance' && r.positionLongPct != null) {
posRow = `<div class="ratio-row"><span class="l">POSITION L (para)</span><span class="v" style="color:var(--amber)">${r.positionLongPct.toFixed(2)}%</span></div>`;
}
card.innerHTML = `
<div class="card-head">
<div class="ex-name">${ex.toUpperCase()}</div>
<div class="ex-status ok">● ONLINE</div>
</div>
<div class="ratio-row"><span class="l">L/S RATIO</span><span class="v">${r.longShortRatio.toFixed(3)}</span></div>
<div class="ratio-row"><span class="l">ACCOUNT L (kalabalik)</span><span class="v">${r.longPct.toFixed(2)}%</span></div>
${posRow}
<div class="pct-bar"><div class="fill" style="width:${r.longPct}%"></div></div>
<div class="pct-vals"><span class="lng">▲ ${r.longPct.toFixed(1)}%</span><span class="sht">▼ ${r.shortPct.toFixed(1)}%</span></div>
<div class="divider"></div>
<div class="ratio-row"><span class="l">OPEN INTEREST</span><span class="v">${oi}</span></div>
<div class="ratio-row"><span class="l">FUNDING RATE</span><span class="v ${fr.cls}">${fr.text}</span></div>
${r.periodNote ? `<div class="err-msg" style="color:var(--amber);opacity:0.85">${r.periodNote}</div>` : ''}
`;
} else {
const msg = r?.error || 'NO DATA';
card.innerHTML = `
<div class="card-head">
<div class="ex-name">${ex.toUpperCase()}</div>
<div class="ex-status err">● NO DATA</div>
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
document.getElementById('aggLong').textContent = '—';
document.getElementById('aggShort').textContent = '—';
document.getElementById('aggBar').style.width = '0%';
return;
}
const avgLong = ok.reduce((s, ex) => s + results[ex].longPct, 0) / ok.length;
document.getElementById('aggLong').textContent = avgLong.toFixed(2) + '%';
document.getElementById('aggShort').textContent = (100 - avgLong).toFixed(2) + '%';
document.getElementById('aggBar').style.width = avgLong + '%';
}

function periodHours(p) {
return { '5m':5/60, '15m':15/60, '30m':30/60, '1h':1, '4h':4, '1d':24 }[p] || 1;
}

// ===== ANA GRAFIK: 4 borsa account + Binance position (kesik) =====
function renderChart(results, period, limit) {
const ctx = document.getElementById('chart');
const datasets = [];
const now = Date.now();
const windowMs = limit * periodHours(period) * 3600 * 1000;
const cutoff = now - windowMs;
EXCHANGES.forEach(ex => {
const r = results[ex];
if (!r?.ok || !r.series?.length) return;
const filtered = r.series.filter(p => p.t >= cutoff);
if (filtered.length === 0) return;
datasets.push({
label: ex, data: filtered.map(p => ({ x: p.t, y: p.longPct })),
borderColor: COLORS[ex], backgroundColor: COLORS[ex] + '22',
borderWidth: 1.8, pointRadius: 0, pointHoverRadius: 4, tension: 0.25, fill: false,
});
});
// Binance position cizgisi (kesik sari)
const b = results['Binance'];
if (b?.ok && b.positionSeries?.length) {
const pf = b.positionSeries.filter(p => p.t >= cutoff);
if (pf.length) {
datasets.push({
label: 'Binance POS', data: pf.map(p => ({ x: p.t, y: p.longPct })),
borderColor: '#f3ba2f', backgroundColor: 'transparent',
borderWidth: 1.6, borderDash: [6, 4], pointRadius: 0, pointHoverRadius: 4, tension: 0.25, fill: false,
});
}
}
if (chart) chart.destroy();
if (datasets.length === 0) {
document.getElementById('legendPills').innerHTML = '<span style="color:var(--text-faint)">veri yok</span>';
return;
}
chart = makeChart(ctx, datasets, cutoff, now, period);
document.getElementById('legendPills').innerHTML = datasets.map(d =>
`<span><span class="swatch" style="background:${d.borderColor}${d.borderDash?';border-top:2px dashed '+d.borderColor+';background:transparent':''}"></span>${d.label}</span>`
).join('');
}

// ===== IKINCI GRAFIK: Binance account vs position =====
function renderBinanceChart(results, period, limit) {
const ctx = document.getElementById('chartBinance');
const b = results['Binance'];
const now = Date.now();
const windowMs = limit * periodHours(period) * 3600 * 1000;
const cutoff = now - windowMs;
const datasets = [];
if (b?.ok && b.series?.length) {
const af = b.series.filter(p => p.t >= cutoff);
if (af.length) datasets.push({
label: 'ACCOUNT (kalabalik)', data: af.map(p => ({ x: p.t, y: p.longPct })),
borderColor: '#6df5d4', backgroundColor: '#6df5d422',
borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25, fill: false,
});
}
if (b?.ok && b.positionSeries?.length) {
const pf = b.positionSeries.filter(p => p.t >= cutoff);
if (pf.length) datasets.push({
label: 'POSITION (para)', data: pf.map(p => ({ x: p.t, y: p.longPct })),
borderColor: '#f3ba2f', backgroundColor: '#f3ba2f22',
borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.25, fill: false,
});
}
if (chartBinance) chartBinance.destroy();
const lp = document.getElementById('legendPillsBinance');
if (datasets.length === 0) {
lp.innerHTML = '<span style="color:var(--text-faint)">position verisi yok (bu coinde account vs position karsilastirilamaz)</span>';
return;
}
chartBinance = makeChart(ctx, datasets, cutoff, now, period);
lp.innerHTML = datasets.map(d =>
`<span><span class="swatch" style="background:${d.borderColor}"></span>${d.label}</span>`
).join('');
}

// Ozel tooltip konumu: sol-ust kosede sabit (veride hareket genelde sagda olur, sol-ust bos)
// Crosshair dikey cizgisi zaten X noktasini gosterir, tooltip kenarda durur -> nokta kapanmaz
if (window.Chart && Chart.Tooltip && Chart.Tooltip.positioners) {
Chart.Tooltip.positioners.topCenter = function(elements, eventPosition) {
const chart = this.chart;
return { x: chart.chartArea.left + 6, y: chart.chartArea.top + 6 };
};
}

// Dikey crosshair cizgisi (dokunulan X noktasini gosterir)
const crosshairPlugin = {
id: 'crosshair',
afterDraw(chart) {
const tt = chart.tooltip;
if (tt && tt._active && tt._active.length) {
const ctx = chart.ctx;
const x = tt._active[0].element.x;
const top = chart.chartArea.top;
const bottom = chart.chartArea.bottom;
ctx.save();
ctx.beginPath();
ctx.moveTo(x, top);
ctx.lineTo(x, bottom);
ctx.lineWidth = 1;
ctx.strokeStyle = 'rgba(109,245,212,0.5)';
ctx.setLineDash([4, 4]);
ctx.stroke();
ctx.restore();
}
}
};

function themeColors() {
  // Aktif temadan (CSS degiskenlerinden) grafik renklerini oku
  const cs = getComputedStyle(document.body);
  const v = (n, fb) => (cs.getPropertyValue(n).trim() || fb);
  const light = document.body.classList.contains('light');
  return {
    text:   v('--text', '#d4dcd9'),
    dim:    v('--text-dim', '#6e7976'),
    faint:  v('--text-faint', '#3f4845'),
    border: v('--border', '#1f2a28'),
    grid:   light ? 'rgba(0,0,0,0.06)' : '#14201d',
    bg:     v('--bg', '#0a0e0d'),
    strong: v('--border-strong', '#2a3a37'),
  };
}

function makeChart(ctx, datasets, cutoff, now, period) {
const TC = themeColors();
return new Chart(ctx, {
type: 'line', data: { datasets },
plugins: [crosshairPlugin],
options: {
responsive: true, maintainAspectRatio: false,
interaction: { mode: 'index', intersect: false },
plugins: {
legend: { display: false },
tooltip: {
backgroundColor: TC.bg, borderColor: TC.strong, borderWidth: 1,
titleColor: TC.text, bodyColor: TC.text,
titleFont: { family: 'JetBrains Mono', size: 11 }, bodyFont: { family: 'JetBrains Mono', size: 11 },
padding: 10, caretPadding: 12,
// Tooltip'i SABIT konuma tasi (noktayi kapatmasin) - hep ust ortada
position: 'topCenter',
callbacks: {
title: (items) => {
// Tooltip basligi TR saati (timestamp + 3 saat)
if (!items.length) return '';
const tr = new Date(items[0].parsed.x + 3*3600*1000);
const z = n => String(n).padStart(2,'0');
return `${z(tr.getUTCDate())}.${z(tr.getUTCMonth()+1)} ${z(tr.getUTCHours())}:${z(tr.getUTCMinutes())} TR`;
},
label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(2)}%`
}
}
},
scales: {
x: { type: 'time', min: cutoff, max: now,
// Chart.js zaman islemlerini UTC'de yap (tick'ler UTC'de yuvarlanir),
// sonra callback'te +3 ile temiz TR gosterilir (cift kaydirma olmaz)
adapters: { date: { zone: 'UTC' } },
time: { displayFormats: { minute:'HH:mm', hour:'MM/dd HH:mm', day:'MM/dd' } },
grid: { color:TC.grid, drawTicks:false },
ticks: { color:TC.dim, font:{ family:'JetBrains Mono', size:10 }, maxTicksLimit: 6,
// Eksen etiketleri TR saati (timestamp + 3 saat). Tarayici diliminden bagimsiz.
callback: function(value) {
const tr = new Date(value + 3*3600*1000);
const z = n => String(n).padStart(2,'0');
return `${z(tr.getUTCMonth()+1)}/${z(tr.getUTCDate())} ${z(tr.getUTCHours())}:${z(tr.getUTCMinutes())}`;
} },
title: { display: true, text: 'TR (UTC+3)', color:TC.faint,
font:{ family:'JetBrains Mono', size:9 }, padding:{top:4} },
border: { color:TC.border } },
y: { min:0, max:100,
grid: { color:TC.grid, drawTicks:false },
ticks: { color:TC.dim, font:{ family:'JetBrains Mono', size:10 }, callback: (v) => v + '%' },
border: { color:TC.border } },
},
},
});
}

async function run() {
const rawInput = document.getElementById('symbolInput').value;
const sym = cleanSymbol(rawInput);
if (sym !== rawInput.trim().toUpperCase()) document.getElementById('symbolInput').value = sym;
if (!sym) return;
const period = document.getElementById('periodSelect').value;
const limit = +document.querySelector('#tf button.active').dataset.limit;
const btn = document.getElementById('runBtn');
btn.disabled = true; btn.textContent = 'FETCHING...';
document.getElementById('cards').innerHTML = EXCHANGES.map(ex => `
<div class="card ex-${ex.toLowerCase()}">
<div class="card-head"><div class="ex-name">${ex.toUpperCase()}</div>
<div class="ex-status blink">● LOADING</div></div>
<div class="ratio-row skeleton"><span class="l">L/S RATIO</span><span class="v">...</span></div>
</div>`).join('');

const promises = EXCHANGES.map(ex =>
fetchOne(ex, sym, period, limit).then(data => [ex, data])
.catch(err => [ex, { ok: false, error: err.message || String(err) }]));
const settled = await Promise.all(promises);
const results = Object.fromEntries(settled);
lastFetch = { sym, period, limit, results };

renderAggregate(sym, results);
renderDivergence(results['Binance']);
renderCards(results);
renderChart(results, period, limit);
renderBinanceChart(results, period, limit);

btn.disabled = false; btn.textContent = 'FETCH >';
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

// ===== SAAT: TR + UTC (tarih + saat). TR = UTC+3 =====
function tick() {
const d = new Date();
const z = n => String(n).padStart(2, '0');
// UTC
document.getElementById('clockUTC').textContent =
`${z(d.getUTCDate())}.${z(d.getUTCMonth()+1)}.${d.getUTCFullYear()} ${z(d.getUTCHours())}:${z(d.getUTCMinutes())}:${z(d.getUTCSeconds())} UTC`;
// TR = UTC + 3
const tr = new Date(d.getTime() + 3*3600*1000);
document.getElementById('clockTR').textContent =
`${z(tr.getUTCDate())}.${z(tr.getUTCMonth()+1)}.${tr.getUTCFullYear()} ${z(tr.getUTCHours())}:${z(tr.getUTCMinutes())}:${z(tr.getUTCSeconds())} TR`;
}
setInterval(tick, 1000); tick();

// ===== Gece/gunduz modu (Screener ile ayni sistem) =====
function applyTheme(light) {
  document.body.classList.toggle('light', light);
  document.getElementById('themeBtn').innerHTML = light ? '\u2600' : '\u263D';
  document.querySelector('meta[name=theme-color]').setAttribute('content', light ? '#f4f6f5' : '#0a0e0d');
  try { localStorage.setItem('lst_theme', light ? 'light' : 'dark'); } catch {}
  // Tema degisince grafikleri yeniden ciz (renkler CSS degiskenlerinden gelir)
  if (lastFetch) {
    try {
      renderChart(lastFetch.results, lastFetch.period, lastFetch.limit);
      renderBinanceChart(lastFetch.results, lastFetch.period, lastFetch.limit);
    } catch (e) {}
  }
}
document.getElementById('themeBtn').addEventListener('click', () => {
  applyTheme(!document.body.classList.contains('light'));
});
(function(){ let l=false; try{ l=localStorage.getItem('lst_theme')==='light'; }catch{}; applyTheme(l); })();

setInterval(() => { if (!document.hidden && lastFetch) run(); }, 300000);
document.addEventListener('visibilitychange', () => { if (!document.hidden && lastFetch) run(); });

run();
</script>
</body>
</html>
'''


MANIFEST_JSON = json.dumps({
    "name": "L/S Ratio Terminal", "short_name": "L/S Ratio", "start_url": "/",
    "display": "standalone", "background_color": "#0a0e0d", "theme_color": "#0a0e0d",
    "orientation": "portrait",
    "icons": [{
        "src": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 192 192'%3E%3Crect fill='%230a0e0d' width='192' height='192'/%3E%3Ctext x='96' y='110' font-family='monospace' font-size='48' font-weight='bold' fill='%2300d09c' text-anchor='middle'%3EL/S%3C/text%3E%3C/svg%3E",
        "sizes": "192x192", "type": "image/svg+xml"
    }]
})


class LSHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write(f" - {self.address_string()} - {format % args}\n")

    def _send(self, status, content_type, body_bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body_bytes)

    def _send_json(self, status, payload):
        self._send(status, "application/json; charset=utf-8", json.dumps(payload).encode("utf-8"))

    def _send_html(self, html):
        self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        q = urllib.parse.parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            self._send_html(DASHBOARD_HTML); return
        if path == "/manifest.json":
            self._send(200, "application/json; charset=utf-8", MANIFEST_JSON.encode("utf-8")); return
        if path == "/healthz":
            self._send_json(200, {"ok": True}); return
        if path.startswith("/api/whale/"):
            # whale route'lari; FETCHERS'a girmemeli
            sub = path[len("/api/whale/"):].strip("/").lower()
            if sub == "wallets":
                with _w_lock:
                    rows = [{"addr": k[0], "coin": k[1], "side": k[2],
                             "total": v["total"], "last_ts": v["last_ts"]}
                            for k, v in _w_wallets.items()
                            if v["total"] >= _W_WALLET_FLOOR]
                self._send_json(200, {"ok": True, "wallets": rows}); return
            if sub == "trades":
                with _w_lock:
                    trades = list(_w_recent)
                self._send_json(200, {"ok": True, "trades": trades}); return
            if sub == "stats":
                with _w_lock:
                    self._send_json(200, {
                        "ok": True, "msgs": _w_stats["msgs"],
                        "errors": _w_stats["errors"],
                        "reconnects": _w_stats["reconnects"],
                        "status": _w_stats["status"],
                        "uptime": int(time.time() - _w_stats["start"]),
                        "wallets": len(_w_wallets), "recent": len(_w_recent),
                    }); return
            self._send_json(404, {"ok": False, "error": "not found"}); return
        if path.startswith("/api/"):
            ex = path[len("/api/"):].strip("/").lower()
            if ex not in FETCHERS:
                self._send_json(404, {"ok": False, "error": f"unknown exchange: {ex}"}); return
            symbol = (q.get("symbol", [""])[0] or "").strip()
            period = (q.get("period", ["1h"])[0] or "1h").strip()
            try: limit = int(q.get("limit", ["60"])[0])
            except ValueError: limit = 60
            limit = max(1, min(limit, 500))
            if not symbol:
                self._send_json(400, {"ok": False, "error": "symbol required"}); return
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
        if path == "/whale":
            self._send_html(WHALE_HTML); return
        self._send_json(404, {"ok": False, "error": "not found"})


# ======================================================================
# WHALE TRACKER — Hyperliquid buyuk pozisyon takibi (Terminal eklentisi)
# Tamamen bagimsiz: Binance/borsa koduna SIFIR etki.
# Hyperliquid public REST, API key yok, ban riski yok.
# ======================================================================

_W_COINS      = ["BTC", "ETH"]
_W_SINGLE_MIN = 500_000    # tek islem esigi (USD)
_W_CUMUL_STEP = 1_000_000  # kumulatif adim
_W_MEGA       = 5_000_000  # MEGA esigi
_W_WS_HOST    = "api.hyperliquid.xyz"
_W_WS_PATH    = "/ws"
_W_RECONNECT  = 5          # saniye, baglanti kopunca bekle

_w_lock    = threading.Lock()
_w_seen    = set()
_w_recent  = []
_w_wallets = {}
_w_stats   = {"msgs": 0, "errors": 0, "reconnects": 0, "start": time.time(),
              "status": "basliyor"}


def _w_fmt_usd(v):
    if v >= 1_000_000: return f"{v/1_000_000:.2f}M"
    if v >= 1_000:     return f"{v/1_000:.0f}K"
    return f"{v:.0f}"


# ---- Saf stdlib WebSocket client (RFC 6455 minimal) ----
import socket as _socket, ssl as _ssl, base64 as _b64, struct as _struct, os as _os

def _ws_handshake(sock, host, path):
    key = _b64.b64encode(_os.urandom(16)).decode()
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("WS handshake bos yanit")
        resp += chunk
    if b"101" not in resp:
        raise ConnectionError(f"WS handshake basarisiz: {resp[:120]}")


def _ws_recv_frame(sock):
    """Bir frame oku. Donus: (payload|None, fin_bool).
    payload None ise (ping/pong/diger) yoksay. FIN biti fragman takibi icin."""
    def _read_exact(n):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("WS baglanti kapandi")
            buf += chunk
        return buf
    header = _read_exact(2)
    fin    = (header[0] & 0x80) != 0
    opcode = header[0] & 0x0F
    masked = (header[1] & 0x80) != 0
    length = header[1] & 0x7F
    if length == 126:
        length = _struct.unpack("!H", _read_exact(2))[0]
    elif length == 127:
        length = _struct.unpack("!Q", _read_exact(8))[0]
    mask_key = _read_exact(4) if masked else b""
    payload  = _read_exact(length)
    if masked:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    if opcode == 0x9:  # Ping -> Pong
        try: sock.sendall(bytes([0x8A, len(payload)]) + payload)
        except Exception: pass
        return (None, True)
    if opcode == 0x8:  # Close
        raise ConnectionError("WS sunucu kapatti")
    if opcode in (0x1, 0x0):  # Text / continuation
        return (payload, fin)
    return (None, True)


def _ws_send(sock, text):
    payload = text.encode()
    n = len(payload)
    mask = _os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    if n <= 125:
        hdr = bytes([0x81, 0x80 | n])
    elif n <= 65535:
        hdr = bytes([0x81, 0xFE]) + _struct.pack("!H", n)
    else:
        hdr = bytes([0x81, 0xFF]) + _struct.pack("!Q", n)
    sock.sendall(hdr + mask + masked)


def _w_ws_loop(coin):
    sub = json.dumps({"method": "subscribe",
                      "subscription": {"type": "trades", "coin": coin}})
    ping = json.dumps({"method": "ping"})
    while True:
        sock = None
        try:
            raw = _socket.create_connection((_W_WS_HOST, 443), timeout=30)
            ctx = _ssl.create_default_context()
            sock = ctx.wrap_socket(raw, server_hostname=_W_WS_HOST)
            # 30s recv timeout: sessizlikte heartbeat ping atmak icin
            # (Hyperliquid ~60s sessiz baglantilari kapatir)
            sock.settimeout(30)
            _ws_handshake(sock, _W_WS_HOST, _W_WS_PATH)
            _ws_send(sock, sub)
            with _w_lock:
                _w_stats["status"] = "baglandi"
            print(f"[whale] WS baglandi: {coin}", flush=True)
            buf = b""
            while True:
                try:
                    payload, fin = _ws_recv_frame(sock)
                except _socket.timeout:
                    # sessiz donem: heartbeat gonder, baglantiyi canli tut
                    _ws_send(sock, ping)
                    continue
                if payload is None:
                    continue
                buf += payload
                if not fin:
                    continue  # fragman devam ediyor, mesaj tamamlanmadi
                # mesaj TAMAM (FIN=1): parse et, basarili/basarisiz buf'i sifirla
                raw_msg, buf = buf, b""
                try:
                    msg = json.loads(raw_msg.decode())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue  # bozuk mesaj atildi; buffer temiz, akis devam
                with _w_lock:
                    _w_stats["msgs"] += 1
                data = msg.get("data")
                if isinstance(data, list):
                    for t in data:
                        _w_process(t)
                elif isinstance(data, dict):
                    _w_process(data)
        except Exception as e:
            with _w_lock:
                _w_stats["errors"]     += 1
                _w_stats["reconnects"] += 1
                _w_stats["status"]      = f"yeniden ({e})"
            print(f"[whale] WS hata ({coin}): {e} -- {_W_RECONNECT}s sonra yeniden", flush=True)
            time.sleep(_W_RECONNECT)
        finally:
            if sock is not None:
                try: sock.close()
                except Exception: pass


# Budama esikleri: sozluk sismesin, UI bogulmasin
_W_WALLET_FLOOR = 250_000   # bu altindaki cuzdanlar budanabilir + API'ye donmez
_W_WALLET_MAX   = 5000      # sozlukteki maksimum kayit; asilirsa kucuk/eski silinir
_w_prune_tick   = [0]       # islem sayaci (budamayi seyrek calistirmak icin)


def _w_prune_locked():
    """_w_lock TUTULURKEN cagrilir. Once esik alti + eski olanlari, gerekirse
    en dusuk toplamlilari sil."""
    if len(_w_wallets) <= _W_WALLET_MAX:
        return
    now_ms = int(time.time() * 1000)
    # 1) esik alti VE 6 saattir islem gormemis kayitlari at
    stale_cut = now_ms - 6 * 3600 * 1000
    for k in [k for k, v in _w_wallets.items()
              if v["total"] < _W_WALLET_FLOOR and v["last_ts"] < stale_cut]:
        del _w_wallets[k]
    # 2) hala fazlaysa: en dusuk toplamdan baslayarak sil (esik ustunu koru)
    if len(_w_wallets) > _W_WALLET_MAX:
        by_total = sorted(_w_wallets.items(), key=lambda kv: kv[1]["total"])
        for k, v in by_total:
            if len(_w_wallets) <= _W_WALLET_MAX:
                break
            if v["total"] >= _W_WALLET_FLOOR:
                break  # esik ustune dokunma
            del _w_wallets[k]


def _w_track_wallet(wallet, coin, side, usd, ts):
    """Bir cuzdanin bir yondeki birikimini guncelle.
    side: bu cuzdan icin islem yonu (B=long birikim, A=short birikim).
    Ters yon islem gelirse o cuzdanin ters sayaci sifirlanir."""
    key      = (wallet, coin, side)
    ters_key = (wallet, coin, "A" if side == "B" else "B")
    notify   = False
    is_mega  = False
    total    = 0.0
    with _w_lock:
        if ters_key in _w_wallets:
            del _w_wallets[ters_key]
        if key not in _w_wallets:
            _w_wallets[key] = {"total": 0.0, "notified_at": 0.0, "last_ts": ts}
        _w_wallets[key]["total"]   += usd
        _w_wallets[key]["last_ts"]  = ts
        total   = _w_wallets[key]["total"]
        steps_now      = int(total // _W_CUMUL_STEP)
        steps_notified = int(_w_wallets[key]["notified_at"] // _W_CUMUL_STEP) if _w_wallets[key]["notified_at"] > 0 else 0
        if steps_now > steps_notified and total >= _W_CUMUL_STEP:
            _w_wallets[key]["notified_at"] = total
            is_mega = total >= _W_MEGA
            notify  = True
        # seyrek budama (her 500 cagirimda bir)
        _w_prune_tick[0] += 1
        if _w_prune_tick[0] >= 500:
            _w_prune_tick[0] = 0
            _w_prune_locked()
    # Telegram buraya eklenecek (v2): notify/is_mega/total kullanilacak
    return notify, is_mega, total


def _w_process(t):
    coin = t.get("coin", "")
    if coin not in _W_COINS:
        return
    tid = t.get("tid")
    if tid is None:
        return
    with _w_lock:
        if tid in _w_seen:
            return
        _w_seen.add(tid)
        if len(_w_seen) > 100_000:
            _w_seen.clear()
            _w_seen.add(tid)
    try:
        px   = float(t.get("px", 0))
        sz   = float(t.get("sz", 0))
        side = t.get("side", "")
        users = t.get("users", [])
        ts   = int(t.get("time", time.time() * 1000))
    except Exception:
        return
    usd = px * sz
    if usd < 1000:
        return
    # users = [alici, satici] (agresor kim olursa olsun her trade'de ikisi de var)
    buyer  = users[0] if isinstance(users, list) and len(users) > 0 and users[0] else ""
    seller = users[1] if isinstance(users, list) and len(users) > 1 and users[1] else ""
    # Buyuk islem listesi: agresor tarafin cuzdaniyla goster
    display_addr = buyer if side == "B" else seller
    rec = {"tid": tid, "coin": coin, "side": side,
           "px": px, "sz": sz, "usd": usd, "addr": display_addr, "ts": ts}
    if usd >= _W_SINGLE_MIN:
        with _w_lock:
            _w_recent.insert(0, rec)
            if len(_w_recent) > 100:
                _w_recent.pop()
    # Kumulatif takip: HER IKI cuzdan da islenir (pasif/maker taraf kacmasin).
    # Alici -> LONG birikimi (B), satici -> SHORT birikimi (A).
    if buyer:
        _w_track_wallet(buyer, coin, "B", usd, ts)
    if seller:
        _w_track_wallet(seller, coin, "A", usd, ts)





WHALE_HTML = '''<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Whale Tracker</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;700&display=swap" rel="stylesheet">
<style>
:root{
--bg:#0a0e0d;--bg2:#0f1413;--bg3:#131a19;
--border:#1f2a28;--border2:#2a3a37;
--text:#d4dcd9;--dim:#6e7976;--faint:#2a3837;
--green:#00d09c;--red:#ff4d6d;--amber:#ffb83d;
--accent:#6df5d4;--mega:#d45cff;
--btc:#f7931a;--eth:#627eea;
}
body.light{
--bg:#f4f6f5;--bg2:#ffffff;--bg3:#eef0ef;
--border:#dde3e1;--border2:#c4cecb;
--text:#1a2422;--dim:#6e7976;--faint:#dde3e1;
--green:#00a37a;--red:#e0334f;--amber:#d4920f;
--accent:#0a9b7d;--mega:#8800cc;
--btc:#c0520a;--eth:#3a5bbb;
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{background:var(--bg);color:var(--text);font-family:"JetBrains Mono",monospace;
font-size:13px;line-height:1.5;min-height:100vh;-webkit-font-smoothing:antialiased;
transition:background .25s,color .25s}
.wrap{max-width:1100px;margin:0 auto;padding:20px;
padding-top:calc(20px + env(safe-area-inset-top));
padding-bottom:calc(60px + env(safe-area-inset-bottom))}
/* NAV */
.nav{display:flex;gap:0;margin-bottom:20px;border-bottom:1px solid var(--border)}
.nav a{display:block;padding:10px 18px;font-size:11px;letter-spacing:0.08em;
text-decoration:none;color:var(--dim);border-bottom:2px solid transparent;margin-bottom:-1px}
.nav a:hover{color:var(--text)}
.nav a.active{color:var(--green);border-bottom-color:var(--green);font-weight:700}
/* HEADER */
header{display:flex;align-items:center;justify-content:space-between;
padding-bottom:16px;border-bottom:1px solid var(--border);margin-bottom:20px;gap:12px;flex-wrap:wrap}
.logo{font-family:"JetBrains Mono",monospace;font-size:15px;font-weight:700;letter-spacing:0.06em}
.logo .wh{color:var(--accent)}
.header-right{display:flex;gap:10px;align-items:center}
.clocks{font-size:10px;color:var(--dim);text-align:right;line-height:1.7}
.theme-btn{background:transparent;border:1px solid var(--border2);color:var(--text);
font-size:15px;width:34px;height:34px;cursor:pointer}
.theme-btn:hover{border-color:var(--text)}
/* STATS */
.stats{display:flex;border:1px solid var(--border);margin-bottom:20px}
.stat{flex:1;padding:10px 14px;border-right:1px solid var(--border)}
.stat:last-child{border-right:none}
.stat-lbl{font-size:9px;color:var(--dim);letter-spacing:0.1em;text-transform:uppercase;margin-bottom:3px}
.stat-val{font-size:15px;font-weight:700}
.stat-val.g{color:var(--green)}.stat-val.r{color:var(--red)}.stat-val.a{color:var(--amber)}
/* STATUS */
.status{font-size:10px;color:var(--dim);margin-bottom:14px;display:flex;align-items:center;gap:6px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--green);
animation:blink 2s infinite;flex-shrink:0}
.dot.err{background:var(--red);animation:none}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}
/* SEC TITLE */
.sec{font-size:10px;color:var(--dim);letter-spacing:0.1em;text-transform:uppercase;
margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--border);
display:flex;align-items:center;justify-content:space-between}
.sec span{color:var(--text)}
.refresh-btn{background:transparent;border:1px solid var(--border2);color:var(--dim);
font-family:inherit;font-size:10px;padding:5px 10px;cursor:pointer;letter-spacing:0.04em}
.refresh-btn:hover{border-color:var(--green);color:var(--green)}
/* WALLETS TABLE */
.tbl-wrap{overflow-x:auto;margin-bottom:28px}
table{width:100%;border-collapse:collapse;font-size:11px;min-width:560px}
thead th{padding:7px 10px;text-align:left;color:var(--dim);font-size:9px;
letter-spacing:0.1em;text-transform:uppercase;border-bottom:1px solid var(--border);font-weight:400}
thead th.r{text-align:right}
tbody td{padding:8px 10px;border-bottom:1px solid var(--border)}
tbody td.r{text-align:right}
tbody tr:hover{background:var(--bg2)}
.cb{display:inline-block;padding:1px 6px;font-weight:700;font-size:10px;letter-spacing:0.04em}
.cb.BTC{background:var(--btc);color:#000}.cb.ETH{background:var(--eth);color:#fff}
.sl{color:var(--green);font-weight:700}.ss{color:var(--red);font-weight:700}
.addr{font-size:10px;color:var(--dim);word-break:break-all}
.uv{font-weight:700}
.bar-w{width:72px;height:3px;background:var(--faint);display:inline-block;vertical-align:middle;margin-left:6px}
.bar-f{height:3px;background:var(--accent)}
.mega-b{background:var(--mega);color:#fff;font-size:9px;padding:1px 5px;font-weight:700;margin-left:4px}
.empty{text-align:center;padding:24px 0;color:var(--dim)}
/* TRADES */
.trade{display:flex;align-items:flex-start;gap:10px;padding:8px 0;
border-bottom:1px solid var(--border);flex-wrap:wrap}
.trade:last-child{border-bottom:none}
.tr-s{width:76px;flex-shrink:0;font-weight:700;font-size:11px}
.tr-s.l{color:var(--green)}.tr-s.s{color:var(--red)}
.tr-u{font-weight:700;font-size:13px;min-width:86px}
.tr-d{font-size:10px;color:var(--dim);flex:1;min-width:130px}
.tr-a{font-size:9px;color:var(--faint);word-break:break-all;width:100%}
.tr-t{font-size:10px;color:var(--dim);min-width:56px;text-align:right;flex-shrink:0}
.pulse{animation:pls .8s ease-out}
@keyframes pls{from{background:var(--bg3)}to{background:transparent}}
@media(max-width:600px){
.stats{flex-wrap:wrap}.stat{min-width:50%}
.nav a{padding:8px 12px}
}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="logo">L/S TERMINAL &mdash; <span class="wh">&#x1F40B; WHALE</span></div>
  <div class="header-right">
    <div class="clocks"><div id="cTR">-- TR</div><div id="cUTC">-- UTC</div></div>
    <button class="theme-btn" id="themeBtn">&#9790;</button>
  </div>
</header>
<nav class="nav">
  <a href="/">L/S TERMINAL</a>
  <a href="/whale" class="active">&#x1F40B; WHALE</a>
</nav>
<div class="stats">
  <div class="stat"><div class="stat-lbl">Izlenen</div><div class="stat-val">BTC &amp; ETH</div></div>
  <div class="stat"><div class="stat-lbl">Buyuk Islem</div><div class="stat-val g" id="sBig">0</div></div>
  <div class="stat"><div class="stat-lbl">Aktif Cuzdan</div><div class="stat-val a" id="sWal">0</div></div>
  <div class="stat"><div class="stat-lbl">Hata</div><div class="stat-val r" id="sErr">0</div></div>
</div>
<div class="status"><div class="dot" id="dot"></div><span id="statusTxt">Baglaniyor...</span></div>
<div class="sec" style="color:var(--mega)">&#x1F988; MEGA WHALE (&ge;5M USD) <span id="mCnt"></span>
  <button class="refresh-btn" onclick="load()">&#8635; YENILE</button>
</div>
<div class="tbl-wrap">
<table>
  <thead><tr>
    <th>CUZDAN</th><th>COIN</th><th>YON</th>
    <th class="r">KUMULATIF</th><th class="r">SEVIYE</th>
  </tr></thead>
  <tbody id="mBody"><tr><td colspan="5" class="empty">Henuz MEGA whale yok</td></tr></tbody>
</table>
</div>

<div class="sec">AKTIF CUZDAN POZISYONLARI <span id="wCnt"></span></div>
<div class="tbl-wrap">
<table>
  <thead><tr>
    <th>CUZDAN</th><th>COIN</th><th>YON</th>
    <th class="r">KUMULATIF</th><th class="r">ILERLEME</th>
  </tr></thead>
  <tbody id="wBody"><tr><td colspan="5" class="empty">Bekleniyor...</td></tr></tbody>
</table>
</div>
<div class="sec">SON BUYUK ISLEMLER (&ge;500K USD) <span id="tCnt"></span></div>
<div id="tradeList"><div class="empty">Bekleniyor...</div></div>
</div>
<script>
var THEME_KEY = "lst_theme";
function applyTheme(t){
  document.body.className = t==="light"?"light":"";
  document.getElementById("themeBtn").innerHTML = t==="light"?"&#9790;":"&#9728;";
}
(function(){applyTheme(localStorage.getItem(THEME_KEY)||"dark");})();
document.getElementById("themeBtn").onclick=function(){
  var t=document.body.classList.contains("light")?"dark":"light";
  localStorage.setItem(THEME_KEY,t);applyTheme(t);
};
function pad(n){return n<10?"0"+n:n}
function tick(){
  var now=new Date();
  var trMs=now.getTime()+now.getTimezoneOffset()*60000+3*3600000;
  var tr=new Date(trMs);
  document.getElementById("cTR").textContent=pad(tr.getUTCHours())+":"+pad(tr.getUTCMinutes())+":"+pad(tr.getUTCSeconds())+" TR";
  document.getElementById("cUTC").textContent=pad(now.getUTCHours())+":"+pad(now.getUTCMinutes())+":"+pad(now.getUTCSeconds())+" UTC";
}
setInterval(tick,1000);tick();
function fmtUSD(v){
  if(v>=1e6)return(v/1e6).toFixed(2)+"M";
  if(v>=1e3)return(v/1e3).toFixed(0)+"K";
  return v.toFixed(0);
}
function fmtTime(ms){
  var d=new Date(ms+3*3600000);
  return pad(d.getUTCHours())+":"+pad(d.getUTCMinutes())+":"+pad(d.getUTCSeconds());
}
function walletRow(w,isMega){
  var sl=w.side==="B"?'<span class="sl">LONG</span>':'<span class="ss">SHORT</span>';
  var pct=Math.min(w.total/_W_MEGA*100,100);
  var bar='<div class="bar-w"><div class="bar-f" style="width:'+pct+'%'+(isMega?';background:var(--mega)':'')+'"></div></div>';
  var lvl=isMega?'<span class="mega-b">'+Math.floor(w.total/1e6)+'M</span>':Math.floor(w.total/1e6)+'M / 5M';
  return '<tr><td><span class="addr">'+w.addr+'</span></td>'+
    '<td><span class="cb '+w.coin+'">'+w.coin+'</span></td>'+
    '<td>'+sl+'</td>'+
    '<td class="r"><span class="uv"'+(isMega?' style="color:var(--mega)"':'')+'>'+fmtUSD(w.total)+'</span></td>'+
    '<td class="r">'+lvl+' '+bar+'</td></tr>';
}
function renderWallets(ws){
  ws.sort(function(a,b){return b.total-a.total;});
  var mega=ws.filter(function(w){return w.total>=_W_MEGA;});
  var norm=ws.filter(function(w){return w.total<_W_MEGA;});
  document.getElementById("sWal").textContent=ws.length;
  document.getElementById("mCnt").textContent=mega.length?"("+mega.length+")":"";
  document.getElementById("wCnt").textContent=norm.length?"("+norm.length+")":"";
  var mb=document.getElementById("mBody");
  mb.innerHTML=mega.length?mega.map(function(w){return walletRow(w,true);}).join(""):
    '<tr><td colspan="5" class="empty">Henuz MEGA whale yok</td></tr>';
  var tb=document.getElementById("wBody");
  tb.innerHTML=norm.length?norm.map(function(w){return walletRow(w,false);}).join(""):
    '<tr><td colspan="5" class="empty">Henuz kumulatif pozisyon yok</td></tr>';
}
function renderTrades(ts){
  document.getElementById("sBig").textContent=ts.length;
  document.getElementById("tCnt").textContent=ts.length?"("+ts.length+")":"";
  var el=document.getElementById("tradeList");
  if(!ts.length){el.innerHTML='<div class="empty">Henuz buyuk islem yok (&ge;500K USD)</div>';return;}
  el.innerHTML=ts.map(function(t,i){
    var isL=t.side==="B";
    var sc=t.coin==="BTC"?"color:var(--btc)":"color:var(--eth)";
    return '<div class="trade" id="tr'+i+'">'+
      '<div class="tr-s '+(isL?"l":"s")+'"><span style="'+sc+'">'+t.coin+'</span> '+(isL?"LONG":"SHORT")+'</div>'+
      '<div class="tr-u">'+fmtUSD(t.usd)+' USD</div>'+
      '<div class="tr-d">'+t.sz+' '+t.coin+' @ '+Number(t.px).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2})+'</div>'+
      '<div class="tr-t">'+fmtTime(t.ts)+'</div>'+
      '<div class="tr-a">'+t.addr+'</div>'+
      '</div>';
  }).join("");
}
var _W_MEGA=5000000;
var lastBig=0;
async function load(){
  try{
    var r=await Promise.all([
      fetch("/api/whale/wallets").then(function(r){return r.json();}),
      fetch("/api/whale/trades").then(function(r){return r.json();}),
      fetch("/api/whale/stats").then(function(r){return r.json();})
    ]);
    var dW=r[0],dT=r[1],dS=r[2];
    if(dW.ok)renderWallets(dW.wallets);
    if(dT.ok){
      if(dT.trades.length>lastBig){
        renderTrades(dT.trades);
        var first=document.querySelector(".trade");
        if(first)first.classList.add("pulse");
        lastBig=dT.trades.length;
      } else renderTrades(dT.trades);
    }
    if(dS.ok){
      document.getElementById("sErr").textContent=dS.errors;
      document.getElementById("dot").className="dot";
      document.getElementById("statusTxt").textContent=
        "WS Canli \u2014 "+_W_COINS.join(", ")+" \u2014 Mesaj: "+dS.msgs+" | Yeniden: "+dS.reconnects+" \u2014 "+new Date().toLocaleTimeString("tr-TR");
    }
  }catch(e){
    document.getElementById("dot").className="dot err";
    document.getElementById("statusTxt").textContent="Baglanti hatasi: "+e.message;
  }
}
var _W_COINS=["BTC","ETH"];
load();
setInterval(load,15000);
</script>
</body>
</html>
'''


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    print(f"L/S Ratio Terminal v4.4 listening on {HOST}:{PORT}", flush=True)
    for _coin in _W_COINS:
        threading.Thread(target=_w_ws_loop, args=(_coin,), daemon=True).start()
    print("[whale] WS stream basliyor (BTC+ETH) -- hic islem kacmaz", flush=True)
    try:
        with ThreadedServer((HOST, PORT), LSHandler) as srv:
            srv.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.", flush=True)


if __name__ == "__main__":
    main()
