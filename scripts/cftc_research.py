"""Strict parser for official CFTC disaggregated and TFF COT reports."""
from __future__ import annotations
import csv,datetime as dt,io,urllib.request,subprocess
from pathlib import Path
DISAGG_URL="https://www.cftc.gov/dea/newcot/c_disagg.txt"; TFF_URL="https://www.cftc.gov/dea/newcot/FinComWk.txt"
M=[("gold","黄金","088691","GOLD - COMMODITY EXCHANGE INC."),("silver","白银","084691","SILVER - COMMODITY EXCHANGE INC."),("copper","铜","085692","COPPER- #1 - COMMODITY EXCHANGE INC."),("platinum","铂金","076651","PLATINUM - NEW YORK MERCANTILE EXCHANGE"),("palladium","钯金","075651","PALLADIUM - NEW YORK MERCANTILE EXCHANGE"),("lithium","氢氧化锂","189691","LITHIUM HYDROXIDE  - COMMODITY EXCHANGE INC."),("aluminum","铝·美国中西部升水","191693","ALUMINUM MWP - COMMODITY EXCHANGE INC.")]
E=[("wti","WTI·NYMEX","067651","WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE"),("brent_nymex","布伦特·NYMEX","06765T","BRENT LAST DAY - NEW YORK MERCANTILE EXCHANGE"),("ulsd","纽约港超低硫柴油","022651","NY HARBOR ULSD - NEW YORK MERCANTILE EXCHANGE")]
A=[("corn","玉米","002602","CORN - CHICAGO BOARD OF TRADE"),("soybeans","大豆","005602","SOYBEANS - CHICAGO BOARD OF TRADE"),("soybean_meal","豆粕","026603","SOYBEAN MEAL - CHICAGO BOARD OF TRADE"),("soybean_oil","豆油","007601","SOYBEAN OIL - CHICAGO BOARD OF TRADE"),("lean_hogs","瘦肉猪","054642","LEAN HOGS - CHICAGO MERCANTILE EXCHANGE"),("cotton","棉花","033661","COTTON NO. 2 - ICE FUTURES U.S."),("sugar","白糖","080732","SUGAR NO. 11 - ICE FUTURES U.S.")]
F=[("ust_10y","美债10Y期货","043602","UST 10Y NOTE - CHICAGO BOARD OF TRADE"),("ust_2y","美债2Y期货","042601","UST 2Y NOTE - CHICAGO BOARD OF TRADE"),("ust_bond","美债长期国债期货","020601","UST BOND - CHICAGO BOARD OF TRADE"),("sofr_3m","3个月 SOFR","134741","SOFR-3M - CHICAGO MERCANTILE EXCHANGE"),("euro","欧元","099741","EURO FX - CHICAGO MERCANTILE EXCHANGE"),("yen","日元","097741","JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE"),("sp500","标普500·合并","13874+","S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE"),("nasdaq100","纳斯达克100·合并","20974+","NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE"),("msci_em","MSCI新兴市场","244042","MSCI EM INDEX - ICE FUTURES U.S."),("bitcoin","比特币·CME","133741","BITCOIN - CHICAGO MERCANTILE EXCHANGE"),("ether","以太坊·CME","146021","ETHER CASH SETTLED - CHICAGO MERCANTILE EXCHANGE")]
F.append(("usd", "美元指数", "098662", "USD INDEX - ICE FUTURES U.S."))
BOARDS=(("metals","金属","metals",M,"managed_money"),("energy","能源","energy",E,"managed_money"),("agriculture","农产品","agriculture",A,"managed_money"),("financial","金融","financial",F,"leveraged_funds"))
def _n(v):
    try: return int(v.strip().replace(",","")) if v.strip() and v.strip() not in {"-","--","—","N/A","NA"} else None
    except ValueError:return None
def _rows(t,w):
    if "<html" in t[:1000].lower() or "<!doctype" in t[:1000].lower(): raise ValueError("CFTC download is HTML, not a text report")
    r=[x for x in csv.reader(io.StringIO(t)) if x]
    if not r or any(len(x)!=w for x in r): raise ValueError("CFTC report has an unexpected column count")
    return r
def _cat(r,f):
    specs=(("生产商/贸易商",8,9),("掉期交易商",10,11),("管理资金",13,14),("其他报告持仓",16,17),("非报告持仓",21,22)) if f=="managed_money" else (("交易商/中介",8,9),("资产管理机构",11,12),("杠杆基金",14,15),("其他报告持仓",17,18),("非报告持仓",22,23))
    out=[]
    for name,li,si in specs:
        dl,ds=(li+48,si+48) if f=="managed_money" else (li+17,si+17); l,s=_n(r[li]),_n(r[si]); cl,cs=_n(r[dl]),_n(r[ds])
        out.append({"name":name,"long":l,"short":s,"net":l-s if l is not None and s is not None else None,"long_change":cl,"short_change":cs,"net_change":cl-cs if cl is not None and cs is not None else None})
    return out
def _product(r, spec, cohort, report_date, url):
    pid, name, code, market = spec
    if r[0].strip() != market or r[3].strip() != code:
        raise ValueError("contract code/name mismatch")
    is_mm = cohort == "managed_money"
    indexes = (7, 13, 14, 55, 61, 62) if is_mm else (7, 14, 15, 24, 31, 32)
    oi, long, short, oi_change, dl, ds = [_n(r[i]) for i in indexes]
    if any(v is None or v < 0 for v in (oi, long, short)):
        raise ValueError("negative or missing open interest/position")
    if long > oi or short > oi:
        raise ValueError("position exceeds market open interest")
    net = long - short
    change = dl - ds if dl is not None and ds is not None else None
    prev_oi = oi - oi_change if oi_change is not None else None
    pp = None
    if oi > 0 and prev_oi is not None and prev_oi > 0 and change is not None:
        pp = round(100 * net / oi - 100 * (net - change) / prev_oi, 2)
    categories = _cat(r, cohort)
    if any(c[k] is not None and c[k] < 0 for c in categories for k in ("long", "short")):
        raise ValueError("negative category holdings")
    if all(c["net"] is not None for c in categories) and abs(sum(c["net"] for c in categories)) > 3:
        raise ValueError("category net positions do not balance (combined rounding tolerance 3)")
    if change is None:
        explanation = "周度变化缺失，不能判断本周增减仓。"
    else:
        state = "净多" if net > 0 else "净空" if net < 0 else "多空平衡"
        action = "增加" if change > 0 else "减少" if change < 0 else "不变"
        explanation = f"当前{state} {abs(net):,} 张；多头周变 {dl:+,} 张，空头周变 {ds:+,} 张，净头寸周变 {change:+,} 张。"
        if net < 0 and change > 0:
            explanation += " 净空收窄不等于已转为净多。"
        if net > 0 and change < 0:
            explanation += " 净多减少不等于已转为净空。"
        if change > 0 and ds < 0:
            explanation += " 空头减仓对净头寸回升有贡献。"
        if change < 0 and dl < 0:
            explanation += " 多头减仓对净头寸回落有贡献。"
        if pp is not None and change * pp < 0:
            explanation += " 净头寸与净/OI比率方向相反，需同时看未平仓量分母变化。"
    if pid.startswith("ust_"):
        explanation += " 美债空头可能包含基差套保，不能直接当作利率方向押注。"
    if pid == "brent_nymex":
        explanation += " 仅为NYMEX Brent Last Day合约，不代表ICE布伦特全市场。"
    if pid in ("bitcoin", "ether"):
        explanation += " 仅为CME该合约持仓，不代表全加密市场。"
    explanation += " 持仓变化不是美元资金流，也不能单独预测涨跌。"
    return {"id": pid, "name": name, "market_name": market, "contract_code": code,
            "report_family": "disaggregated" if is_mm else "tff",
            "cohort": "管理资金" if is_mm else "杠杆基金", "report_date": report_date,
            "source_url": url, "open_interest": oi, "oi_change": oi_change,
            "long": long, "short": short, "net": net, "long_change": dl, "short_change": ds,
            "net_change": change, "net_oi_pct": round(100 * net / oi, 2) if oi else None,
            "net_oi_change_pp": pp, "categories": categories, "interpretation": explanation}

def parse_cftc(disagg_text, tff_text):
    lookups, duplicates = {}, {}
    for family, text, width in (("managed_money", disagg_text, 191), ("leveraged_funds", tff_text, 87)):
        lookup, duplicate = {}, set()
        for row in _rows(text, width):
            code = row[3].strip()
            if code in lookup:
                duplicate.add(code)
            lookup[code] = row
        lookups[family], duplicates[family] = lookup, duplicate
    boards, missing, dates = [], [], []
    for bid, bname, _, specs, cohort in BOARDS:
        products = []
        for spec in specs:
            row = lookups[cohort].get(spec[2])
            try:
                if row is None:
                    raise ValueError("contract not present in correct report family")
                if spec[2] in duplicates[cohort]:
                    raise ValueError("duplicate contract code")
                observed = dt.date.fromisoformat(row[2].strip())
                if observed > dt.datetime.now(dt.timezone.utc).date():
                    raise ValueError("report date is in the future")
                product = _product(row, spec, cohort, observed.isoformat(), DISAGG_URL if cohort == "managed_money" else TFF_URL)
                products.append(product)
                dates.append(observed.isoformat())
            except (ValueError, TypeError) as exc:
                missing.append({"board": bid, "product": spec[0], "error": str(exc)})
        boards.append({"id": bid, "name": bname, "cohort": "管理资金" if cohort == "managed_money" else "杠杆基金", "products": products})
    if not dates or len(set(dates)) != 1:
        raise ValueError("CFTC empty or inconsistent report dates")
    return {"report_date": dates[0], "source_url": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
            "boards": boards, "missing": missing}

def _download(url,timeout=40):
    req=urllib.request.Request(url,headers={"User-Agent":"market-data-updater/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:return r.read().decode("utf-8-sig",errors="replace")
    except Exception as first:
        try:
            p=subprocess.run(["curl","--fail","--location","--silent","--show-error","--proto","=https","--proto-redir","=https","--max-time",str(int(timeout)),"-A","market-data-updater/1.0",url],check=True,capture_output=True,timeout=timeout+2)
            return p.stdout.decode("utf-8-sig",errors="replace")
        except Exception: raise first
def fetch_cftc(fixture_paths=None,timeout=40):
    if fixture_paths: a,b=(Path(p).read_text(encoding="utf-8") for p in fixture_paths)
    else:a,b=_download(DISAGG_URL,timeout),_download(TFF_URL,timeout)
    return parse_cftc(a,b)
