import copy
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from update_research_data import refresh_source, validate


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 8, 6, tzinfo=timezone.utc)
        self.metric = {'id': 'commercial_crude', 'value': 424.46}
        self.old = {'status': 'ok', 'week_ending': '2026-08-28', 'metrics': [self.metric],
                    'checked_at': '2026-09-05T00:00:00Z', 'fetched_at': '2026-09-05T00:00:00Z'}

    def refresh(self, fetcher, old=None):
        return refresh_source(self.old if old is None else old, fetcher, 'week_ending', 'https://www.eia.gov/', self.now)

    def test_failure_retains_observation_and_last_success(self):
        before = copy.deepcopy(self.old)
        def fail():
            raise ValueError('download failed')
        result = self.refresh(fail)
        self.assertEqual(result['status'], 'stale')
        self.assertEqual(result['fetched_at'], self.old['fetched_at'])
        self.assertEqual(result['week_ending'], '2026-08-28')
        self.assertEqual(self.old, before)
        self.assertEqual(self.refresh(fail, {})['status'], 'unavailable')

    def test_older_and_future_reports_rejected(self):
        for day in ('2026-08-21', '2026-09-11'):
            result = self.refresh(lambda: {'week_ending': day, 'metrics': [self.metric]})
            self.assertEqual(result['status'], 'stale')
            self.assertEqual(result['week_ending'], '2026-08-28')

    def test_cadence_does_not_fetch_or_retimestamp(self):
        old = dict(self.old, checked_at='2026-09-08T01:00:00Z')
        def forbidden():
            self.fail('must use cached block')
        self.assertEqual(self.refresh(forbidden, old), old)

    def test_old_report_download_stays_stale(self):
        result = self.refresh(lambda: {'week_ending': '2026-08-01', 'metrics': [self.metric]}, {})
        self.assertEqual(result['status'], 'stale')

    def test_missing_core_and_error_status_rejected(self):
        for candidate in ({'week_ending': '2026-08-28', 'metrics': []},
                          dict(self.old, status='error')):
            self.assertEqual(self.refresh(lambda: candidate)['status'], 'stale')

    def test_mixed_cftc_dates_rejected(self):
        block = {'report_date': '2026-09-01', 'boards': [{'products': [{'report_date': '2026-08-25'}]}]}
        with self.assertRaises(ValueError):
            validate(block, 'report_date', self.now)


if __name__ == '__main__':
    unittest.main()
