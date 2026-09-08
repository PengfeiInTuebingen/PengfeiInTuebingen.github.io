#!/usr/bin/env python3
"""Build the independently cached CFTC/EIA page bundle without AI calls."""
from __future__ import annotations
import argparse
import copy
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from cftc_research import fetch_cftc
from eia_inventory import fetch_eia

ROOT = Path(os.environ.get('MARKET_SITE_ROOT', Path(__file__).resolve().parents[1]))
TARGET = ROOT / 'markets/data/research.json'
SOURCES = {
    'cftc': (fetch_cftc, 'report_date', 'https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm'),
    'eia': (fetch_eia, 'week_ending', 'https://www.eia.gov/petroleum/supply/weekly/'),
}


def stamp(value):
    return value.isoformat().replace('+00:00', 'Z')


def read_previous(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def validate(block, key, now, previous=None):
    if block.get('status') == 'error':
        raise ValueError('Source reported a validation error')
    observed = date.fromisoformat(block[key])
    if observed > now.date():
        raise ValueError('Source observation is in the future')
    if previous and previous.get(key) and block[key] < previous[key]:
        raise ValueError('Source returned an older report; retained the last valid report')
    if key == 'report_date':
        products = [p for b in block.get('boards', []) for p in b.get('products', [])]
        if not products or any(p.get('report_date') != block[key] for p in products):
            raise ValueError('CFTC data empty or mixed observation dates')
        if previous and previous.get('boards'):
            old_ids = {p['id'] for b in previous['boards'] for p in b.get('products', [])}
            lost_ids = old_ids - {p['id'] for p in products}
            # Missing contracts are not zero; source explains their absence.
            if lost_ids:
                block.setdefault('missing', []).append({'error': '上次可用但本期缺失的合约：' + ', '.join(sorted(lost_ids))})
    else:
        commercial = next((m for m in block.get('metrics', []) if m.get('id') == 'commercial_crude'), None)
        if not commercial or commercial.get('value') is None:
            raise ValueError('EIA commercial crude inventory is missing')
        if block.get('published_at') and not block[key] <= block['published_at'] <= now.date().isoformat():
            raise ValueError('EIA release date outside valid observation window')
    # Observation dates, not retrieval timestamps, determine freshness.
    return (now.date() - observed).days <= 12


def refresh_source(previous, fetcher, date_key, source_url, now, force=False):
    previous = previous or {}
    try:
        checked = datetime.fromisoformat(previous.get('checked_at', '').replace('Z', '+00:00'))
        if not force and timedelta(0) <= now - checked < timedelta(hours=12):
            cached = copy.deepcopy(previous)
            if cached.get(date_key) and not validate(cached, date_key, now):
                cached.update(status='stale', error='报告已超过正常周报观察窗口，保留原始日期。')
            return cached
    except (ValueError, TypeError, KeyError):
        pass
    try:
        result = fetcher()
        fresh = validate(result, date_key, now, previous)
        result.update(checked_at=stamp(now), fetched_at=stamp(now), status='ok' if fresh else 'stale')
        if not fresh:
            result['error'] = '官方源仍返回较早周报，尚无近期观测。'
        if result.get('missing'):
            result['status'] = 'stale'
            result['error'] = '部分合约缺失；仅展示本期已核验品种，缺失不等于零。'
        return result
    except Exception as exc:
        result = copy.deepcopy(previous)
        result.update(checked_at=stamp(now), source_url=result.get('source_url') or source_url,
                      status='stale' if result.get(date_key) else 'unavailable', error=str(exc)[:240])
        # Never redate a retained snapshot after failure.
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    previous = read_previous(TARGET)
    result = {'schema_version': 1, 'generated_at': stamp(now), 'poll_hours': 12,
              'reference_url': 'https://www.workbuddy.link/p/sZtveaphmOb61FGYSLnLy4',
              'reference_note': '参考四板块框架；数据由 CFTC / EIA 官方源核验，不复制旧快照。'}
    for name, (fetcher, key, url) in SOURCES.items():
        result[name] = refresh_source(previous.get(name), fetcher, key, url, now, args.force)
    if all(result[name] == previous.get(name) for name in SOURCES):
        print('Research sources cached inside 12-hour polling window; no changes.')
        return
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temp = TARGET.with_suffix('.json.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temp.replace(TARGET)
    print(json.dumps({name: {key: result[name].get(key) for key in ('status', 'report_date', 'week_ending', 'error')} for name in SOURCES}, ensure_ascii=False))


if __name__ == '__main__':
    main()
