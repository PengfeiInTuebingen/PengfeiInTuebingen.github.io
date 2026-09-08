import unittest
from scripts import eia_inventory as e

STOCKS = '''STUB_1,8/28/26,8/21/26,Difference,8/29/25,Percent Change,8/30/24,Percent Change
Commercial (Excluding SPR),424.460,428.910,-4.450,420.707,0.9,418.310,1.5
SPR,286.604,289.726,-3.122,404.710,-29.2,379.672,-24.5
Cushing,22.508,22.428,0.080,24.222,-7.1,26.394,-14.7
Total Motor Gasoline,205.669,206.842,-1.173,218.539,-5.9,219.242,-6.2
Distillate Fuel Oil,104.187,103.391,0.796,115.923,-10.1,115.275,-9.6
'''
OPERATIONS = '''STUB_1,STUB_2,8/28/26,8/21/26,8/29/25,8/30/24,8/28/26,8/29/25
Refiner Inputs and Utilization,Crude Oil Inputs,"17,496","17,393",16869,16900,17366,17034
Refiner Inputs and Utilization,Percent Utilization,98.0,97.4,94.3,93.3,97.2,95.5
Imports,Total Crude Oil Incl SPR,6770,6158,6742,5792,6715,6598
Exports,Crude Oil,4483,3792,3884,3756,3850,3911
'''
PAGE = '<span>Release Date:</span><span>Sept. 2, 2026</span><span>Next Release Date:</span>Sept. 10, 2026'

class EiaTests(unittest.TestCase):
    def test_units_dates_and_changes(self):
        block = e.parse_eia(STOCKS, OPERATIONS, PAGE)
        data = {m['id']: m for m in block['metrics']}
        self.assertEqual(block['published_at'], '2026-09-02')
        self.assertEqual(block['next_release_at'], '2026-09-10')
        self.assertEqual(data['commercial_crude']['change'], -4.45)
        self.assertEqual(data['cushing']['change'], .08)
        self.assertEqual(data['imports']['value'], 6.77)
        self.assertEqual(data['exports']['change'], .691)
        self.assertEqual(data['runs']['change'], .103)
        self.assertEqual(data['utilization']['change'], .6)

    def test_html_missing_and_nan(self):
        with self.assertRaises(ValueError):
            e.parse_eia('<html>Access denied</html>', OPERATIONS)
        for value in ('-', '', 'NaN', 'inf'):
            self.assertIsNone(e._number(value))
        self.assertEqual(e._number('0'), 0)

    def test_all_table_dates_and_previous_week_checked(self):
        for invalid in (OPERATIONS.replace('8/28/26', '8/27/26'),
                        OPERATIONS.replace('8/21/26', '8/20/26')):
            with self.assertRaises(ValueError):
                e.parse_eia(STOCKS, invalid)

    def test_missing_value_is_not_zero(self):
        result = e.parse_eia(STOCKS.replace('Cushing,22.508', 'Cushing,-'), OPERATIONS)
        cushing = next(m for m in result['metrics'] if m['id'] == 'cushing')
        self.assertIsNone(cushing['value'])
        self.assertIsNone(cushing['change'])

    def test_missing_core_duplicate_and_wrong_columns_fail(self):
        for invalid in (STOCKS.replace('424.460', '-'), STOCKS + STOCKS.splitlines()[1] + '\n',
                        STOCKS.replace('Difference', 'BadColumn'), STOCKS.replace('-4.450', '2.000')):
            with self.assertRaises(ValueError):
                e.parse_eia(invalid, OPERATIONS)

    def test_next_release_never_used_as_publication(self):
        self.assertIsNone(e._publication('Next Release Date: Sept. 10, 2026', 'Release Date'))

if __name__ == '__main__':
    unittest.main()
