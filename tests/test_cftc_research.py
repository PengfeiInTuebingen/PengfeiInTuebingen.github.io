import csv
import io
import unittest
from scripts import cftc_research as c


def row(width, spec, values=None, day='2026-08-25'):
    r = ['0'] * width
    r[0], r[2], r[3] = spec[3], day, spec[2]
    r[7] = '100'
    li, si = (13, 14) if width == 191 else (14, 15)
    r[li], r[si] = '10', '5'
    for index, value in (values or {}).items():
        r[index] = str(value)
    # Put the offsetting position into producer/dealer for balanced fixtures.
    net = int(r[li]) - int(r[si])
    r[8], r[9] = str(max(-net, 0)), str(max(net, 0))
    return r


def csvtext(rows):
    stream = io.StringIO()
    csv.writer(stream).writerows(rows)
    return stream.getvalue()


def sample():
    return ([row(191, spec) for spec in c.M + c.E + c.A],
            [row(87, spec) for spec in c.F])


def products(block):
    return {p['id']: p for b in block['boards'] for p in b['products']}


class CftcTests(unittest.TestCase):
    def test_gold_reference_denominator_divergence(self):
        d, t = sample()
        d[0] = row(191, c.M[0], {7: 644992, 13: 163217, 14: 11902,
                               55: 83175, 61: 6044, 62: 651})
        block = c.parse_cftc(csvtext(d), csvtext(t))
        p = products(block)
        self.assertEqual(len(p), 29)
        self.assertEqual(block['missing'], [])
        gold = p['gold']
        self.assertEqual(gold['net'], 151315)
        self.assertEqual(gold['net_change'], 5393)
        self.assertEqual(gold['net_oi_pct'], 23.46)
        self.assertEqual(gold['net_oi_change_pp'], -2.51)
        self.assertIn('分母', gold['interpretation'])

    def test_tff_offsets_and_short_covering(self):
        d, t = sample()
        t[0] = row(87, c.F[0], {7: 1000, 14: 200, 15: 500, 24: 0, 31: 0, 32: -50})
        p = products(c.parse_cftc(csvtext(d), csvtext(t)))['ust_10y']
        self.assertEqual(p['report_family'], 'tff')
        self.assertEqual(p['cohort'], '杠杆基金')
        self.assertEqual(p['net'], -300)
        self.assertEqual(p['net_change'], 50)
        self.assertIn('净空收窄', p['interpretation'])
        self.assertIn('基差套保', p['interpretation'])

    def test_zero_and_missing_change(self):
        d, t = sample()
        d[0] = row(191, c.M[0], {7: 0, 13: 0, 14: 0, 61: ''})
        p = products(c.parse_cftc(csvtext(d), csvtext(t)))['gold']
        self.assertIsNone(p['net_oi_pct'])
        self.assertIsNone(p['net_change'])
        self.assertIsNone(p['net_oi_change_pp'])

    def test_html_columns_and_mixed_dates_fail(self):
        d, t = sample()
        for bad in ('<html>Error</html>', 'x,y'):
            with self.assertRaises(ValueError):
                c.parse_cftc(bad, csvtext(t))
        t[0][2] = '2026-08-18'
        with self.assertRaises(ValueError):
            c.parse_cftc(csvtext(d), csvtext(t))

    def test_duplicate_bad_balance_and_future_not_silent_zero(self):
        for bad_type in ('duplicate', 'balance', 'negative', 'future'):
            d, t = sample()
            if bad_type == 'duplicate':
                d.append(d[0])
            elif bad_type == 'balance':
                d[0][8] = '999'
            elif bad_type == 'negative':
                d[0][13] = '-5'
            else:
                d[0][2] = '2099-01-01'
            result = c.parse_cftc(csvtext(d), csvtext(t))
            self.assertNotIn('gold', products(result))
            self.assertTrue(any(x['product'] == 'gold' for x in result['missing']))

    def test_previous_oi_not_positive_disables_ratio_change(self):
        d, t = sample()
        d[0][55] = '101'
        p = products(c.parse_cftc(csvtext(d), csvtext(t)))['gold']
        self.assertIsNone(p['net_oi_change_pp'])

if __name__ == '__main__':
    unittest.main()
