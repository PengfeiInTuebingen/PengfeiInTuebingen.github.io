"""EIA WPSR: exact table schemas, dated stock levels and weekly changes."""
from __future__ import annotations
import csv
import io
import math
import re
import subprocess
import urllib.request
from datetime import datetime, date
from html import unescape

WPSR_PAGE = 'https://www.eia.gov/petroleum/supply/weekly/'
TABLE4_URL = 'https://ir.eia.gov/wpsr/table4.csv'
TABLE9_URL = 'https://ir.eia.gov/wpsr/table9.csv'


def _get(url, timeout=25):
    request = urllib.request.Request(url, headers={'User-Agent': 'PengfeiMarketResearch/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode('utf-8-sig', errors='replace')
    except (OSError, ValueError):
        # Use the operating-system certificate store; never disable TLS checks.
        result = subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                                 '--proto', '=https', '--proto-redir', '=https',
                                 '--max-time', str(timeout), url], check=True,
                                capture_output=True, timeout=timeout + 3)
        return result.stdout.decode('utf-8-sig', errors='replace')


def _number(value):
    value = value.strip().replace(',', '')
    if value in {'', '-', '--', 'NA', 'N/A', '—', '�'}:
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except ValueError:
        return None


def _date(value):
    for form in ('%m/%d/%y', '%m/%d/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(value.strip(), form).date()
        except ValueError:
            pass
    raise ValueError('Invalid EIA table date')


def _table(text, stub_count):
    if '<html' in text[:1000].lower() or '<!doctype' in text[:1000].lower():
        raise ValueError('EIA returned HTML instead of CSV')
    rows = list(csv.reader(io.StringIO(text.strip('\ufeff\x1a\r\n'))))
    expected = ['STUB_' + str(i + 1) for i in range(stub_count)]
    if not rows or rows[0][:stub_count] != expected or len(rows[0]) != 8:
        raise ValueError('EIA table header changed')
    if any(len(r) != 8 for r in rows[1:] if r and any(c.strip() for c in r)):
        raise ValueError('EIA table has truncated or inconsistent rows')
    current, previous = map(_date, rows[0][stub_count:stub_count + 2])
    if (current - previous).days != 7 or current > date.today():
        raise ValueError('EIA table does not contain consecutive completed weeks')
    return rows, current, previous


def _find(rows, keys):
    matches = [r for r in rows[1:] if [c.strip() for c in r[:len(keys)]] == list(keys)]
    if len(matches) != 1:
        raise ValueError('EIA row missing or duplicated: ' + ' / '.join(keys))
    return matches[0]


def _publication(page, label):
    plain = unescape(re.sub('<[^>]*>', ' ', page))
    plain = re.sub(r'\s+', ' ', plain)
    match = re.search(r'(?<!Next )' + re.escape(label) + r':\s*([A-Za-z]+\.?)\s+(\d{1,2}),\s+(\d{4})', plain)
    if not match:
        return None
    month = match[1].replace('.', '')[:3]
    try:
        return datetime.strptime(f'{month} {match[2]} {match[3]}', '%b %d %Y').date().isoformat()
    except ValueError:
        return None


def parse_eia(table4, table9, page=''):
    stocks, week, previous = _table(table4, 1)
    estimates, other, previous_other = _table(table9, 2)
    if (week, previous) != (other, previous_other):
        raise ValueError('EIA inventory and operating tables have different dates')
    if stocks[0][3] != 'Difference':
        raise ValueError('EIA stock change column changed')
    metrics = []
    def add(mid, label, row, column, unit, scale, url, published_change=False):
        current, prior = _number(row[column]), _number(row[column + 1])
        value = round(current * scale, 3) if current is not None else None
        before = round(prior * scale, 3) if prior is not None else None
        change = round(value - before, 3) if value is not None and before is not None else None
        if current is not None and current < 0:
            raise ValueError('Negative EIA stock/throughput level')
        if published_change:
            supplied = _number(row[column + 2])
            if supplied is not None and change is not None and abs(supplied * scale - change) > 0.002:
                raise ValueError('EIA published stock change disagrees with levels')
        metrics.append({'id': mid, 'label': label, 'value': value, 'previous': before,
                        'change': change, 'unit': unit, 'source_url': url,
                        'week_ending': week.isoformat(), 'previous_week_ending': previous.isoformat()})
    for mid, label, source_label in (
        ('commercial_crude', '商业原油（不含 SPR）', 'Commercial (Excluding SPR)'),
        ('spr', '战略石油储备 SPR', 'SPR'), ('cushing', '库欣原油（商业库存子集）', 'Cushing'),
        ('gasoline', '汽油库存', 'Total Motor Gasoline'),
        ('distillate', '馏分油库存', 'Distillate Fuel Oil')):
        add(mid, label, _find(stocks, (source_label,)), 1, '百万桶', 1, TABLE4_URL, True)
    for mid, label, category, row_label, unit, scale in (
        ('utilization', '炼厂利用率', 'Refiner Inputs and Utilization', 'Percent Utilization', '%', 1),
        ('runs', '炼厂原油加工量', 'Refiner Inputs and Utilization', 'Crude Oil Inputs', '百万桶/日', .001),
        ('imports', '原油进口（含 SPR）', 'Imports', 'Total Crude Oil Incl SPR', '百万桶/日', .001),
        ('exports', '原油出口', 'Exports', 'Crude Oil', '百万桶/日', .001)):
        add(mid, label, _find(estimates, (category, row_label)), 2, unit, scale, TABLE9_URL)
    if metrics[0]['value'] is None:
        raise ValueError('EIA commercial crude inventory missing')
    published = _publication(page, 'Release Date')
    notes = ['库欣是商业原油库存的子集，不能相加；SPR 与商业库存分列。',
             '周变化由同表相邻两周水平相减；原始值已四舍五入，可能与报告中的未舍入差值相差 0.001。']
    if not published:
        notes.append('未能核验发布日期；仅使用表格明确给出的观测周。')
    return {'status': 'ok', 'week_ending': week.isoformat(), 'published_at': published,
            'next_release_at': _publication(page, 'Next Release Date'), 'source_url': WPSR_PAGE,
            'metrics': metrics, 'notes': notes}


def fetch_eia(timeout=25):
    table4, table9 = _get(TABLE4_URL, timeout), _get(TABLE9_URL, timeout)
    try:
        page = _get(WPSR_PAGE, timeout)
    except Exception:
        page = ''
    return parse_eia(table4, table9, page)
