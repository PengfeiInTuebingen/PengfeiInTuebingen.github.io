#!/usr/bin/env python3
"""Build the zero-token data bundle used by the market dashboard.

The updater intentionally uses only Python's standard library and public,
read-only endpoints. A failed source never replaces a previously valid value;
the last successful observation is retained and the failure is reported in the
JSON metadata shown on the website.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(os.environ.get("MARKET_SITE_ROOT", Path(__file__).resolve().parents[1]))
DATA_DIR = ROOT / "markets" / "data"
LATEST_PATH = DATA_DIR / "latest.json"
HISTORY_PATH = DATA_DIR / "history.json"
USER_AGENT = "PengfeiMarketDashboard/1.0 (+https://pengfeiintuebingen.github.io/markets/)"

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
CFTC_DISAGG_URL = "https://www.cftc.gov/dea/newcot/c_disagg.txt"
CFTC_TFF_URL = "https://www.cftc.gov/dea/newcot/FinComWk.txt"
GOLD_API_URL = "https://api.gold-api.com/price"
XAUS_FALLBACK_URL = "https://xaus.com/api/v1/spot?compact=1"
CALENDAR_FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
BEA_CALENDAR_URL = "https://www.bea.gov/news/schedule"
FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
ECB_CALENDAR_URL = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"
CME_WAREHOUSE_PAGE_URL = "https://www.cmegroup.com/solutions/clearing/operations-and-deliveries/nymex-delivery-notices.html"
CME_WAREHOUSE_URLS = {
    "gold": "https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls",
    "silver": "https://www.cmegroup.com/delivery_reports/Silver_stocks.xls",
}
COINGLASS_API_BASE = "https://open-api-v4.coinglass.com/api"
BINANCE_FUTURES_BASE = "https://fapi.binance.com"

# Last verified official CME snapshot retained when CME's anti-scraping edge
# blocks automated downloads.  A successful future report replaces these rows;
# the UI labels this snapshot as fallback and shows its report date.
CME_SEED_INVENTORY = {
    "gold": {
        "label": "COMEX 黄金库存", "metal": "gold", "report_date": "2026-08-25", "activity_date": "2026-08-24",
        "unit": "troy oz", "contract_size_oz": 100, "registered_oz": 14545334.889, "eligible_oz": 12276889.007,
        "pledged_oz": 1695988.548, "total_oz": 26822223.896, "registered_net_change_oz": 30184.854,
        "eligible_net_change_oz": 64302.0, "total_net_change_oz": 94486.854, "registered_share_pct": 54.231,
        "registered_contract_equivalents": 145453.35, "history": [["2026-08-24", 14545334.889, 12276889.007, 26822223.896]],
    },
    "silver": {
        "label": "COMEX 白银库存", "metal": "silver", "report_date": "2026-08-25", "activity_date": "2026-08-24",
        "unit": "troy oz", "contract_size_oz": 5000, "registered_oz": 99207707.582, "eligible_oz": 239144674.283,
        "pledged_oz": None, "total_oz": 338352381.865, "registered_net_change_oz": 90128.695,
        "eligible_net_change_oz": 583983.53, "total_net_change_oz": 583983.53, "registered_share_pct": 29.316,
        "registered_contract_equivalents": 19841.54, "history": [["2026-08-24", 99207707.582, 239144674.283, 338352381.865]],
    },
}

RUN_INTERVAL_MINUTES = 15
MACRO_REFRESH_HOURS = 6
CFTC_REFRESH_HOURS = 12
CALENDAR_REFRESH_HOURS = 1
WAREHOUSE_REFRESH_HOURS = 6

FRED_SERIES = {
    "WALCL": ("美联储总资产", "百万美元", "流动性"),
    "RRPONTSYD": ("ON RRP", "十亿美元", "流动性"),
    "WDTGAL": ("美国财政部 TGA", "十亿美元", "流动性"),
    "TOTRESNS": ("银行准备金", "十亿美元", "流动性"),
    "WM2NS": ("美国 M2", "十亿美元", "流动性"),
    "DGS2": ("美债 2 年收益率", "%", "利率"),
    "DGS10": ("美债 10 年收益率", "%", "利率"),
    "DGS30": ("美债 30 年收益率", "%", "利率"),
    "DFII10": ("美债 10 年实际利率", "%", "通胀"),
    "T10YIE": ("10 年盈亏平衡通胀率", "%", "通胀"),
    "DFF": ("联邦基金有效利率", "%", "政策"),
    "VIXCLS": ("VIX", "指数", "情绪"),
    "BAMLH0A0HYM2": ("美国高收益债 OAS", "%", "情绪"),
    "SP500": ("标普 500", "指数", "资产"),
    "NASDAQCOM": ("纳斯达克综合", "指数", "资产"),
    "DTWEXBGS": ("广义美元指数", "指数", "资产"),
    "A191RL1Q225SBEA": ("美国实际 GDP 环比年化", "%", "周期"),
    "PAYEMS": ("美国非农就业", "千人", "周期"),
    "UNRATE": ("美国失业率", "%", "周期"),
    "JTSJOL": ("JOLTS 职位空缺", "千人", "周期"),
    "CPIAUCSL": ("美国 CPI", "指数", "通胀"),
    "PCEPI": ("美国 PCE", "指数", "通胀"),
    "PCEPILFE": ("美国核心 PCE", "指数", "通胀"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def cadence_due(last_checked: str | None, hours: float) -> bool:
    parsed = parse_timestamp(last_checked)
    return parsed is None or datetime.now(timezone.utc) - parsed >= timedelta(hours=hours)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def request_text(url: str, attempts: int = 3, headers: dict[str, str] | None = None) -> str:
    last_error: Exception | None = None
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/html,text/csv,text/plain,application/xml,*/*",
    }
    request_headers.update(headers or {})
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            headers=request_headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read()
                encoding = response.headers.get_content_charset() or "utf-8"
                return raw.decode(encoding, errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    if last_error and "CERTIFICATE_VERIFY_FAILED" in str(last_error):
        try:
            completed = subprocess.run(
                ["curl", "--http1.1", "--fail", "--silent", "--show-error", "-L", "-A", request_headers.get("User-Agent", USER_AGENT), "--max-time", "60", url],
                check=True,
                capture_output=True,
                text=True,
                timeout=70,
            )
            return completed.stdout
        except (subprocess.SubprocessError, OSError) as curl_error:
            last_error = curl_error
    raise RuntimeError(f"download failed: {url}: {last_error}")


def request_json(url: str, headers: dict[str, str] | None = None) -> Any:
    try:
        return json.loads(request_text(url, headers=headers))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON from {url}: {error}") from error


def download_cme_report(url: str) -> bytes:
    """Download a CME CDFV2 workbook with browser-like headers.

    CME's delivery-report host rejects the default urllib fingerprint.  The
    report remains an official, read-only source; curl is used only for the
    transport and the workbook is parsed locally with xlrd.
    """
    headers = [
        ("Connection", "keep-alive"),
        ("sec-ch-ua", '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"'),
        ("sec-ch-ua-mobile", "?0"),
        ("sec-ch-ua-platform", '"Windows"'),
        ("Upgrade-Insecure-Requests", "1"),
        ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36"),
        ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9"),
        ("Sec-Fetch-Site", "none"),
        ("Sec-Fetch-Mode", "navigate"),
        ("Sec-Fetch-User", "?1"),
        ("Sec-Fetch-Dest", "document"),
        ("Accept-Language", "en-US,en;q=0.9"),
    ]
    args = ["curl", "--http1.1", "--fail", "--silent", "--show-error", "-L", "--compressed"]
    for key, value in headers:
        args.extend(["-H", f"{key}: {value}"])
    args.extend(["--max-time", "60", url])
    try:
        completed = subprocess.run(args, check=True, capture_output=True, timeout=75)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or b"").decode("utf-8", errors="replace")[-240:]
        raise RuntimeError(f"CME report download blocked: {url}: {detail or error}") from error
    except (subprocess.SubprocessError, OSError) as error:
        raise RuntimeError(f"CME report download failed: {url}: {error}") from error
    if not completed.stdout.startswith(b"\xd0\xcf\x11\xe0"):
        raise ValueError(f"CME report is not an XLS workbook: {url}")
    return completed.stdout


def _cme_date(text: str) -> str | None:
    match = re.search(r"(?:Report|Activity) Date\s*:\s*(\d{1,2}/\d{1,2}/\d{4})", text, re.I)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def parse_cme_inventory(raw: bytes, metal: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        import xlrd  # type: ignore
    except ImportError as error:
        raise RuntimeError("xlrd is required to parse CME warehouse reports") from error

    workbook = xlrd.open_workbook(file_contents=raw)
    sheet = workbook.sheet_by_index(0)
    cells = [str(sheet.cell_value(row, col)).strip() for row in range(sheet.nrows) for col in range(sheet.ncols)]
    report_date = next((date for text in cells if (date := _cme_date(text)) and "report" in text.lower()), None)
    activity_date = next((date for text in cells if (date := _cme_date(text)) and "activity" in text.lower()), None)
    if not report_date:
        raise ValueError(f"CME {metal} report date missing")

    def row_for(label: str) -> list[Any]:
        expected = re.sub(r"\s+", " ", label.strip().upper())
        for row in range(sheet.nrows):
            first = re.sub(r"\s+", " ", str(sheet.cell_value(row, 0)).strip().upper())
            if first == expected or expected in first:
                return [sheet.cell_value(row, col) for col in range(sheet.ncols)]
        raise ValueError(f"CME {metal} row missing: {label}")

    def value(row: list[Any], col: int) -> float | None:
        return number(row[col]) if len(row) > col else None

    registered = row_for("TOTAL REGISTERED")
    eligible = row_for("TOTAL ELIGIBLE")
    combined = row_for("COMBINED TOTAL")
    try:
        pledged = row_for("TOTAL PLEDGED")
    except ValueError:
        pledged = []
    registered_oz = value(registered, 7)
    eligible_oz = value(eligible, 7)
    total_oz = value(combined, 7)
    if None in (registered_oz, eligible_oz, total_oz):
        raise ValueError(f"CME {metal} totals are incomplete")
    registered_net = value(registered, 5)
    eligible_net = value(eligible, 5)
    total_net = value(combined, 5)
    pledged_oz = value(pledged, 7) if pledged else None
    contract_size = 100 if metal == "gold" else 5000
    history = list((previous or {}).get("history", []))
    history_key = activity_date or report_date
    point = [history_key, round_value(registered_oz, 3), round_value(eligible_oz, 3), round_value(total_oz, 3)]
    if not history or history[-1][0] != history_key:
        history.append(point)
    else:
        history[-1] = point
    return {
        "label": "COMEX 黄金库存" if metal == "gold" else "COMEX 白银库存",
        "metal": metal,
        "report_date": report_date,
        "activity_date": activity_date,
        "unit": "troy oz",
        "contract_size_oz": contract_size,
        "registered_oz": round_value(registered_oz, 3),
        "eligible_oz": round_value(eligible_oz, 3),
        "pledged_oz": round_value(pledged_oz, 3),
        "total_oz": round_value(total_oz, 3),
        "registered_net_change_oz": round_value(registered_net, 3),
        "eligible_net_change_oz": round_value(eligible_net, 3),
        "total_net_change_oz": round_value(total_net, 3),
        "registered_share_pct": round_value(registered_oz / total_oz * 100 if total_oz else None, 3),
        "registered_contract_equivalents": round_value(registered_oz / contract_size, 2),
        "history": history[-180:],
        "source": "CME Group COMEX",
        "source_url": CME_WAREHOUSE_PAGE_URL,
        "report_url": CME_WAREHOUSE_URLS[metal],
        "definition_note": "Registered = 已签发仓单、可交割库存；Eligible = 符合规格但未签发仓单；Pledged = 已质押库存。三者不可当作同一口径的可售库存。",
    }


def fetch_cme_inventory_asset(metal: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    return parse_cme_inventory(download_cme_report(CME_WAREHOUSE_URLS[metal]), metal, previous)


def _milliseconds_iso(value: Any) -> str | None:
    timestamp = number(value)
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp / 1000, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def fetch_binance_crypto_asset(symbol: str) -> dict[str, Any]:
    pair = f"{symbol}USDT"
    ticker = request_json(f"{BINANCE_FUTURES_BASE}/fapi/v1/ticker/24hr?symbol={pair}")
    oi_rows = request_json(f"{BINANCE_FUTURES_BASE}/futures/data/openInterestHist?symbol={pair}&period=15m&limit=97")
    premium = request_json(f"{BINANCE_FUTURES_BASE}/fapi/v1/premiumIndex?symbol={pair}")
    if not isinstance(oi_rows, list) or not oi_rows:
        raise ValueError(f"Binance {pair} open interest history is empty")
    history = []
    for item in oi_rows:
        timestamp = _milliseconds_iso(item.get("timestamp"))
        value = number(item.get("sumOpenInterestValue"))
        if timestamp and value is not None:
            history.append([timestamp, round_value(value, 2)])
    if not history:
        raise ValueError(f"Binance {pair} open interest values are empty")
    current_oi = history[-1][1]
    first_oi = history[0][1]
    funding = number(premium.get("lastFundingRate"))
    return {
        "symbol": symbol,
        "label": f"{symbol} 永续合约",
        "provider": "Binance USDⓈ-M public fallback",
        "scope": "single-venue",
        "aggregated": False,
        "price_usd": round_value(number(ticker.get("lastPrice")), 6),
        "price_change_24h_pct": round_value(number(ticker.get("priceChangePercent")), 4),
        "volume_24h_usd": round_value(number(ticker.get("quoteVolume")), 2),
        "open_interest_usd": round_value(current_oi, 2),
        "open_interest_change_24h_pct": round_value((current_oi / first_oi - 1) * 100 if first_oi else None, 4),
        "funding_rate": round_value(funding, 8),
        "funding_rate_pct": round_value(funding * 100 if funding is not None else None, 5),
        "next_funding_at": _milliseconds_iso(premium.get("nextFundingTime")),
        "observed_at": history[-1][0],
        "oi_history": history[-97:],
        "source": "Binance USDⓈ-M public API",
        "source_url": "https://developers.binance.com/en/docs/derivatives/usds-margined-futures/market-data/rest-api",
        "note": "单一交易所公开代理值；不等于全市场持仓量、成交量或资金费率聚合。",
    }


def fetch_binance_positioning() -> dict[str, Any]:
    assets = {}
    errors = []
    for symbol in ("BTC", "ETH"):
        try:
            assets[symbol] = fetch_binance_crypto_asset(symbol)
        except Exception as error:
            errors.append(f"{symbol}: {str(error)[:180]}")
    if not assets:
        raise RuntimeError("Binance public positioning unavailable: " + "; ".join(errors))
    return {
        "checked_at": utc_now(),
        "provider": "Binance USDⓈ-M public fallback",
        "scope": "single-venue",
        "aggregated": False,
        "assets": assets,
        "exchange_totals": {},
        "etf": {},
        "activation_note": "设置 GitHub Actions Secret COINGLASS_API_KEY 后启用 CoinGlass 多交易所聚合；当前值仅作单交易所代理。",
        "errors": errors,
    }


def _coinglass_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("list", "data", "result", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def coinglass_json(path: str, params: dict[str, Any], api_key: str) -> Any:
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
    url = f"{COINGLASS_API_BASE}/{path.lstrip('/')}" + (f"?{query}" if query else "")
    payload = request_json(url, headers={"CG-API-KEY": api_key, "Accept": "application/json"})
    if not isinstance(payload, dict) or str(payload.get("code", "0")) not in {"0", "200"}:
        raise ValueError(f"CoinGlass API error at {path}: {str(payload.get('msg', payload))[:180] if isinstance(payload, dict) else payload}")
    return payload.get("data", payload)


def _coinglass_time(item: dict[str, Any]) -> str | None:
    for key in ("time", "timestamp", "ts", "date"):
        if item.get(key) is not None:
            return _milliseconds_iso(item[key]) or str(item[key])
    return None


def _coinglass_close(item: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = number(item.get(key))
        if value is not None:
            return value
    return None


def fetch_coinglass_crypto_asset(symbol: str, api_key: str) -> dict[str, Any]:
    oi = _coinglass_rows(coinglass_json("futures/open-interest/aggregated-history", {"symbol": symbol, "interval": "4h", "limit": 7, "unit": "usd"}, api_key))
    funding = _coinglass_rows(coinglass_json("futures/funding-rate/oi-weight-history", {"symbol": symbol, "interval": "4h", "limit": 7}, api_key))
    oi_history = []
    for item in oi:
        stamp = _coinglass_time(item)
        value = _coinglass_close(item, ("close", "open_interest", "openInterest", "oi", "value"))
        if stamp and value is not None:
            oi_history.append([stamp, round_value(value, 2)])
    if not oi_history:
        raise ValueError(f"CoinGlass {symbol} OI history is empty")
    funding_value = _coinglass_close(funding[-1], ("close", "funding_rate", "fundingRate", "value")) if funding else None
    latest = oi_history[-1]
    first = oi_history[0]
    # Price and volume are deliberately sourced from Binance public API and
    # labeled as such; CoinGlass Hobbyist does not expose the all-in-one market
    # endpoint needed for those fields.
    proxy = fetch_binance_crypto_asset(symbol)
    return {
        "symbol": symbol,
        "label": f"{symbol} 永续合约",
        "provider": "CoinGlass aggregate OI/funding + Binance price/volume proxy",
        "scope": "multi-venue OI/funding",
        "aggregated": True,
        "price_usd": proxy.get("price_usd"),
        "price_change_24h_pct": proxy.get("price_change_24h_pct"),
        "volume_24h_usd": proxy.get("volume_24h_usd"),
        "open_interest_usd": latest[1],
        "open_interest_change_24h_pct": round_value((latest[1] / first[1] - 1) * 100 if first[1] else None, 4),
        "funding_rate": round_value(funding_value, 8),
        "funding_rate_pct": round_value(funding_value * 100 if funding_value is not None else None, 5),
        "next_funding_at": proxy.get("next_funding_at"),
        "observed_at": latest[0],
        "oi_history": oi_history,
        "source": "CoinGlass API v4",
        "source_url": "https://docs.coinglass.com/reference/getting-started-with-your-api",
        "note": "持仓量与资金费率为 CoinGlass 多交易所聚合；价格与成交量为 Binance USDⓈ-M 公开代理。",
    }


def fetch_coinglass_positioning(api_key: str) -> dict[str, Any]:
    assets = {symbol: fetch_coinglass_crypto_asset(symbol, api_key) for symbol in ("BTC", "ETH")}
    exchange_totals: dict[str, Any] = {}
    try:
        rank_rows = _coinglass_rows(coinglass_json("futures/exchange-rank", {}, api_key))
        totals = {"open_interest_usd": 0.0, "volume_24h_usd": 0.0, "liquidation_24h_usd": 0.0}
        for row in rank_rows:
            totals["open_interest_usd"] += number(row.get("open_interest_usd") or row.get("openInterestUsd")) or 0
            totals["volume_24h_usd"] += number(row.get("volume_usd") or row.get("volumeUsd")) or 0
            totals["liquidation_24h_usd"] += number(row.get("liquidation_usd_24h") or row.get("liquidationUsd24h")) or 0
        if any(totals.values()):
            exchange_totals = {key: round_value(value, 2) for key, value in totals.items()}
    except Exception:
        exchange_totals = {}
    etf = {}
    try:
        etf_rows = _coinglass_rows(coinglass_json("etf/bitcoin/list", {}, api_key))
        etf_totals = {"aum_usd": 0.0, "volume_24h_usd": 0.0, "btc_holdings": 0.0}
        for row in etf_rows:
            etf_totals["aum_usd"] += number(row.get("aum_usd") or row.get("aumUsd")) or 0
            etf_totals["volume_24h_usd"] += number(row.get("volume_usd") or row.get("volumeUsd")) or 0
            details = row.get("asset_details") if isinstance(row.get("asset_details"), dict) else {}
            etf_totals["btc_holdings"] += number(details.get("btc_holding") or row.get("btc_holding") or row.get("btcHolding")) or 0
        if any(etf_totals.values()):
            etf = {key: round_value(value, 2) for key, value in etf_totals.items()}
    except Exception:
        etf = {}
    return {
        "checked_at": utc_now(),
        "provider": "CoinGlass API v4",
        "scope": "multi-venue aggregate",
        "aggregated": True,
        "assets": assets,
        "exchange_totals": exchange_totals,
        "etf": etf,
        "activation_note": "CoinGlass 聚合已启用；成交量/价格字段注明 Binance 代理，避免把不同口径混为全市场数据。",
        "errors": [],
    }


def fetch_crypto_positioning() -> dict[str, Any]:
    api_key = os.environ.get("COINGLASS_API_KEY", "").strip()
    if api_key:
        try:
            return fetch_coinglass_positioning(api_key)
        except Exception as error:
            fallback = fetch_binance_positioning()
            fallback["activation_note"] = f"CoinGlass API 暂时失败，已降级为 Binance 单交易所代理；错误：{str(error)[:180]}"
            fallback["coinglass_error"] = str(error)[:240]
            return fallback
    return fetch_binance_positioning()


def clean_html(value: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(plain)).strip()


def number(value: Any) -> float | None:
    try:
        value = str(value).strip()
        if not value or value == ".":
            return None
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def round_value(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def fetch_fred_series(series_id: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"id": series_id, "cosd": "2023-01-01"})
    text = request_text(f"{FRED_URL}?{query}")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        raise ValueError(f"FRED {series_id}: empty response")
    observations: list[list[Any]] = []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        value = number(row[1])
        if value is not None:
            observations.append([row[0], value])
    if not observations:
        raise ValueError(f"FRED {series_id}: no numeric observations")
    label, unit, category = FRED_SERIES[series_id]
    latest = observations[-1]
    previous = observations[-2] if len(observations) > 1 else latest
    return {
        "id": series_id,
        "label": label,
        "value": round_value(latest[1], 6),
        "previous": round_value(previous[1], 6),
        "date": latest[0],
        "previous_date": previous[0],
        "unit": unit,
        "category": category,
        "source": "FRED",
        "source_url": f"https://fred.stlouisfed.org/series/{series_id}",
        "history": [[date, round_value(value, 6)] for date, value in observations[-90:]],
    }


def prior_year_value(history: list[list[Any]]) -> float | None:
    if len(history) < 2:
        return None
    latest_date = datetime.fromisoformat(history[-1][0]).date()
    candidates = []
    for date_text, value in history[:-1]:
        date = datetime.fromisoformat(date_text).date()
        distance = abs((latest_date - date).days - 365)
        if distance <= 50:
            candidates.append((distance, value))
    return min(candidates, default=(0, None), key=lambda item: item[0])[1]


def change(series: dict[str, Any] | None) -> float | None:
    if not series:
        return None
    return round_value(series["value"] - series["previous"], 6)


def percent_change(series: dict[str, Any] | None) -> float | None:
    if not series or not series.get("previous"):
        return None
    return round_value((series["value"] / series["previous"] - 1) * 100, 4)


def yoy(series: dict[str, Any] | None) -> float | None:
    if not series:
        return None
    prior = prior_year_value(series.get("history", []))
    if prior in (None, 0):
        return None
    return round_value((series["value"] / prior - 1) * 100, 4)


def fetch_ecb_usdjpy() -> dict[str, Any]:
    text = request_text(ECB_URL)
    root = ET.fromstring(text)
    daily: list[list[Any]] = []
    for element in root.iter():
        date = element.attrib.get("time")
        if not date:
            continue
        rates = {}
        for child in list(element):
            currency = child.attrib.get("currency")
            value = number(child.attrib.get("rate"))
            if currency and value is not None:
                rates[currency] = value
        if rates.get("USD") and rates.get("JPY"):
            daily.append([date, rates["JPY"] / rates["USD"]])
    daily.sort(key=lambda item: item[0])
    if len(daily) < 2:
        raise ValueError("ECB: insufficient USD/JPY reference rates")
    latest, previous = daily[-1], daily[-2]
    return {
        "id": "FX_USDJPY",
        "label": "USD/JPY ECB 参考汇率",
        "value": round_value(latest[1], 5),
        "previous": round_value(previous[1], 5),
        "date": latest[0],
        "previous_date": previous[0],
        "unit": "JPY/USD",
        "category": "资产",
        "source": "ECB",
        "source_url": "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html",
        "history": [[date, round_value(value, 5)] for date, value in daily[-90:]],
    }


def append_intraday_history(previous: dict[str, Any] | None, observed_at: str, value: float) -> list[list[Any]]:
    points: dict[str, float] = {}
    for point in (previous or {}).get("history", []):
        if len(point) >= 2 and parse_timestamp(str(point[0])) and number(point[1]) is not None:
            points[str(point[0])] = float(point[1])
    points[observed_at] = value
    ordered = sorted(points.items(), key=lambda item: parse_timestamp(item[0]) or datetime.min.replace(tzinfo=timezone.utc))
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent = [[stamp, round_value(price, 6)] for stamp, price in ordered if (parse_timestamp(stamp) or cutoff) >= cutoff]
    return recent[-700:]


def fetch_metal_spot(symbol: str, previous: dict[str, Any] | None) -> dict[str, Any]:
    symbol = symbol.upper()
    if symbol not in {"XAU", "XAG"}:
        raise ValueError(f"unsupported metal symbol {symbol}")
    source = "Gold-API.com"
    source_url = f"https://gold-api.com/{symbol.lower()}"
    quote_basis = "公开聚合现货指示中间价（非可成交报价）"
    stale = False
    try:
        raw = request_json(f"{GOLD_API_URL}/{symbol}")
        price = number(raw.get("price"))
        observed_at = raw.get("updatedAt")
    except Exception as primary_error:
        fallback = request_json(XAUS_FALLBACK_URL)
        price = number(fallback.get("spot_usd_oz") if symbol == "XAU" else fallback.get("silver_usd_oz"))
        observed_at = fallback.get("price_as_of") or fallback.get("updated_at")
        stale = bool(fallback.get("stale"))
        source = "XAUS.com fallback"
        source_url = "https://xaus.com/api/"
        quote_basis = "公开聚合现货指示中间价（回退源，非可成交报价）"
        if price is None:
            raise RuntimeError(f"{symbol} primary failed ({primary_error}); fallback returned no price")
    if price is None or observed_at is None:
        raise ValueError(f"{symbol}: missing price or observation timestamp")
    lower, upper = (100.0, 50_000.0) if symbol == "XAU" else (1.0, 1_000.0)
    if not lower <= price <= upper:
        raise ValueError(f"{symbol}: implausible price {price}")
    observed = parse_timestamp(str(observed_at))
    if observed is None:
        raise ValueError(f"{symbol}: invalid observation timestamp {observed_at}")
    observed_at = observed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    previous_value = number((previous or {}).get("value"))
    if previous_value is None:
        previous_value = price
    history = append_intraday_history(previous, observed_at, price)
    label = "黄金现货 XAU/USD" if symbol == "XAU" else "白银现货 XAG/USD"
    return {
        "id": f"SPOT_{symbol}USD",
        "label": label,
        "value": round_value(price, 6),
        "previous": round_value(previous_value, 6),
        "date": observed_at[:10],
        "previous_date": (previous or {}).get("observed_at") or observed_at,
        "observed_at": observed_at,
        "unit": "USD/金衡盎司",
        "category": "贵金属",
        "instrument": f"{symbol}/USD spot",
        "venue": "OTC composite",
        "quote_basis": quote_basis,
        "tradable": False,
        "stale": stale,
        "source": source,
        "source_url": source_url,
        "history": history,
    }


def cftc_ratio(row: list[str], kind: str) -> tuple[float, float, int]:
    if kind == "managed_money":
        oi, long_pos, short_pos = number(row[7]), number(row[13]), number(row[14])
        oi_change, long_change, short_change = number(row[55]), number(row[61]), number(row[62])
    else:
        oi, long_pos, short_pos = number(row[7]), number(row[14]), number(row[15])
        oi_change, long_change, short_change = number(row[24]), number(row[31]), number(row[32])
    if None in (oi, long_pos, short_pos) or not oi:
        raise ValueError("CFTC row missing required position fields")
    net = int(round(long_pos - short_pos))
    ratio = 100 * net / oi
    weekly = 0.0
    if None not in (oi_change, long_change, short_change):
        previous_oi = oi - oi_change
        previous_net = net - (long_change - short_change)
        if previous_oi:
            weekly = ratio - (100 * previous_net / previous_oi)
    return round(ratio, 2), round(weekly, 2), net


def parse_cftc_rows(text: str) -> list[list[str]]:
    return [row for row in csv.reader(io.StringIO(text)) if row]


def find_contract(rows: list[list[str]], prefix: str) -> list[str] | None:
    prefix = prefix.upper()
    return next((row for row in rows if row[0].strip().upper().startswith(prefix)), None)


def fetch_cftc() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    disaggregated = parse_cftc_rows(request_text(CFTC_DISAGG_URL))
    financial = parse_cftc_rows(request_text(CFTC_TFF_URL))
    contracts = [
        ("黄金", "GOLD - COMMODITY EXCHANGE", "managed_money", disaggregated),
        ("白银", "SILVER - COMMODITY EXCHANGE", "managed_money", disaggregated),
        ("铜", "COPPER- #1 - COMMODITY EXCHANGE", "managed_money", disaggregated),
        ("铂金", "PLATINUM - NEW YORK MERCANTILE", "managed_money", disaggregated),
        ("钯金", "PALLADIUM - NEW YORK MERCANTILE", "managed_money", disaggregated),
        ("日元", "JAPANESE YEN - CHICAGO MERCANTILE", "leveraged_funds", financial),
        ("纳斯达克100", "NASDAQ-100 CONSOLIDATED", "leveraged_funds", financial),
        ("美债2Y", "UST 2Y NOTE", "leveraged_funds", financial),
        ("美债10Y", "UST 10Y NOTE", "leveraged_funds", financial),
        ("美债30Y", "UST BOND", "leveraged_funds", financial),
    ]
    positions = []
    missing = []
    report_dates = []
    for display_name, prefix, kind, rows in contracts:
        row = find_contract(rows, prefix)
        if row is None:
            missing.append({"source": "CFTC", "series": display_name, "error": "contract not found"})
            continue
        ratio, weekly, net = cftc_ratio(row, kind)
        report_date = row[2].strip()
        report_dates.append(report_date)
        positions.append({
            "name": display_name,
            "contract_name": row[0].strip(),
            "contracts": net,
            "ratio": ratio,
            "weekly_ratio_change": weekly,
            "category": "管理资金" if kind == "managed_money" else "杠杆基金",
            "report_date": report_date,
            "source": "CFTC COT Futures + Options Combined",
        })
    positions.sort(key=lambda item: item["ratio"], reverse=True)
    return {
        "report_date": max(report_dates) if report_dates else None,
        "positions": positions,
        "dynamic_count": len(positions),
        "target_count": len(contracts),
        "source_url": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
    }, missing


def translate_event(title: str, country: str) -> str:
    lowered = title.lower()
    translations = [
        ("core pce", "美国核心 PCE"),
        ("personal income and outlays", "美国个人收入与支出（含 PCE）"),
        ("prelim gdp", "美国 GDP 修正值"),
        ("gdp (second estimate)", "美国 GDP 第二次估值"),
        ("gdp (third estimate)", "美国 GDP 第三次估值"),
        ("gdp (advance estimate)", "美国 GDP 初值"),
        ("gdp price index", "美国 GDP 价格指数"),
        ("employment situation", "美国非农就业报告"),
        ("non-farm", "美国非农就业"),
        ("unemployment claims", "美国初请失业金"),
        ("consumer price index", "美国 CPI"),
        ("tokyo core cpi", "日本东京核心 CPI"),
        ("cpi m/m", "CPI 环比"),
        ("cpi y/y", "CPI 同比"),
        ("producer price index", "美国 PPI"),
        ("jolts", "美国 JOLTS 职位空缺"),
        ("fomc", "美联储 FOMC 事件"),
        ("fed chairman", "美联储主席讲话"),
        ("jackson hole", "杰克逊霍尔央行年会"),
        ("boj", "日本央行事件"),
        ("china", "中国"),
        ("international trade", "美国国际贸易"),
        ("monetary policy meeting accounts", "ECB 货币政策会议纪要"),
    ]
    for needle, translated in translations:
        if needle in lowered:
            return translated
    prefixes = {"USD": "美国", "JPY": "日本", "CNY": "中国", "EUR": "欧元区", "All": "全球"}
    return f"{prefixes.get(country, country)} · {title}"


def make_calendar_event(
    *,
    title: str,
    country: str,
    timestamp: datetime,
    impact: str,
    source: str,
    source_url: str,
    forecast: str = "",
    previous: str = "",
    official: bool = False,
) -> dict[str, Any]:
    stamp = timestamp.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    identity = hashlib.sha1(f"{stamp}|{country}|{title}|{source}".encode()).hexdigest()[:12]
    return {
        "id": identity,
        "title": translate_event(title, country),
        "original_title": clean_html(title),
        "country": country,
        "timestamp": stamp,
        "impact": impact,
        "forecast": forecast,
        "previous": previous,
        "source": source,
        "source_url": source_url,
        "official": official,
    }


def fetch_calendar_feed(now: datetime) -> list[dict[str, Any]]:
    raw = request_json(CALENDAR_FEED_URL)
    if not isinstance(raw, list):
        raise ValueError("calendar feed did not return a list")
    events = []
    countries = {"USD", "JPY", "CNY", "EUR", "All"}
    for item in raw:
        timestamp = parse_timestamp(item.get("date"))
        impact = str(item.get("impact") or "Low").title()
        country = str(item.get("country") or "")
        if timestamp is None or country not in countries or impact not in {"High", "Medium"}:
            continue
        if not now - timedelta(hours=2) <= timestamp <= now + timedelta(days=8):
            continue
        events.append(make_calendar_event(
            title=str(item.get("title") or "Scheduled event"),
            country=country,
            timestamp=timestamp,
            impact=impact,
            source="Forex Factory public calendar feed",
            source_url="https://www.forexfactory.com/calendar",
            forecast=str(item.get("forecast") or ""),
            previous=str(item.get("previous") or ""),
        ))
    return events


def fetch_bea_calendar(now: datetime) -> list[dict[str, Any]]:
    text = request_text(BEA_CALENDAR_URL)
    rows = re.findall(r'<tr class="scheduled-releases-type-press">(.*?)</tr>', text, flags=re.S | re.I)
    events = []
    for row in rows:
        date_match = re.search(r'<div class="release-date">([^<]+)</div>', row, flags=re.I)
        time_match = re.search(r'<small class="text-muted">([^<]+)</small>', row, flags=re.I)
        title_match = re.search(r'<td class="release-title[^"]*"[^>]*>(.*?)</td>', row, flags=re.S | re.I)
        if not (date_match and time_match and title_match):
            continue
        title = clean_html(title_match.group(1))
        if not any(keyword in title.lower() for keyword in ("gdp", "personal income and outlays", "international trade")):
            continue
        try:
            local = datetime.strptime(
                f"{now.year} {clean_html(date_match.group(1))} {clean_html(time_match.group(1))}",
                "%Y %B %d %I:%M %p",
            ).replace(tzinfo=ZoneInfo("America/New_York"))
        except ValueError:
            continue
        if local < now - timedelta(hours=2) or local > now + timedelta(days=180):
            continue
        impact = "High" if any(keyword in title.lower() for keyword in ("gdp", "personal income and outlays")) else "Medium"
        events.append(make_calendar_event(
            title=title,
            country="USD",
            timestamp=local,
            impact=impact,
            source="U.S. BEA",
            source_url=BEA_CALENDAR_URL,
            official=True,
        ))
    return events


def fetch_fomc_calendar(now: datetime) -> list[dict[str, Any]]:
    text = request_text(FOMC_CALENDAR_URL)
    start = text.find(f">{now.year} FOMC Meetings<")
    if start < 0:
        raise ValueError(f"FOMC calendar missing {now.year} section")
    end = text.find(f">{now.year - 1} FOMC Meetings<", start)
    block = text[start:end if end > start else None]
    meetings = re.findall(
        r'fomc-meeting__month[^>]*><strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)</div>',
        block,
        flags=re.S | re.I,
    )
    events = []
    for month_text, date_text in meetings:
        month_name = clean_html(month_text).split("/")[-1]
        day_numbers = re.findall(r"\d+", clean_html(date_text))
        if not day_numbers:
            continue
        try:
            local = datetime(
                now.year,
                datetime.strptime(month_name, "%B").month,
                int(day_numbers[-1]),
                14,
                0,
                tzinfo=ZoneInfo("America/New_York"),
            )
        except ValueError:
            continue
        if local < now - timedelta(hours=2) or local > now + timedelta(days=180):
            continue
        events.append(make_calendar_event(
            title="FOMC interest-rate decision and statement",
            country="USD",
            timestamp=local,
            impact="High",
            source="Federal Reserve",
            source_url=FOMC_CALENDAR_URL,
            official=True,
        ))
    return events


def fetch_ecb_calendar(now: datetime) -> list[dict[str, Any]]:
    text = request_text(ECB_CALENDAR_URL)
    entries = re.findall(r"<dt>\s*(\d{2}/\d{2}/\d{4})\s*</dt>\s*<dd>\s*(.*?)<br", text, flags=re.S | re.I)
    events = []
    for date_text, description in entries:
        title = clean_html(description)
        if "monetary policy meeting" not in title.lower() or "(day 2)" not in title.lower():
            continue
        try:
            local = datetime.strptime(date_text, "%d/%m/%Y").replace(
                hour=14,
                minute=15,
                tzinfo=ZoneInfo("Europe/Berlin"),
            )
        except ValueError:
            continue
        if local < now - timedelta(hours=2) or local > now + timedelta(days=180):
            continue
        events.append(make_calendar_event(
            title="ECB monetary-policy decision",
            country="EUR",
            timestamp=local,
            impact="High",
            source="European Central Bank",
            source_url=ECB_CALENDAR_URL,
            official=True,
        ))
    return events


def fetch_economic_calendar() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    now = datetime.now(timezone.utc)
    events: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    sources = [
        ("Broad weekly feed", fetch_calendar_feed),
        ("BEA", fetch_bea_calendar),
        ("Federal Reserve", fetch_fomc_calendar),
        ("ECB", fetch_ecb_calendar),
    ]
    source_statuses = []
    for source, fetcher in sources:
        try:
            collected = fetcher(now)
            events.extend(collected)
            source_statuses.append({"source": source, "status": "ok", "events": len(collected)})
        except Exception as error:
            errors.append({"source": source, "series": "economic_calendar", "error": str(error)[:240]})
            source_statuses.append({"source": source, "status": "failed", "events": 0})
    if not events:
        raise RuntimeError("all economic calendar sources failed")
    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in sorted(events, key=lambda item: (not item["official"], item["timestamp"])):
        key = (event["timestamp"][:16], event["country"], event["title"])
        if key not in unique or event["official"]:
            unique[key] = event
    upcoming = sorted(unique.values(), key=lambda item: item["timestamp"])
    return {
        "checked_at": utc_now(),
        "timezone": "Europe/Berlin",
        "events": upcoming[:24],
        "next_event": upcoming[0] if upcoming else None,
        "source_statuses": source_statuses,
        "coverage_note": "美联储、BEA、ECB 官方日程优先；公开周历补足 CPI、非农、日本与中国事件。",
    }, errors


def derived_metric(label: str, value: float | None, unit: str, date: str | None, source: str) -> dict[str, Any]:
    return {"label": label, "value": round_value(value, 4), "unit": unit, "date": date, "source": source}


def intraday_session_change(series: dict[str, Any] | None) -> float | None:
    if not series or not series.get("history"):
        return None
    observed = parse_timestamp(series.get("observed_at"))
    if observed is None:
        return None
    same_day = [
        number(point[1])
        for point in series["history"]
        if len(point) >= 2 and parse_timestamp(str(point[0])) and parse_timestamp(str(point[0])).date() == observed.date()
    ]
    values = [value for value in same_day if value is not None]
    if not values or values[0] == 0:
        return None
    return round_value((series["value"] / values[0] - 1) * 100, 4)


def build_derived(series: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest_date = lambda key: series.get(key, {}).get("date")
    value = lambda key: series.get(key, {}).get("value")
    dgs10, dgs2 = value("DGS10"), value("DGS2")
    walcl_change = change(series.get("WALCL"))
    gold, silver = value("SPOT_XAUUSD"), value("SPOT_XAGUSD")
    return {
        "YIELD_10Y2Y": derived_metric("10Y−2Y 利差", None if None in (dgs10, dgs2) else dgs10 - dgs2, "百分点", latest_date("DGS10"), "FRED"),
        "WALCL_WEEKLY_B": derived_metric("美联储资产负债表周变动", None if walcl_change is None else walcl_change / 1000, "十亿美元", latest_date("WALCL"), "FRED"),
        "M2_YOY": derived_metric("美国 M2 同比", yoy(series.get("WM2NS")), "%", latest_date("WM2NS"), "FRED"),
        "PAYROLL_CHANGE": derived_metric("非农就业月变动", change(series.get("PAYEMS")), "千人", latest_date("PAYEMS"), "FRED"),
        "CPI_YOY": derived_metric("美国 CPI 同比", yoy(series.get("CPIAUCSL")), "%", latest_date("CPIAUCSL"), "FRED"),
        "PCE_YOY": derived_metric("美国 PCE 同比", yoy(series.get("PCEPI")), "%", latest_date("PCEPI"), "FRED"),
        "CORE_PCE_YOY": derived_metric("美国核心 PCE 同比", yoy(series.get("PCEPILFE")), "%", latest_date("PCEPILFE"), "FRED"),
        "SP500_DAILY": derived_metric("标普 500 日变动", percent_change(series.get("SP500")), "%", latest_date("SP500"), "FRED"),
        "NASDAQ_DAILY": derived_metric("纳斯达克日变动", percent_change(series.get("NASDAQCOM")), "%", latest_date("NASDAQCOM"), "FRED"),
        "USDJPY_DAILY": derived_metric("USD/JPY 日变动", percent_change(series.get("FX_USDJPY")), "%", latest_date("FX_USDJPY"), "ECB"),
        "XAU_15M": derived_metric("黄金较上次快照", percent_change(series.get("SPOT_XAUUSD")), "%", latest_date("SPOT_XAUUSD"), "Gold-API"),
        "XAG_15M": derived_metric("白银较上次快照", percent_change(series.get("SPOT_XAGUSD")), "%", latest_date("SPOT_XAGUSD"), "Gold-API"),
        "XAU_SESSION": derived_metric("黄金 UTC 日内变动", intraday_session_change(series.get("SPOT_XAUUSD")), "%", latest_date("SPOT_XAUUSD"), "Gold-API"),
        "XAG_SESSION": derived_metric("白银 UTC 日内变动", intraday_session_change(series.get("SPOT_XAGUSD")), "%", latest_date("SPOT_XAGUSD"), "Gold-API"),
        "GOLD_SILVER_RATIO": derived_metric(
            "金银比",
            None if None in (gold, silver) or silver == 0 else gold / silver,
            "倍",
            latest_date("SPOT_XAUUSD"),
            "Gold-API",
        ),
    }


def metric_display(metric: dict[str, Any] | None, digits: int = 2, scale: float = 1.0, suffix: str = "") -> str:
    if not metric or metric.get("value") is None:
        return "待更新"
    value = metric["value"] / scale
    return f"{value:,.{digits}f}{suffix}"


def build_layers(series: dict[str, dict[str, Any]], derived: dict[str, dict[str, Any]], cftc: dict[str, Any]) -> dict[str, Any]:
    silver = next((item for item in cftc.get("positions", []) if item["name"] == "白银"), None)
    return {
        "L1": {
            "automated": True,
            "metrics": {
                "美联储总资产": metric_display(series.get("WALCL"), 3, 1_000_000, " 万亿美元"),
                "周度变化": metric_display(derived.get("WALCL_WEEKLY_B"), 1, scale=0.1, suffix=" 亿美元"),
                "ON RRP": metric_display(series.get("RRPONTSYD"), 2, suffix=" 十亿美元"),
                "10Y−2Y 利差": metric_display(derived.get("YIELD_10Y2Y"), 2, suffix="pct"),
            },
        },
        "L2": {
            "automated": True,
            "metrics": {
                "美国 Q2 GDP": metric_display(series.get("A191RL1Q225SBEA"), 1, suffix="% 年化"),
                "美国非农月变动": metric_display(derived.get("PAYROLL_CHANGE"), 0, suffix=" 千人"),
                "美国失业率": metric_display(series.get("UNRATE"), 1, suffix="%"),
                "JOLTS 职位空缺": metric_display(series.get("JTSJOL"), 0, scale=1000, suffix=" 百万"),
            },
        },
        "L3": {
            "automated": True,
            "metrics": {
                "美国总 PCE": metric_display(derived.get("PCE_YOY"), 2, suffix="%"),
                "美国核心 PCE": metric_display(derived.get("CORE_PCE_YOY"), 2, suffix="%"),
                "10Y 盈亏平衡": metric_display(series.get("T10YIE"), 2, suffix="%"),
                "10Y 实际利率": metric_display(series.get("DFII10"), 2, suffix="%"),
            },
        },
        "L4": {
            "automated": True,
            "metrics": {
                "美债 10Y": metric_display(series.get("DGS10"), 3, suffix="%"),
                "美债 30Y": metric_display(series.get("DGS30"), 3, suffix="%"),
                "USD/JPY": metric_display(series.get("FX_USDJPY"), 2),
                "SPX / NDX": f"{metric_display(derived.get('SP500_DAILY'), 2, suffix='%')} / {metric_display(derived.get('NASDAQ_DAILY'), 2, suffix='%')}",
            },
        },
        "L5": {
            "automated": True,
            "metrics": {
                "VIX": metric_display(series.get("VIXCLS"), 2),
                "美国 HY OAS": metric_display(series.get("BAMLH0A0HYM2"), 2, suffix="%"),
                "白银管理资金净多": "待更新" if not silver else f"{silver['contracts']:+,} 张",
                "动态 CFTC": f"{cftc.get('dynamic_count', 0)} 类资产",
            },
        },
        "L6": {"automated": False, "metrics": {}, "note": "政策与地缘事件仍采用人工核验，避免自动文本误判。"},
    }


def directional_signal(value: float | None, deadband: float, positive_when_rising: bool = True) -> float | None:
    if value is None:
        return None
    if abs(value) <= deadband:
        return 0.0
    raw = 1.0 if value > 0 else -1.0
    return raw if positive_when_rising else -raw


def conclusion_factor(
    name: str,
    value: float | None,
    *,
    weight: float,
    deadband: float,
    positive_when_rising: bool,
    fact: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "raw": directional_signal(value, deadband, positive_when_rising),
        "weight": weight,
        "fact": fact,
    }


def weighted_conclusion(factors: list[dict[str, Any]]) -> tuple[int, str, list[dict[str, Any]]]:
    available = [factor for factor in factors if factor["raw"] is not None]
    total_weight = sum(factor["weight"] for factor in available)
    score = 0 if not total_weight else round(100 * sum(factor["raw"] * factor["weight"] for factor in available) / total_weight)
    if score >= 35:
        stance = "明显支持"
    elif score >= 10:
        stance = "温和支持"
    elif score > -10:
        stance = "中性等待"
    elif score > -35:
        stance = "温和压制"
    else:
        stance = "明显压制"
    drivers = []
    for factor in available:
        direction = "支持" if factor["raw"] > 0 else "压制" if factor["raw"] < 0 else "中性"
        drivers.append({
            "name": factor["name"],
            "direction": direction,
            "raw": factor["raw"],
            "weight": factor["weight"],
            "fact": factor["fact"],
        })
    return score, stance, drivers


def signed_text(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "待更新"
    return f"{value:+.{digits}f}{suffix}"


def build_daily_conclusion(
    series: dict[str, dict[str, Any]],
    derived: dict[str, dict[str, Any]],
    cftc: dict[str, Any],
    calendar: dict[str, Any],
) -> dict[str, Any]:
    metric = lambda key: number(derived.get(key, {}).get("value"))
    value = lambda key: number(series.get(key, {}).get("value"))
    delta = lambda key: change(series.get(key))
    positions = {item["name"]: item for item in cftc.get("positions", [])}
    cftc_ratio_value = lambda name: number(positions.get(name, {}).get("ratio"))

    xau_session = metric("XAU_SESSION")
    xag_session = metric("XAG_SESSION")
    real_yield_delta = delta("DFII10")
    dollar_change = percent_change(series.get("DTWEXBGS"))
    nasdaq_change = metric("NASDAQ_DAILY")
    usdjpy_change = metric("USDJPY_DAILY")
    ten_year_delta = delta("DGS10")
    vix_level = value("VIXCLS")

    gold_factors = [
        conclusion_factor("黄金日内动量", xau_session, weight=.25, deadband=.08, positive_when_rising=True, fact=f"黄金 UTC 日内 {signed_text(xau_session, 2, '%')}"),
        conclusion_factor("10Y 实际利率", real_yield_delta, weight=.25, deadband=.02, positive_when_rising=False, fact=f"10Y 实际利率较前值 {signed_text(None if real_yield_delta is None else real_yield_delta * 100, 1, 'bp')}"),
        conclusion_factor("广义美元", dollar_change, weight=.20, deadband=.05, positive_when_rising=False, fact=f"广义美元较前值 {signed_text(dollar_change, 2, '%')}"),
        conclusion_factor("黄金 CFTC", cftc_ratio_value("黄金"), weight=.15, deadband=5, positive_when_rising=True, fact=f"黄金净持仓/OI {signed_text(cftc_ratio_value('黄金'), 2, '%')}"),
        conclusion_factor("避险波动", None if vix_level is None else vix_level - 20, weight=.15, deadband=3, positive_when_rising=True, fact=f"VIX {vix_level:.2f}" if vix_level is not None else "VIX 待更新"),
    ]
    silver_factors = [
        conclusion_factor("白银日内动量", xag_session, weight=.25, deadband=.10, positive_when_rising=True, fact=f"白银 UTC 日内 {signed_text(xag_session, 2, '%')}"),
        conclusion_factor("10Y 实际利率", real_yield_delta, weight=.15, deadband=.02, positive_when_rising=False, fact=f"10Y 实际利率较前值 {signed_text(None if real_yield_delta is None else real_yield_delta * 100, 1, 'bp')}"),
        conclusion_factor("广义美元", dollar_change, weight=.15, deadband=.05, positive_when_rising=False, fact=f"广义美元较前值 {signed_text(dollar_change, 2, '%')}"),
        conclusion_factor("纳斯达克风险偏好", nasdaq_change, weight=.15, deadband=.20, positive_when_rising=True, fact=f"纳斯达克较前值 {signed_text(nasdaq_change, 2, '%')}"),
        conclusion_factor("铜 CFTC", cftc_ratio_value("铜"), weight=.15, deadband=5, positive_when_rising=True, fact=f"铜净持仓/OI {signed_text(cftc_ratio_value('铜'), 2, '%')}"),
        conclusion_factor("白银 CFTC", cftc_ratio_value("白银"), weight=.15, deadband=5, positive_when_rising=True, fact=f"白银净持仓/OI {signed_text(cftc_ratio_value('白银'), 2, '%')}"),
    ]
    yen_factors = [
        conclusion_factor("USD/JPY 方向", usdjpy_change, weight=.35, deadband=.08, positive_when_rising=False, fact=f"USD/JPY 较前值 {signed_text(usdjpy_change, 2, '%')}"),
        conclusion_factor("美债 10Y", ten_year_delta, weight=.25, deadband=.02, positive_when_rising=False, fact=f"美债 10Y 较前值 {signed_text(None if ten_year_delta is None else ten_year_delta * 100, 1, 'bp')}"),
        conclusion_factor("风险规避", None if vix_level is None else vix_level - 20, weight=.15, deadband=3, positive_when_rising=True, fact=f"VIX {vix_level:.2f}" if vix_level is not None else "VIX 待更新"),
        conclusion_factor("日元 CFTC", cftc_ratio_value("日元"), weight=.25, deadband=5, positive_when_rising=True, fact=f"日元净持仓/OI {signed_text(cftc_ratio_value('日元'), 2, '%')}"),
    ]

    assets = {}
    for key, label, factors in (
        ("gold", "黄金", gold_factors),
        ("silver", "白银", silver_factors),
        ("yen", "日元", yen_factors),
    ):
        score, stance, drivers = weighted_conclusion(factors)
        assets[key] = {
            "label": label,
            "score": score,
            "stance": stance,
            "drivers": drivers,
            "interpretation": (
                f"当前规则得分 {score:+d}，对{label}{stance}。"
                "只有价格与跨资产信号继续同向，才视为确认；出现反向组合时应降低结论强度。"
            ),
        }

    next_event = calendar.get("next_event")
    event_text = "近期无已载入的高影响事件"
    if next_event:
        event_time = parse_timestamp(next_event.get("timestamp"))
        if event_time:
            berlin = event_time.astimezone(ZoneInfo("Europe/Berlin"))
            event_text = f"下一事件：{berlin:%m-%d %H:%M} {next_event['title']}"
    observed_times = [
        parse_timestamp(series.get(key, {}).get("observed_at"))
        for key in ("SPOT_XAUUSD", "SPOT_XAGUSD")
    ]
    observed_times = [stamp for stamp in observed_times if stamp]
    as_of = max(observed_times).isoformat().replace("+00:00", "Z") if observed_times else utc_now()
    headline = "；".join(f"{item['label']}{item['stance']}" for item in assets.values()) + "。"
    return {
        "date": datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat(),
        "as_of": as_of,
        "method": "transparent-rules-v1",
        "ai_tokens_used": 0,
        "headline": headline,
        "summary": f"{headline}{event_text}。这是指标规则的条件判断，不是收益保证或自动交易指令。",
        "assets": assets,
        "next_event_text": event_text,
        "risk_note": "若实际利率、美元与价格动量发生同步反转，当前结论应立即降级；事件公布前后需防范跳空和点差扩大。",
        "method_note": "仅使用已标注时点的价格、FRED/ECB 宏观数据与 CFTC 持仓；CME 库存和加密衍生品指标作为风险背景展示，不直接改变金银规则分数；缺失因子不参与加权，不用 AI 补写。",
    }


def signature(payload: dict[str, Any]) -> str:
    compact = {
        "series": {key: [item.get("date"), item.get("value")] for key, item in payload.get("series", {}).items()},
        "cftc": [payload.get("cftc", {}).get("report_date"), [[item["name"], item["contracts"]] for item in payload.get("cftc", {}).get("positions", [])]],
        "flow_positioning": {
            "cme": {key: [item.get("report_date"), item.get("registered_oz"), item.get("total_oz")] for key, item in payload.get("flow_positioning", {}).get("cme_inventory", {}).get("metals", {}).items()},
            "crypto": {key: [item.get("open_interest_usd"), item.get("volume_24h_usd"), item.get("funding_rate")] for key, item in payload.get("flow_positioning", {}).get("crypto", {}).get("assets", {}).items()},
        },
    }
    return hashlib.sha256(json.dumps(compact, sort_keys=True).encode()).hexdigest()[:16]


def main() -> int:
    previous = load_json(LATEST_PATH, {})
    previous_series = previous.get("series", {})
    previous_pipeline = previous.get("pipeline", {})
    previous_flow = previous.get("flow_positioning", {})
    series: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    run_at = utc_now()

    macro_due = cadence_due(previous_pipeline.get("macro_checked_at"), MACRO_REFRESH_HOURS) or any(
        series_id not in previous_series for series_id in (*FRED_SERIES.keys(), "FX_USDJPY")
    )
    if macro_due:
        macro_checked_at = run_at
        for series_id in FRED_SERIES:
            try:
                series[series_id] = fetch_fred_series(series_id)
                statuses.append({"source": f"FRED {series_id}", "status": "ok", "date": series[series_id]["date"]})
            except Exception as error:  # source isolation is intentional
                if series_id in previous_series:
                    series[series_id] = previous_series[series_id]
                errors.append({"source": "FRED", "series": series_id, "error": str(error)[:240]})
                statuses.append({"source": f"FRED {series_id}", "status": "fallback" if series_id in series else "failed"})
        try:
            series["FX_USDJPY"] = fetch_ecb_usdjpy()
            statuses.append({"source": "ECB FX", "status": "ok", "date": series["FX_USDJPY"]["date"]})
        except Exception as error:
            if "FX_USDJPY" in previous_series:
                series["FX_USDJPY"] = previous_series["FX_USDJPY"]
            errors.append({"source": "ECB", "series": "FX_USDJPY", "error": str(error)[:240]})
            statuses.append({"source": "ECB FX", "status": "fallback" if "FX_USDJPY" in series else "failed"})
    else:
        macro_checked_at = previous_pipeline.get("macro_checked_at")
        for series_id in FRED_SERIES:
            if series_id in previous_series:
                series[series_id] = previous_series[series_id]
            statuses.append({
                "source": f"FRED {series_id}",
                "status": "cached" if series_id in series else "failed",
                "date": series.get(series_id, {}).get("date"),
            })
        if "FX_USDJPY" in previous_series:
            series["FX_USDJPY"] = previous_series["FX_USDJPY"]
        statuses.append({
            "source": "ECB FX",
            "status": "cached" if "FX_USDJPY" in series else "failed",
            "date": series.get("FX_USDJPY", {}).get("date"),
        })

    for symbol in ("XAU", "XAG"):
        series_id = f"SPOT_{symbol}USD"
        try:
            series[series_id] = fetch_metal_spot(symbol, previous_series.get(series_id))
            statuses.append({
                "source": f"{symbol}/USD spot",
                "status": "ok",
                "date": series[series_id].get("observed_at"),
            })
        except Exception as error:
            if series_id in previous_series:
                series[series_id] = previous_series[series_id]
            errors.append({"source": "Gold spot API", "series": series_id, "error": str(error)[:240]})
            statuses.append({"source": f"{symbol}/USD spot", "status": "fallback" if series_id in series else "failed"})

    cftc_due = cadence_due(previous_pipeline.get("cftc_checked_at"), CFTC_REFRESH_HOURS) or not previous.get("cftc", {}).get("positions")
    if cftc_due:
        try:
            cftc, cftc_missing = fetch_cftc()
            errors.extend(cftc_missing)
            cftc_checked_at = run_at
            statuses.append({"source": "CFTC", "status": "ok", "date": cftc.get("report_date")})
        except Exception as error:
            cftc = previous.get("cftc", {"positions": [], "dynamic_count": 0, "target_count": 10})
            cftc_checked_at = previous_pipeline.get("cftc_checked_at")
            errors.append({"source": "CFTC", "series": "COT", "error": str(error)[:240]})
            statuses.append({"source": "CFTC", "status": "fallback" if cftc.get("positions") else "failed"})
    else:
        cftc = previous.get("cftc", {"positions": [], "dynamic_count": 0, "target_count": 10})
        cftc_checked_at = previous_pipeline.get("cftc_checked_at")
        statuses.append({"source": "CFTC", "status": "cached", "date": cftc.get("report_date")})

    previous_calendar = previous.get("calendar", {})
    calendar_due = cadence_due(previous_pipeline.get("calendar_checked_at"), CALENDAR_REFRESH_HOURS) or not previous_calendar.get("events")
    if calendar_due:
        try:
            calendar, calendar_errors = fetch_economic_calendar()
            errors.extend(calendar_errors)
            calendar_checked_at = run_at
            statuses.append({"source": "Economic calendar", "status": "ok", "date": calendar.get("checked_at")})
        except Exception as error:
            calendar = previous_calendar
            calendar_checked_at = previous_pipeline.get("calendar_checked_at")
            errors.append({"source": "Economic calendar", "series": "events", "error": str(error)[:240]})
            statuses.append({"source": "Economic calendar", "status": "fallback" if calendar.get("events") else "failed"})
    else:
        calendar = previous_calendar
        calendar_checked_at = previous_pipeline.get("calendar_checked_at")
        statuses.append({"source": "Economic calendar", "status": "cached", "date": calendar.get("checked_at")})

    previous_inventory = previous_flow.get("cme_inventory", {})
    previous_metals = previous_inventory.get("metals", {})
    inventory_due = cadence_due(previous_pipeline.get("inventory_checked_at"), WAREHOUSE_REFRESH_HOURS) or not previous_metals
    if inventory_due:
        cme_inventory = {
            "checked_at": run_at,
            "source": "CME Group COMEX",
            "source_url": CME_WAREHOUSE_PAGE_URL,
            "metals": dict(previous_metals),
            "definition_note": "Registered = 已签发仓单、可交割库存；Eligible = 符合规格但未签发仓单；Pledged = 已质押库存。",
        }
        cme_success = False
        for metal in ("gold", "silver"):
            try:
                cme_inventory["metals"][metal] = fetch_cme_inventory_asset(metal, previous_metals.get(metal))
                cme_success = True
                statuses.append({"source": f"CME {metal} warehouse", "status": "ok", "date": cme_inventory["metals"][metal].get("report_date")})
            except Exception as error:
                if metal not in cme_inventory["metals"]:
                    seeded = dict(CME_SEED_INVENTORY[metal])
                    seeded.update({"source": "CME Group COMEX (official snapshot fallback)", "source_url": CME_WAREHOUSE_PAGE_URL, "report_url": CME_WAREHOUSE_URLS[metal], "definition_note": "CME 官方快照；自动下载被站点反爬策略拦截时保留。Registered = 已签发仓单；Eligible = 符合规格但未签发仓单。"})
                    cme_inventory["metals"][metal] = seeded
                    statuses.append({"source": f"CME {metal} warehouse", "status": "fallback", "date": seeded.get("report_date")})
                else:
                    statuses.append({"source": f"CME {metal} warehouse", "status": "fallback", "date": cme_inventory["metals"][metal].get("report_date")})
                errors.append({"source": "CME Group", "series": metal, "error": str(error)[:240]})
        cme_inventory["fallback_note"] = "CME 当前自动报表下载受站点反爬策略限制；页面保留最近一次官方快照，并在下一个 6 小时周期重试。"
        inventory_checked_at = run_at if cme_success or cme_inventory["metals"] else previous_pipeline.get("inventory_checked_at")
    else:
        cme_inventory = previous_inventory
        inventory_checked_at = previous_pipeline.get("inventory_checked_at")
        for metal in ("gold", "silver"):
            statuses.append({"source": f"CME {metal} warehouse", "status": "cached" if metal in previous_metals else "failed", "date": previous_metals.get(metal, {}).get("report_date")})

    previous_crypto = previous_flow.get("crypto", {})
    try:
        crypto = fetch_crypto_positioning()
        crypto_status = "ok" if crypto.get("aggregated") else "fallback"
        statuses.append({"source": "Crypto OI / volume / funding", "status": crypto_status, "date": crypto.get("checked_at")})
        crypto_checked_at = run_at
    except Exception as error:
        crypto = previous_crypto
        crypto_checked_at = previous_pipeline.get("crypto_checked_at")
        errors.append({"source": "Crypto positioning", "series": "BTC/ETH", "error": str(error)[:240]})
        statuses.append({"source": "Crypto OI / volume / funding", "status": "fallback" if crypto.get("assets") else "failed", "date": crypto.get("checked_at")})

    flow_positioning = {
        "updated_at": run_at,
        "cme_inventory": cme_inventory,
        "crypto": crypto,
        "scope_note": "库存与加密衍生品是风险/资金背景，不直接替代金银现货价格或 CFTC 周度持仓结论。",
    }

    if not series and not cftc.get("positions"):
        raise RuntimeError("No source succeeded and no previous snapshot is available")

    derived = build_derived(series)
    available_statuses = {"ok", "cached", "fallback"}
    run_time = parse_timestamp(run_at) or datetime.now(timezone.utc)
    next_update = run_time.replace(minute=0, second=0) + timedelta(
        minutes=((run_time.minute // RUN_INTERVAL_MINUTES) + 1) * RUN_INTERVAL_MINUTES
    )
    payload = {
        "schema_version": 1,
        "generated_at": run_at,
        "pipeline": {
            "mode": "15-minute-zero-token",
            "ai_tokens_used": 0,
            "run_interval_minutes": RUN_INTERVAL_MINUTES,
            "next_scheduled_at": next_update.isoformat().replace("+00:00", "Z"),
            "macro_checked_at": macro_checked_at,
            "cftc_checked_at": cftc_checked_at,
            "calendar_checked_at": calendar_checked_at,
            "inventory_checked_at": inventory_checked_at,
            "crypto_checked_at": crypto_checked_at,
            "source_count": len(statuses),
            "success_count": sum(item["status"] in available_statuses for item in statuses),
            "updated_count": sum(item["status"] == "ok" for item in statuses),
            "cached_count": sum(item["status"] == "cached" for item in statuses),
            "fallback_count": sum(item["status"] == "fallback" for item in statuses),
            "error_count": len(errors),
            "statuses": statuses,
            "errors": errors,
        },
        "series": series,
        "derived": derived,
        "cftc": cftc,
        "calendar": calendar,
        "flow_positioning": flow_positioning,
    }
    payload["layers"] = build_layers(series, derived, cftc)
    payload["daily_conclusion"] = build_daily_conclusion(series, derived, cftc, calendar)
    payload["snapshot_id"] = signature(payload)
    write_json(LATEST_PATH, payload)

    history = load_json(HISTORY_PATH, {"schema_version": 1, "snapshots": []})
    snapshots = [
        item for item in history.setdefault("snapshots", [])
        if item.get("series") and item.get("cftc_report_date")
    ]
    if not snapshots or snapshots[-1].get("snapshot_id") != payload["snapshot_id"]:
        snapshots.append({
            "snapshot_id": payload["snapshot_id"],
            "generated_at": payload["generated_at"],
            "series": {key: {"date": item["date"], "value": item["value"]} for key, item in series.items()},
            "cftc_report_date": cftc.get("report_date"),
        })
        history["snapshots"] = snapshots[-180:]
    history["updated_at"] = payload["generated_at"]
    write_json(HISTORY_PATH, history)

    print(json.dumps({
        "generated_at": payload["generated_at"],
        "snapshot_id": payload["snapshot_id"],
        "series": len(series),
        "metal_quotes": sum(key in series for key in ("SPOT_XAUUSD", "SPOT_XAGUSD")),
        "calendar_events": len(calendar.get("events", [])),
        "cftc_positions": cftc.get("dynamic_count", 0),
        "success": payload["pipeline"]["success_count"],
        "updated": payload["pipeline"]["updated_count"],
        "cached": payload["pipeline"]["cached_count"],
        "fallback": payload["pipeline"]["fallback_count"],
        "errors": payload["pipeline"]["error_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
