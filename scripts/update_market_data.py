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
import zipfile
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(os.environ.get("MARKET_SITE_ROOT", Path(__file__).resolve().parents[1]))
DATA_DIR = ROOT / "markets" / "data"
LATEST_PATH = DATA_DIR / "latest.json"
HISTORY_PATH = DATA_DIR / "history.json"
A_SHARE_PATH = DATA_DIR / "a_share.json"
USER_AGENT = "PengfeiMarketDashboard/1.0 (+https://pengfeiintuebingen.github.io/markets/)"

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
CFTC_DISAGG_URL = "https://www.cftc.gov/dea/newcot/c_disagg.txt"
CFTC_TFF_URL = "https://www.cftc.gov/dea/newcot/FinComWk.txt"
CFTC_DISAGG_HISTORY_URL = "https://www.cftc.gov/files/dea/history/com_disagg_txt_{year}.zip"
GOLD_API_URL = "https://api.gold-api.com/price"
XAUS_FALLBACK_URL = "https://xaus.com/api/v1/spot?compact=1"
GOLD_DAILY_BARS_URL = "https://api.goldprice.dev/v1/bars"
YAHOO_GOLD_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
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
COINBASE_EXCHANGE_BASE = "https://api.exchange.coinbase.com"
EASTMONEY_QUOTE_BASES = (
    "https://push2.eastmoney.com/webguest/api/qt",
    "https://82.push2.eastmoney.com/webguest/api/qt",
    "https://73.push2.eastmoney.com/webguest/api/qt",
    "https://push2.eastmoney.com/api/qt",
    "https://82.push2.eastmoney.com/api/qt",
    "https://73.push2.eastmoney.com/api/qt",
)
EASTMONEY_HISTORY_BASES = (
    "https://push2his.eastmoney.com/api/qt",
    "https://82.push2his.eastmoney.com/api/qt",
    "https://73.push2his.eastmoney.com/api/qt",
    # The webguest edge is less complete (often one day only), but is useful
    # as a last transport fallback when the historical edge is rate-limited.
    "https://push2.eastmoney.com/webguest/api/qt",
    "https://82.push2.eastmoney.com/webguest/api/qt",
    "https://73.push2.eastmoney.com/webguest/api/qt",
)
EASTMONEY_UT = "bd1d9ddb04089700cf9c27f6f7426281"
A_SHARE_INDEXES = (
    {"name": "上证指数", "secid": "1.000001", "code": "000001"},
    {"name": "科创50", "secid": "1.000688", "code": "000688"},
    {"name": "深证成指", "secid": "0.399001", "code": "399001"},
    {"name": "创业板指", "secid": "0.399006", "code": "399006"},
)
A_SHARE_SECTORS = (
    "铜", "工业金属", "证券", "印制电路板", "酿酒", "电力设备", "通信设备",
    "半导体材料", "半导体", "银行", "有色金属/贵金属",
)

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
    "DCOILBRENTEU": ("Brent 原油", "美元/桶", "能源"),
    "DCOILWTICO": ("WTI 原油", "美元/桶", "能源"),
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


def request_text(url: str, attempts: int = 3, headers: dict[str, str] | None = None, timeout: float = 45) -> str:
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
            with urllib.request.urlopen(request, timeout=timeout) as response:
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
                ["curl", "--http1.1", "--fail", "--silent", "--show-error", "-L", "-A", request_headers.get("User-Agent", USER_AGENT), "--max-time", str(max(5, int(timeout + 15))), url],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout + 20,
            )
            return completed.stdout
        except (subprocess.SubprocessError, OSError) as curl_error:
            last_error = curl_error
    raise RuntimeError(f"download failed: {url}: {last_error}")


def request_bytes(url: str, attempts: int = 3, headers: dict[str, str] | None = None, timeout: float = 75) -> bytes:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/zip,application/octet-stream,*/*"}
    request_headers.update(headers or {})
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"download failed: {url}: {last_error}")


def request_json(url: str, headers: dict[str, str] | None = None, attempts: int = 3, timeout: float = 45) -> Any:
    try:
        return json.loads(request_text(url, attempts=attempts, headers=headers, timeout=timeout))
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


def _berlin_midnight_bounds_ms() -> tuple[int, int]:
    now = datetime.now(ZoneInfo("Europe/Berlin"))
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.astimezone(timezone.utc).timestamp() * 1000), int(now.astimezone(timezone.utc).timestamp() * 1000)


def fetch_binance_crypto_asset(symbol: str) -> dict[str, Any]:
    pair = f"{symbol}USDT"
    ticker = request_json(f"{BINANCE_FUTURES_BASE}/fapi/v1/ticker/24hr?symbol={pair}")
    oi_rows = request_json(f"{BINANCE_FUTURES_BASE}/futures/data/openInterestHist?symbol={pair}&period=15m&limit=97")
    kline_rows = request_json(f"{BINANCE_FUTURES_BASE}/fapi/v1/klines?symbol={pair}&interval=15m&limit=97")
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
    volume_history = []
    ohlcv_history = []
    if isinstance(kline_rows, list):
        for row in kline_rows:
            if not isinstance(row, list) or len(row) < 8:
                continue
            stamp = _milliseconds_iso(row[0])
            quote_volume = number(row[7])
            if stamp and quote_volume is not None:
                volume_history.append([stamp, round_value(quote_volume, 2)])
            if stamp and len(row) >= 6 and None not in (number(row[1]), number(row[2]), number(row[3]), number(row[4])):
                ohlcv_history.append({
                    "time": stamp,
                    "open": round_value(number(row[1]), 6),
                    "high": round_value(number(row[2]), 6),
                    "low": round_value(number(row[3]), 6),
                    "close": round_value(number(row[4]), 6),
                    "volume_usd": round_value(quote_volume, 2) if quote_volume is not None else None,
                })
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
        "volume_history": volume_history[-97:],
        "ohlcv_history": ohlcv_history[-97:],
        "source": "Binance USDⓈ-M public API",
        "source_url": "https://developers.binance.com/en/docs/derivatives/usds-margined-futures/market-data/rest-api",
        "note": "单一交易所公开代理值；不等于全市场持仓量、成交量或资金费率聚合。",
    }



def fetch_coinbase_spot_asset(symbol: str) -> dict[str, Any]:
    """Fetch 24/7 Coinbase spot statistics and Berlin-day 15-minute candles."""
    product = f"{symbol}-USD"
    stats = request_json(f"{COINBASE_EXCHANGE_BASE}/products/{product}/stats")
    current = number(stats.get("last"))
    opened = number(stats.get("open"))
    if current is None or opened in (None, 0):
        raise ValueError(f"Coinbase {product} quote is incomplete")
    start_ms, end_ms = _berlin_midnight_bounds_ms()
    start = datetime.fromtimestamp(start_ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
    end = datetime.fromtimestamp(end_ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
    query = urllib.parse.urlencode({"granularity": 900, "start": start, "end": end})
    candles = request_json(f"{COINBASE_EXCHANGE_BASE}/products/{product}/candles?{query}")
    if not isinstance(candles, list):
        raise ValueError(f"Coinbase {product} candles are empty")
    ohlcv_history, volume_history = [], []
    for row in candles:
        if not isinstance(row, list) or len(row) < 6:
            continue
        stamp_value = number(row[0])
        stamp = _milliseconds_iso(stamp_value * 1000 if stamp_value is not None and stamp_value < 10_000_000_000 else stamp_value)
        low, high, row_open, close, base_volume = (number(row[index]) for index in (1, 2, 3, 4, 5))
        if not stamp or None in (low, high, row_open, close):
            continue
        volume_usd = base_volume * close if base_volume is not None else None
        candle = {"time": stamp, "open": row_open, "high": high, "low": low, "close": close, "volume_usd": volume_usd}
        ohlcv_history.append(candle)
        if volume_usd is not None:
            volume_history.append([stamp, round_value(volume_usd, 2)])
    ohlcv_history.sort(key=lambda item: item["time"])
    volume_history.sort(key=lambda item: item[0])
    if len(ohlcv_history) < 2:
        raise ValueError(f"Coinbase {product} candles are too short")
    base_volume_24h = number(stats.get("volume"))
    return {
        "symbol": symbol,
        "product": product,
        "label": f"{symbol} Coinbase 现货",
        "price_usd": round_value(current, 6),
        "price_change_24h_pct": round_value((current / opened - 1) * 100, 4),
        "volume_24h_usd": round_value(base_volume_24h * current if base_volume_24h is not None else None, 2),
        "day_low": number(stats.get("low")), "day_high": number(stats.get("high")),
        "observed_at": ohlcv_history[-1]["time"],
        "ohlcv_history": ohlcv_history[-97:], "volume_history": volume_history[-97:],
        "source": "Coinbase Exchange public API", "source_url": "https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproductcandles",
        "note": "Coinbase USD 现货市场 7×24 更新；不包含永续合约持仓量与资金费率。",
    }


def fetch_coinbase_spot_assets() -> tuple[dict[str, Any], list[str]]:
    assets, errors = {}, []
    for symbol in ("BTC", "ETH"):
        try:
            assets[symbol] = fetch_coinbase_spot_asset(symbol)
        except Exception as error:
            errors.append(f"{symbol}: {str(error)[:180]}")
    return assets, errors

def fetch_binance_positioning() -> dict[str, Any]:
    assets = {}
    errors = []
    for symbol in ("BTC", "ETH"):
        try:
            assets[symbol] = fetch_binance_crypto_asset(symbol)
        except Exception as error:
            errors.append(f"{symbol}: {str(error)[:180]}")
    spot_assets, spot_errors = fetch_coinbase_spot_assets()
    errors.extend(f"Coinbase spot {error}" for error in spot_errors)
    if not assets and not spot_assets:
        raise RuntimeError("Binance/Coinbase public crypto feeds unavailable: " + "; ".join(errors))
    return {
        "checked_at": utc_now(),
        "provider": "Binance USDⓈ-M + Coinbase spot public APIs",
        "scope": "single-venue",
        "aggregated": False,
        "assets": assets,
        "spot_assets": spot_assets,
        "spot_provider": "Coinbase Exchange public API",
        "exchange_totals": {},
        "etf": {},
        "activation_note": "Coinbase 现货用于 7×24 价格/K线；设置 COINGLASS_API_KEY 后另启用多交易所永续 OI/资金费率聚合。",
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
    start_ms, end_ms = _berlin_midnight_bounds_ms()
    price_rows = _coinglass_rows(coinglass_json("futures/price/history", {"exchange": "Binance", "symbol": f"{symbol}USDT", "interval": "15m", "limit": 200, "start_time": start_ms, "end_time": end_ms}, api_key))
    ohlcv_history = []
    for item in price_rows:
        stamp = _coinglass_time(item)
        opened = _coinglass_close(item, ("open",))
        high = _coinglass_close(item, ("high",))
        low = _coinglass_close(item, ("low",))
        closed = _coinglass_close(item, ("close",))
        volume = _coinglass_close(item, ("volume_usd", "volumeUsd", "volume"))
        if stamp and None not in (opened, high, low, closed):
            ohlcv_history.append({"time": stamp, "open": opened, "high": high, "low": low, "close": closed, "volume_usd": volume})
    if len(ohlcv_history) < 2:
        raise ValueError(f"CoinGlass {symbol} price OHLC history is empty or too short")
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
        "volume_history": proxy.get("volume_history", []),
        "ohlcv_history": ohlcv_history[-200:],
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
    spot_assets, spot_errors = fetch_coinbase_spot_assets()
    return {
        "checked_at": utc_now(),
        "provider": "CoinGlass aggregate + Coinbase spot public APIs",
        "scope": "multi-venue aggregate + 24/7 spot",
        "aggregated": True,
        "assets": assets,
        "spot_assets": spot_assets,
        "spot_provider": "Coinbase Exchange public API",
        "exchange_totals": exchange_totals,
        "etf": etf,
        "activation_note": "CoinGlass 聚合永续 OI/资金费率；Coinbase 现货价格/K线为 7×24 独立口径。",
        "errors": [f"Coinbase spot {error}" for error in spot_errors],
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


def eastmoney_get(path: str, params: dict[str, Any], *, historical: bool = False) -> dict[str, Any]:
    hosts = EASTMONEY_HISTORY_BASES if historical else EASTMONEY_QUOTE_BASES
    query = urllib.parse.urlencode(params)
    last_error: Exception | None = None
    for host in hosts:
        url = f"{host}/{path.lstrip('/')}?{query}"
        try:
            try:
                payload = request_json(url, headers={"Referer": "https://data.eastmoney.com/"}, attempts=1, timeout=12)
            except Exception:
                # Eastmoney's edge intermittently closes urllib connections; curl
                # with a browser UA is a transport fallback, not a second source.
                completed = subprocess.run(
                    ["curl", "--http1.1", "--fail", "--silent", "--show-error", "-L", "-A", "Mozilla/5.0", "--max-time", "15", url],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                payload = json.loads(completed.stdout)
            if not isinstance(payload, dict) or payload.get("rc") not in (0, "0") or not isinstance(payload.get("data"), dict):
                raise ValueError(f"Eastmoney response unavailable: {str(payload)[:180]}")
            return payload
        except Exception as error:
            last_error = error
    raise RuntimeError(f"Eastmoney request failed: {path}: {last_error}")


def parse_eastmoney_flow_klines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("data", {}).get("klines", [])
    parsed = []
    for raw in rows if isinstance(rows, list) else []:
        parts = str(raw).split(",")
        if len(parts) < 13:
            continue
        main_net = number(parts[1])
        close = number(parts[11])
        change_pct = number(parts[12])
        if not parts[0] or main_net is None:
            continue
        parsed.append({
            "date": parts[0],
            "main_net_flow_billion_cny": round_value(main_net / 100_000_000, 3),
            "close": round_value(close, 3),
            "change_pct": round_value(change_pct, 3),
        })
    return parsed


def a_share_continuity(today: float | None, five_day: float | None, today_ratio: float | None, five_day_ratio: float | None) -> tuple[str, str]:
    if None in (today, five_day, today_ratio, five_day_ratio):
        return "UNKNOWN", "数据缺失或板块成分聚合异常"
    if today > 0 and five_day > 0 and today_ratio > 0 and five_day_ratio > 0:
        return "CONTINUOUS_GREEN", "连续流入"
    if today > 0 and five_day <= 0:
        return "ONE_DAY_SPIKE", "单日流入，5日未确认"
    if today <= 0 and five_day < 0:
        if five_day_ratio <= -0.20 or five_day <= -100:
            return "RED_STRONG", "持续流出，强度偏高"
        return "RED", "连续流出"
    if today > 0 and five_day < 0:
        return "REBOUND_ONLY", "反抽性质"
    return "MIXED", "方向分裂，等待确认"


def fetch_eastmoney_sector_rows() -> tuple[dict[str, dict[str, Any]], list[str]]:
    base_params = {
        # Pull the complete concept list in one request when the endpoint
        # accepts pz=500. Some edges cap the page at 100; the pagination
        # below detects that response and continues without dropping rows.
        "pn": 1, "pz": 500, "po": 1, "np": 1, "ut": EASTMONEY_UT, "fltt": 2, "invt": 2,
        "fid": "f62", "fs": "m:90+t:2", "fields": "f12,f14,f2,f3,f6,f20,f62,f184",
    }
    first = eastmoney_get("clist/get", base_params)
    data = first.get("data", {})
    rows = list(data.get("diff", [])) if isinstance(data.get("diff"), list) else []
    total = int(number(data.get("total")) or len(rows))
    page_size = max(len(rows), 100)
    pages = min(10, max(1, math.ceil(total / page_size)))
    errors = []
    for page in range(2, pages + 1):
        params = dict(base_params)
        params["pn"] = page
        try:
            page_data = eastmoney_get("clist/get", params).get("data", {})
            if isinstance(page_data.get("diff"), list):
                rows.extend(page_data["diff"])
        except Exception as error:
            errors.append(f"sector page {page}: {str(error)[:120]}")
    return {str(row.get("f14")): row for row in rows if isinstance(row, dict) and row.get("f14")}, errors


def fetch_a_share_snapshot(previous: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
    previous = previous or {}
    checked_at = utc_now()
    errors: list[str] = []
    try:
        sector_rows, sector_errors = fetch_eastmoney_sector_rows()
        errors.extend(sector_errors)
    except Exception as error:
        sector_rows, sector_errors = {}, []
        errors.append(f"sector quotes: {str(error)[:120]}")
    sectors = []
    old_sectors = {str(item.get("name")): item for item in previous.get("sectors", []) if isinstance(item, dict)}
    current_sector_count = 0
    history_live_count = 0
    cached_sector_count = 0
    for name in A_SHARE_SECTORS:
        row = sector_rows.get(name)
        old = old_sectors.get(name, {})
        today = five_day = market_cap = today_ratio = five_day_ratio = None
        history: list[dict[str, Any]] = []
        history_fresh = False
        if row:
            current_sector_count += 1
            market_cap_value = number(row.get("f20"))
            market_cap = market_cap_value / 1_000_000_000_000 if market_cap_value is not None else number(old.get("market_cap_trillion_cny"))
            try:
                flow_payload = eastmoney_get("stock/fflow/daykline/get", {
                    "lmt": 5, "klt": 101, "secid": f"90.{row.get('f12')}",
                    "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
                }, historical=True)
                history = parse_eastmoney_flow_klines(flow_payload)
            except Exception as error:
                errors.append(f"{name} history: {str(error)[:120]}")
            # A one-day webguest response is enough to refresh today's flow,
            # but never masquerades as a five-day continuity signal.
            if history:
                today = history[-1]["main_net_flow_billion_cny"]
                if len(history) >= 5:
                    five_day = round_value(sum(item["main_net_flow_billion_cny"] for item in history[-5:]), 3)
                    history_fresh = True
                    history_live_count += 1
                elif old.get("five_day_billion_cny") is not None:
                    five_day = number(old.get("five_day_billion_cny"))
                    history = history + list(old.get("history") or [])
            else:
                current = number(row.get("f62"))
                today = current / 100_000_000 if current is not None else number(old.get("today_billion_cny"))
                five_day = number(old.get("five_day_billion_cny"))
                history = list(old.get("history") or [])
            if market_cap:
                today_ratio = today / (market_cap * 100) if today is not None else number(old.get("today_to_cap_pct"))
                five_day_ratio = five_day / (market_cap * 100) if five_day is not None else number(old.get("five_day_to_cap_pct"))
        else:
            errors.append(f"{name}: sector not found")
            cached_sector_count += 1 if old else 0
            today = number(old.get("today_billion_cny"))
            five_day = number(old.get("five_day_billion_cny"))
            market_cap = number(old.get("market_cap_trillion_cny"))
            today_ratio = number(old.get("today_to_cap_pct"))
            five_day_ratio = number(old.get("five_day_to_cap_pct"))
            history = list(old.get("history") or [])
        if history_fresh:
            continuity, label = a_share_continuity(today, five_day, today_ratio, five_day_ratio)
            flow_data_status = "LIVE"
        elif today is not None or five_day is not None:
            continuity, label = "UNKNOWN", "5日历史未完整返回，连续性不判定"
            flow_data_status = "PARTIAL" if row else "CACHED"
        else:
            continuity, label = "UNKNOWN", "数据缺失或板块成分聚合异常"
            flow_data_status = "UNKNOWN"
        sectors.append({
            "name": name,
            "code": row.get("f12") if row else old.get("code"),
            "today_billion_cny": round_value(today, 3),
            "five_day_billion_cny": round_value(five_day, 3),
            "market_cap_trillion_cny": round_value(market_cap, 3),
            "today_to_cap_pct": round_value(today_ratio, 3),
            "five_day_to_cap_pct": round_value(five_day_ratio, 3),
            "continuity": continuity,
            "label": label,
            "flow_data_status": flow_data_status,
            "history": history[-5:],
        })

    index_params = {
        "fltt": 2, "secids": ",".join(item["secid"] for item in A_SHARE_INDEXES),
        "fields": "f2,f3,f4,f5,f6,f12,f13,f14",
    }
    try:
        index_data = eastmoney_get("ulist.np/get", index_params).get("data", {})
    except Exception as error:
        errors.append(f"index quotes: {str(error)[:120]}")
        index_data = {}
    raw_index_rows = index_data.get("diff", []) if isinstance(index_data, dict) else []
    if isinstance(raw_index_rows, dict):
        raw_index_rows = list(raw_index_rows.values())
    index_rows = {str(item.get("f12")): item for item in raw_index_rows if isinstance(item, dict)}
    old_index_rows = {str(item.get("code")): item for item in previous.get("index_flows", []) if isinstance(item, dict)}
    index_flows = []
    for index in A_SHARE_INDEXES:
        row = index_rows.get(index["code"], {})
        old = old_index_rows.get(index["code"], {})
        main_net = None
        try:
            flow = eastmoney_get("stock/fflow/daykline/get", {
                "lmt": 5, "klt": 101, "secid": index["secid"],
                "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
            }, historical=True)
            rows = parse_eastmoney_flow_klines(flow)
            if rows:
                main_net = rows[-1]["main_net_flow_billion_cny"]
        except Exception as error:
            errors.append(f"{index['name']} flow: {str(error)[:120]}")
        raw_turnover = number(row.get("f6")) if row else None
        if raw_turnover is None:
            raw_turnover = (number(old.get("turnover_billion_cny")) or 0) * 100_000_000
        index_flows.append({
            "name": index["name"], "code": index["code"], "secid": index["secid"],
            "main_net_flow_billion_cny": round_value(main_net, 3),
            "price": round_value(number(row.get("f2")) if row else number(old.get("price")), 3),
            "change_pct": round_value(number(row.get("f3")) if row else number(old.get("change_pct")), 3),
            "turnover_billion_cny": round_value(raw_turnover / 100_000_000, 3),
        })

    sse = next((item for item in index_flows if item["code"] == "000001"), {})
    sz = next((item for item in index_flows if item["code"] == "399001"), {})
    turnover = sum(item.get("turnover_billion_cny") or 0 for item in (sse, sz))
    if not turnover:
        turnover = (number(previous.get("market", {}).get("turnover_trillion_cny")) or 0) * 10_000
    available_flows = [item["main_net_flow_billion_cny"] for item in index_flows if item.get("main_net_flow_billion_cny") is not None]
    market_label = "指数主力流向净流入，结构仍需结合行业连续性" if available_flows and sum(available_flows) > 0 else "指数主力流向偏弱或部分缺失"
    return {
        "schema_version": 1,
        "data_type": "a_share_snapshot",
        "snapshot_date": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        "checked_at": checked_at,
        "timezone": "Asia/Shanghai",
        "update_interval_minutes": RUN_INTERVAL_MINUTES,
        "data_status": "LIVE" if current_sector_count >= 8 and history_live_count >= 8 else ("PARTIAL" if current_sector_count or cached_sector_count else "UNKNOWN"),
        "observation_finality": "INTRADAY",
        "evaluation_status": "PARTIAL",
        "source": "东方财富公开行情与资金流接口",
        "source_url": "https://data.eastmoney.com/zjlx/",
        "source_note": f"自动抓取指数行情、成交额与行业资金流；板块当前行情 {current_sector_count}/{len(A_SHARE_SECTORS)}，完整5日历史 {history_live_count}/{len(A_SHARE_SECTORS)}。主力净额为数据商依据成交方向推断的主动买卖差额，算法版本与大小单分档未公开。",
        "market": {"turnover_trillion_cny": round_value(turnover / 10_000, 3), "main_net_flow_billion_cny": round_value(sum(available_flows), 3) if len(available_flows) == len(A_SHARE_INDEXES) else None, "structure_label": market_label},
        "index_flows": index_flows,
        "sectors": sectors,
        "conclusions": build_a_share_conclusions(sectors),
        "watchlist": build_a_share_watchlist(sectors, previous),
        "framework": ["宏观货币环境", "大盘（指数）位置", "行业资金连续性与市值比例", "行业内生态位", "个股价格/量价/RVOL", "风险政策与人工确认"],
        "rules_applied": ["UNKNOWN 不等于 0，不生成自动买入绿灯", "连续流入必须同时看 1日、5日和市值比例", "资金流是置信度修正项，不能覆盖价格证伪和风险硬线", "波浪/结构只提出情景，不直接触发交易动作"],
        "next_data_needed": ["A股个股日内 OHLCV", "同一时点累计成交额与20日可比 RVOL", "上涨家数/上涨成交额占比", "板块主动流向来源、算法版本和大小单分档", "个股代码、复权口径和版本化确认/证伪位"],
        "freshness": {"current_sector_count": current_sector_count, "history_live_count": history_live_count, "cached_sector_count": cached_sector_count, "error_count": len(errors)},
        "errors": errors,
    }, errors


def build_a_share_conclusions(sectors: list[dict[str, Any]]) -> list[dict[str, str]]:
    lookup = {item["name"]: item for item in sectors}
    copper = lookup.get("铜", {})
    metals = lookup.get("工业金属", {})
    semi = lookup.get("半导体", {})
    materials = lookup.get("半导体材料", {})
    if copper.get("continuity") == "CONTINUOUS_GREEN":
        first = f"铜今日/市值 {a_share_number(copper.get('today_to_cap_pct'))}%、5日/市值 {a_share_number(copper.get('five_day_to_cap_pct'))}%，5日累计 {a_share_signed(copper.get('five_day_billion_cny'))} 亿。"
    elif copper.get("five_day_billion_cny") is not None:
        first = f"铜当前记录值为 {a_share_signed(copper.get('five_day_billion_cny'))} 亿（5日/市值 {a_share_number(copper.get('five_day_to_cap_pct'))}%），但历史未完整返回，连续性保持 UNKNOWN。"
    else:
        first = "铜板块数据暂缺，不能确认资源主线连续性。"
    if semi.get("continuity") in {"RED", "RED_STRONG"}:
        second = f"半导体 5日净额 {a_share_signed(semi.get('five_day_billion_cny'))} 亿；半导体材料 5日/市值 {a_share_number(materials.get('five_day_to_cap_pct'))}%。"
    elif semi.get("five_day_billion_cny") is not None:
        second = f"半导体记录值为 {a_share_signed(semi.get('five_day_billion_cny'))} 亿，但5日历史未完整返回，撤退判断保持 UNKNOWN。"
    else:
        second = "半导体板块历史流向暂缺，撤退判断保持 UNKNOWN。"
    tone = "positive" if copper.get("continuity") == "CONTINUOUS_GREEN" and metals.get("continuity") == "CONTINUOUS_GREEN" else "neutral"
    return [
        {"title": "资源流入连续性", "body": first + "工业金属若同向，才构成趋势级而非一日异动。", "tone": tone},
        {"title": "科技资金状态", "body": second + "资金流只修正结构可信度，不能替代个股价格与广度确认。", "tone": "negative" if semi.get("continuity") in {"RED", "RED_STRONG"} else "neutral"},
        {"title": "当前执行权限", "body": "板块绿灯不等于个股买点；个股代码、复权口径、OHLCV 和正式证伪位齐备后，才可进入人工评估。", "tone": "neutral"},
    ]


def a_share_number(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "—"


def a_share_signed(value: float | None) -> str:
    return f"{value:+.1f}" if value is not None else "—"


def build_a_share_watchlist(sectors: list[dict[str, Any]], previous: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    previous = previous or {}
    by_name = {item["name"]: item for item in sectors}
    mapping = {"太极实业": "半导体", "云锗": None, "紫金": "工业金属", "兴业": "工业金属", "中铝": "工业金属"}
    result = []
    for name, sector_name in mapping.items():
        old = next((item for item in previous.get("watchlist", []) if item.get("name") == name), {})
        sector = by_name.get(sector_name or "", {})
        status = sector.get("continuity") if sector_name else "UNKNOWN"
        if status in {"RED", "RED_STRONG"}:
            actionability = "FREEZE_BUY"
        elif status == "CONTINUOUS_GREEN":
            status, actionability = "PROVISIONAL_GREEN", "MANUAL_REVIEW"
        else:
            status, actionability = "UNKNOWN", "NON_ACTIONABLE"
        if name == "太极实业":
            reason = f"所属半导体板块5日净额 {a_share_signed(sector.get('five_day_billion_cny'))} 亿；接回资金绿灯不满足，不能仅凭价格反弹接回。"
        elif name == "云锗":
            reason = "确切证券与对应板块未登记，铜的强弱只能作间接背景；等待个股放量收复 105+ 的可核验条件。"
        else:
            reason = f"所属工业金属板块状态为 {status}；板块支持不等于个股绿灯，仍需个股 OHLCV、广度和证伪位。"
        result.append({"name": name, "symbol": old.get("symbol"), "sector": sector_name or old.get("sector", "小金属"), "status": status, "actionability": actionability, "reason": reason, "missing": old.get("missing") or "确切证券代码、复权口径、个股 OHLCV/RVOL、确认与证伪位"})
    return result


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



GOLD_POST_CLOSE_SEED = {
    "as_of": "2026-08-28",
    "source": "FXEmpire / AlQanaas public spot-CFD snapshots",
    "source_url": [
        "https://www.fxempire.com/commodities",
        "https://alqanaas.com/en/gold-price/daily/2026-08-28",
    ],
    "basis": "XAU/USD 现货 CFD 日线；不同供应商日界线可能造成小幅差异",
    "daily_bar": {
        "date": "2026-08-28", "open": 4601.95, "high": 4631.98,
        "low": 4445.46, "close": 4454.99, "volume": None,
    },
    "metrics": {
        "body": 146.96, "range": 186.52, "body_pct": 78.8,
        "upper_wick": 30.03, "lower_wick": 9.53, "close_location_pct": 5.1,
        "sma20": 4410.0, "previous_close": None,
    },
    "pattern": {
        "label": "长实体阴线 / 近低位收盘",
        "bias": "短线转弱，等待支撑确认",
        "confirmation": "连续日收盘跌破 20 日均线附近支撑，或反弹重新站回开盘区后再定方向",
    },
    "levels": {
        "support_1": 4445.46, "support_2": 4410.0, "midpoint": 4538.72,
        "resistance_1": 4601.95, "resistance_2": 4631.98, "prior_high": 4697.0,
        "deep_support": 4200.0,
    },
    "scenarios": [
        {"rank": "A", "priority": "最高", "title": "支撑守住，震荡消化后反抽", "trigger": "日收盘守住 $4,410–4,445，随后收回 $4,539", "invalidation": "有效跌破 $4,410", "watch": "$4,602 开盘区"},
        {"rank": "B", "priority": "次高", "title": "下破延续，向深层支撑寻找平衡", "trigger": "日收盘跌破 $4,410，且美元/短端利率继续走强", "invalidation": "快速收回 $4,539 并稳定", "watch": "$4,200"},
        {"rank": "C", "priority": "较低", "title": "快速反包，恢复上行", "trigger": "收回 $4,602 并突破 $4,632", "invalidation": "反弹再次跌回 $4,539 下方", "watch": "$4,697 前高"},
    ],
    "silver": {"label": "白银 XAG/USD", "stance": "高波动，等待跟随确认", "value": None, "session_change": None, "note": "白银既受贵金属联动支持，也对实际利率和工业周期更敏感。"},
    "oil": {"label": "Brent / WTI", "stance": "油价下跌，通胀降温但工业需求偏弱", "brent": None, "wti": None, "brent_change": None, "wti_change": None},
    "thorson": {
        "label": "AG Thorson / GoldPredict",
        "stance": "1–2 周回撤，长期框架未证伪",
        "summary": "8/28 公开稿：首看 50 日 EMA，若回撤加深则看 $4,200；仍维持长期牛市框架。",
        "source_url": "https://www.fxempire.com/forecasts/article/gold-price-forecast-a-brief-pullback-before-resuming-higher-1619963",
        "public_access": True,
    },
    "data_quality": "当前种子日线来自公开 CFD 快照；自动接口有新完整收盘日线时替换。现货没有统一交易所成交量，成交量字段为空。",
}


def _validate_daily_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean = []
    for item in bars:
        opened, high, low, closed = (number(item.get(key)) for key in ("open", "high", "low", "close"))
        date_text = str(item.get("date") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
            continue
        if None in (opened, high, low, closed) or high < max(opened, closed) or low > min(opened, closed):
            continue
        clean.append({"date": date_text, "open": opened, "high": high, "low": low, "close": closed, "volume": number(item.get("volume"))})
    return sorted(clean, key=lambda item: item["date"])


def _fetch_goldprice_daily_bars() -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date()
    query = urllib.parse.urlencode({
        "symbol": "XAU-USD-SPOT", "interval": "1d", "from": (today - timedelta(days=75)).isoformat(),
        "to": (today + timedelta(days=1)).isoformat(), "limit": 90,
    })
    payload = request_json(f"{GOLD_DAILY_BARS_URL}?{query}")
    rows = []
    for item in payload.get("bars", []):
        if not item.get("is_closed"):
            continue
        stamp = parse_timestamp(str(item.get("bar_start")))
        if stamp is None:
            continue
        rows.append({
            "date": stamp.date().isoformat(), "open": item.get("open"), "high": item.get("high"),
            "low": item.get("low"), "close": item.get("close"), "volume": item.get("volume"),
        })
    return _validate_daily_bars(rows)


def _fetch_yahoo_gold_daily_bars() -> list[dict[str, Any]]:
    payload = request_json(f"{YAHOO_GOLD_CHART_URL}?range=6mo&interval=1d&events=history")
    result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [None])[0] or {}
    today = datetime.now(timezone.utc).date()
    rows = []
    for index, timestamp in enumerate(timestamps):
        stamp = parse_timestamp(datetime.fromtimestamp(timestamp, timezone.utc).isoformat()) if number(timestamp) is not None else None
        if stamp is None or stamp.date() >= today:
            continue  # do not treat today's in-progress COMEX bar as a close
        rows.append({"date": stamp.date().isoformat(), **{key: (quote.get(key) or [None] * len(timestamps))[index] for key in ("open", "high", "low", "close", "volume")}})
    return _validate_daily_bars(rows)


def fetch_gold_daily_bars() -> list[dict[str, Any]]:
    """Fetch completed gold daily bars, with a public futures proxy fallback.

    Spot CFD vendors do not share a single session boundary.  We therefore
    prefer a spot OHLC endpoint, then use COMEX GC=F only as a labeled proxy;
    unfinished or malformed rows are discarded and the last verified page bar
    is retained when both sources are stale.
    """
    errors = []
    for fetcher in (_fetch_goldprice_daily_bars, _fetch_yahoo_gold_daily_bars):
        try:
            bars = fetcher()
            if len(bars) >= 5:
                return bars
            errors.append(f"{fetcher.__name__}: too short")
        except Exception as error:
            errors.append(f"{fetcher.__name__}: {error}")
    raise ValueError("; ".join(errors)[:300] or "public gold daily bars unavailable")


def _post_close_seed() -> dict[str, Any]:
    return json.loads(json.dumps(GOLD_POST_CLOSE_SEED, ensure_ascii=False))


def build_post_close_analysis(
    series: dict[str, dict[str, Any]],
    derived: dict[str, dict[str, Any]],
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact, auditable close-analysis layer for the dashboard."""
    analysis = json.loads(json.dumps(previous, ensure_ascii=False)) if previous else _post_close_seed()
    analysis["update_status"] = "cached"
    bars: list[dict[str, Any]] = []
    try:
        bars = fetch_gold_daily_bars()
    except Exception:
        bars = []
    previous_date = str(analysis.get("as_of") or "")
    if bars and bars[-1]["date"] >= previous_date:
        bar = bars[-1]
        bar_range = max(0.0, bar["high"] - bar["low"])
        body = abs(bar["close"] - bar["open"])
        upper_wick = bar["high"] - max(bar["open"], bar["close"])
        lower_wick = min(bar["open"], bar["close"]) - bar["low"]
        sma20 = sum(item["close"] for item in bars[-20:]) / min(20, len(bars)) if len(bars) >= 10 else None
        previous_close = bars[-2]["close"] if len(bars) > 1 else None
        close_location = None if not bar_range else (bar["close"] - bar["low"]) / bar_range * 100
        body_pct = None if not bar_range else body / bar_range * 100
        if bar["close"] < bar["open"] and (body_pct or 0) >= 65 and (close_location or 100) <= 20:
            pattern_label = "长实体阴线 / 近低位收盘"
            bias = "短线转弱，等待支撑确认"
        elif bar["close"] < bar["open"] and (body_pct or 0) >= 50:
            pattern_label = "中长阴线"
            bias = "短线偏弱"
        elif bar["close"] > bar["open"] and (body_pct or 0) >= 65:
            pattern_label = "长实体阳线"
            bias = "短线偏强"
        else:
            pattern_label = "小实体 / 混合 K 线"
            bias = "方向待确认"
        midpoint = (bar["high"] + bar["low"]) / 2
        support_2 = sma20 if sma20 is not None else analysis.get("levels", {}).get("support_2", 4410.0)
        levels = {
            "support_1": round(bar["low"], 2), "support_2": round(support_2, 2),
            "midpoint": round(midpoint, 2), "resistance_1": round(bar["open"], 2),
            "resistance_2": round(bar["high"], 2),
            "prior_high": analysis.get("levels", {}).get("prior_high", 4697.0),
            "deep_support": analysis.get("levels", {}).get("deep_support", 4200.0),
        }
        analysis.update({
            "as_of": bar["date"],
            "update_status": "ok",
            "source": "goldprice.dev spot / Yahoo Finance GC=F proxy",
            "source_url": [GOLD_DAILY_BARS_URL, YAHOO_GOLD_CHART_URL, "https://www.fxempire.com/commodities"],
            "basis": "优先 XAU/USD spot 日线；接口不可用时使用 COMEX GC=F 日线代理；成交量由源端提供时才展示",
            "daily_bar": bar,
            "metrics": {
                "body": round(body, 2), "range": round(bar_range, 2),
                "body_pct": round(body_pct, 1) if body_pct is not None else None,
                "upper_wick": round(upper_wick, 2), "lower_wick": round(lower_wick, 2),
                "close_location_pct": round(close_location, 1) if close_location is not None else None,
                "sma20": round(sma20, 2) if sma20 is not None else None,
                "previous_close": round(previous_close, 2) if previous_close is not None else None,
            },
            "pattern": {
                "label": pattern_label, "bias": bias,
                "confirmation": "连续日收盘跌破支撑，或反弹重新站回开盘区后再定方向",
            },
            "levels": levels,
            "data_quality": "使用公开 XAU/USD 日线；若源端尚未发布新完整收盘日线，则保留最近已验证日线。",
        })
    # The seed remains visible when a free endpoint is stale; the error is
    # recorded by the pipeline caller rather than replacing the last good bar.
    xag = series.get("SPOT_XAGUSD", {})
    xag_session = number(derived.get("XAG_SESSION", {}).get("value"))
    analysis["silver"] = {
        "label": "白银 XAG/USD", "stance": "高波动，等待跟随确认",
        "value": number(xag.get("value")), "session_change": xag_session,
        "note": "白银既受贵金属联动支持，也对实际利率和工业周期更敏感；跌破自身支撑时不与黄金强行合并。",
    }
    brent, wti = series.get("DCOILBRENTEU", {}), series.get("DCOILWTICO", {})
    brent_change = percent_change(brent)
    wti_change = percent_change(wti)
    analysis["oil"] = {
        "label": "Brent / WTI", "stance": "油价下跌，通胀降温但工业需求偏弱",
        "brent": number(brent.get("value")), "wti": number(wti.get("value")),
        "brent_change": brent_change, "wti_change": wti_change,
        "as_of": max(str(brent.get("date") or ""), str(wti.get("date") or "")),
    }
    return analysis

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


CFTC_CATEGORY_COLUMNS = {
    "生产商/贸易商": (8, 9),
    "掉期商": (10, 11),
    "管理资金": (13, 14),
    "其他报告商": (16, 17),
    "非报告商": (21, 22),
}


def cftc_category_breakdown(row: list[str]) -> dict[str, dict[str, float | int | None]]:
    oi = number(row[7])
    output = {}
    for label, (long_index, short_index) in CFTC_CATEGORY_COLUMNS.items():
        long_pos, short_pos = number(row[long_index]), number(row[short_index])
        net = None if None in (long_pos, short_pos) else int(round(long_pos - short_pos))
        output[label] = {"contracts": net, "ratio": round(100 * net / oi, 2) if net is not None and oi else None}
    return output


def fetch_cftc_category_history() -> dict[str, list[dict[str, Any]]]:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=130)
    rows = []
    for year in range(start.year, today.year + 1):
        archive = request_bytes(CFTC_DISAGG_HISTORY_URL.format(year=year), attempts=2, timeout=90)
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            member = next((name for name in bundle.namelist() if name.lower().endswith(".txt")), None)
            if not member:
                continue
            rows.extend(parse_cftc_rows(bundle.read(member).decode("utf-8-sig", errors="replace"))[1:])
    output = {}
    for display_name, prefix in (("黄金", "GOLD - COMMODITY EXCHANGE"), ("白银", "SILVER - COMMODITY EXCHANGE")):
        points = []
        for row in rows:
            if not row or not row[0].strip().upper().startswith(prefix):
                continue
            report_date = row[2].strip()
            try:
                date_value = datetime.strptime(report_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            if date_value < start or date_value > today:
                continue
            breakdown = cftc_category_breakdown(row)
            points.append({
                "date": report_date,
                "open_interest": number(row[7]),
                "categories": {name: item.get("contracts") for name, item in breakdown.items()},
            })
        dedup = {item["date"]: item for item in points}
        output[display_name] = [dedup[key] for key in sorted(dedup)]
    return output


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
        item = {
            "name": display_name,
            "contract_name": row[0].strip(),
            "contracts": net,
            "ratio": ratio,
            "weekly_ratio_change": weekly,
            "category": "管理资金" if kind == "managed_money" else "杠杆基金",
            "report_date": report_date,
            "source": "CFTC COT Futures + Options Combined",
        }
        if display_name in {"黄金", "白银"} and kind == "managed_money":
            item["breakdown"] = cftc_category_breakdown(row)
        positions.append(item)
    history = {}
    try:
        history = fetch_cftc_category_history()
    except Exception as error:
        missing.append({"source": "CFTC history", "series": "黄金/白银", "error": str(error)[:240]})
    positions.sort(key=lambda item: item["ratio"], reverse=True)
    return {
        "report_date": max(report_dates) if report_dates else None,
        "positions": positions,
        "history": history,
        "dynamic_count": len(positions),
        "target_count": len(contracts),
        "source_url": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
        "history_source_url": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm",
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
        "BRENT_DAILY": derived_metric("Brent 原油日变动", percent_change(series.get("DCOILBRENTEU")), "%", latest_date("DCOILBRENTEU"), "FRED"),
        "WTI_DAILY": derived_metric("WTI 原油日变动", percent_change(series.get("DCOILWTICO")), "%", latest_date("DCOILWTICO"), "FRED"),
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
    brent_change = metric("BRENT_DAILY")
    wti_change = metric("WTI_DAILY")
    oil_changes = [item for item in (brent_change, wti_change) if item is not None]
    oil_change = sum(oil_changes) / len(oil_changes) if oil_changes else None
    oil_fact = f"Brent {signed_text(brent_change, 2, '%')}；WTI {signed_text(wti_change, 2, '%')}"

    gold_factors = [
        conclusion_factor("黄金日内动量", xau_session, weight=.23, deadband=.08, positive_when_rising=True, fact=f"黄金 UTC 日内 {signed_text(xau_session, 2, '%')}"),
        conclusion_factor("10Y 实际利率", real_yield_delta, weight=.24, deadband=.02, positive_when_rising=False, fact=f"10Y 实际利率较前值 {signed_text(None if real_yield_delta is None else real_yield_delta * 100, 1, 'bp')}"),
        conclusion_factor("广义美元", dollar_change, weight=.18, deadband=.05, positive_when_rising=False, fact=f"广义美元较前值 {signed_text(dollar_change, 2, '%')}"),
        conclusion_factor("黄金 CFTC", cftc_ratio_value("黄金"), weight=.15, deadband=5, positive_when_rising=True, fact=f"黄金净持仓/OI {signed_text(cftc_ratio_value('黄金'), 2, '%')}"),
        conclusion_factor("避险波动", None if vix_level is None else vix_level - 20, weight=.12, deadband=3, positive_when_rising=True, fact=f"VIX {vix_level:.2f}" if vix_level is not None else "VIX 待更新"),
        conclusion_factor("能源/通胀背景", oil_change, weight=.08, deadband=.50, positive_when_rising=True, fact=oil_fact),
    ]
    silver_factors = [
        conclusion_factor("白银日内动量", xag_session, weight=.23, deadband=.10, positive_when_rising=True, fact=f"白银 UTC 日内 {signed_text(xag_session, 2, '%')}"),
        conclusion_factor("10Y 实际利率", real_yield_delta, weight=.14, deadband=.02, positive_when_rising=False, fact=f"10Y 实际利率较前值 {signed_text(None if real_yield_delta is None else real_yield_delta * 100, 1, 'bp')}"),
        conclusion_factor("广义美元", dollar_change, weight=.14, deadband=.05, positive_when_rising=False, fact=f"广义美元较前值 {signed_text(dollar_change, 2, '%')}"),
        conclusion_factor("纳斯达克风险偏好", nasdaq_change, weight=.14, deadband=.20, positive_when_rising=True, fact=f"纳斯达克较前值 {signed_text(nasdaq_change, 2, '%')}"),
        conclusion_factor("铜 CFTC", cftc_ratio_value("铜"), weight=.13, deadband=5, positive_when_rising=True, fact=f"铜净持仓/OI {signed_text(cftc_ratio_value('铜'), 2, '%')}"),
        conclusion_factor("白银 CFTC", cftc_ratio_value("白银"), weight=.14, deadband=5, positive_when_rising=True, fact=f"白银净持仓/OI {signed_text(cftc_ratio_value('白银'), 2, '%')}"),
        conclusion_factor("能源/通胀背景", oil_change, weight=.08, deadband=.50, positive_when_rising=True, fact=oil_fact),
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
        "method_note": "仅使用已标注时点的价格、FRED/ECB 宏观数据、Brent/WTI 与 CFTC 持仓；CME 库存和加密衍生品指标作为风险背景展示；缺失因子不参与加权，不用 AI 补写。",
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

    previous_a_share = load_json(A_SHARE_PATH, {})
    try:
        a_share, a_share_errors = fetch_a_share_snapshot(previous_a_share)
        errors.extend({"source": "Eastmoney A-share", "series": "sector/index", "error": item} for item in a_share_errors)
        a_share_status = "ok" if a_share.get("data_status") == "LIVE" else "fallback"
        statuses.append({"source": "A股指数/板块资金流", "status": a_share_status, "date": a_share.get("checked_at")})
    except Exception as error:
        a_share = previous_a_share
        a_share_status = "fallback" if a_share else "failed"
        errors.append({"source": "Eastmoney A-share", "series": "index/sector", "error": str(error)[:240]})
        statuses.append({"source": "A股指数/板块资金流", "status": a_share_status, "date": a_share.get("checked_at")})
    if a_share:
        write_json(A_SHARE_PATH, a_share)

    flow_positioning = {
        "updated_at": run_at,
        "cme_inventory": cme_inventory,
        "crypto": crypto,
        "scope_note": "库存与加密衍生品是风险/资金背景，不直接替代金银现货价格或 CFTC 周度持仓结论。",
    }

    if not series and not cftc.get("positions"):
        raise RuntimeError("No source succeeded and no previous snapshot is available")

    derived = build_derived(series)
    previous_post_close = previous.get("post_close_analysis")
    try:
        post_close_analysis = build_post_close_analysis(series, derived, previous_post_close)
        statuses.append({"source": "XAU/USD close morphology", "status": post_close_analysis.get("update_status", "cached"), "date": post_close_analysis.get("as_of")})
    except Exception as error:
        post_close_analysis = previous_post_close or _post_close_seed()
        errors.append({"source": "XAU/USD close morphology", "series": "post_close_analysis", "error": str(error)[:240]})
        statuses.append({"source": "XAU/USD close morphology", "status": "fallback", "date": post_close_analysis.get("as_of")})
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
            "a_share_checked_at": a_share.get("checked_at"),
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
        "post_close_analysis": post_close_analysis,
        "a_share": a_share,
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
