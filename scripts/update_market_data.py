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
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("MARKET_SITE_ROOT", Path(__file__).resolve().parents[1]))
DATA_DIR = ROOT / "markets" / "data"
LATEST_PATH = DATA_DIR / "latest.json"
HISTORY_PATH = DATA_DIR / "history.json"
USER_AGENT = "PengfeiMarketDashboard/1.0 (+https://pengfeiintuebingen.github.io/markets/)"

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
CFTC_DISAGG_URL = "https://www.cftc.gov/dea/newcot/c_disagg.txt"
CFTC_TFF_URL = "https://www.cftc.gov/dea/newcot/FinComWk.txt"

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


def request_text(url: str, attempts: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/csv,text/plain,application/xml,*/*"},
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
                ["curl", "--http1.1", "--fail", "--silent", "--show-error", "-L", "-A", USER_AGENT, "--max-time", "60", url],
                check=True,
                capture_output=True,
                text=True,
                timeout=70,
            )
            return completed.stdout
        except (subprocess.SubprocessError, OSError) as curl_error:
            last_error = curl_error
    raise RuntimeError(f"download failed: {url}: {last_error}")


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


def derived_metric(label: str, value: float | None, unit: str, date: str | None, source: str) -> dict[str, Any]:
    return {"label": label, "value": round_value(value, 4), "unit": unit, "date": date, "source": source}


def build_derived(series: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest_date = lambda key: series.get(key, {}).get("date")
    value = lambda key: series.get(key, {}).get("value")
    dgs10, dgs2 = value("DGS10"), value("DGS2")
    walcl_change = change(series.get("WALCL"))
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


def signature(payload: dict[str, Any]) -> str:
    compact = {
        "series": {key: [item.get("date"), item.get("value")] for key, item in payload.get("series", {}).items()},
        "cftc": [payload.get("cftc", {}).get("report_date"), [[item["name"], item["contracts"]] for item in payload.get("cftc", {}).get("positions", [])]],
    }
    return hashlib.sha256(json.dumps(compact, sort_keys=True).encode()).hexdigest()[:16]


def main() -> int:
    previous = load_json(LATEST_PATH, {})
    previous_series = previous.get("series", {})
    series: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []

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

    try:
        cftc, cftc_missing = fetch_cftc()
        errors.extend(cftc_missing)
        statuses.append({"source": "CFTC", "status": "ok", "date": cftc.get("report_date")})
    except Exception as error:
        cftc = previous.get("cftc", {"positions": [], "dynamic_count": 0, "target_count": 10})
        errors.append({"source": "CFTC", "series": "COT", "error": str(error)[:240]})
        statuses.append({"source": "CFTC", "status": "fallback" if cftc.get("positions") else "failed"})

    if not series and not cftc.get("positions"):
        raise RuntimeError("No source succeeded and no previous snapshot is available")

    derived = build_derived(series)
    payload = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "pipeline": {
            "mode": "low-cost-dynamic",
            "ai_tokens_used": 0,
            "source_count": len(statuses),
            "success_count": sum(item["status"] == "ok" for item in statuses),
            "fallback_count": sum(item["status"] == "fallback" for item in statuses),
            "error_count": len(errors),
            "statuses": statuses,
            "errors": errors,
        },
        "series": series,
        "derived": derived,
        "cftc": cftc,
    }
    payload["layers"] = build_layers(series, derived, cftc)
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
        "cftc_positions": cftc.get("dynamic_count", 0),
        "success": payload["pipeline"]["success_count"],
        "fallback": payload["pipeline"]["fallback_count"],
        "errors": payload["pipeline"]["error_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
