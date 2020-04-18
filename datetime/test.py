#!/usr/bin/env python3

import unittest
import maintenance_datetime
from argparse import ArgumentTypeError
from datetime import datetime
from pytz import common_timezones, timezone

class TestMaintenanceDatetime(unittest.TestCase):
    def test_timezones(self):
        timezones = maintenance_datetime.timezones
        for timezone in timezones:
            self.assertIn(timezone, common_timezones)

    def test_input_datetime_format(self):
        input_string = '23.01.2019 16:45'
        input_format = maintenance_datetime.in_dt_format
        result = datetime.strptime(input_string, input_format)
        self.assertEqual(result, datetime(2019, 1, 23, 16, 45))

    def test_output_datetime_format(self):
        input_datetime = datetime(2019, 1, 23, 16, 45, tzinfo=timezone('UTC'))
        output_format = maintenance_datetime.out_dt_format
        result = input_datetime.strftime(output_format)
        self.assertEqual(result, 'Wednesday, 23 January 2019, 16:45 UTC')

    def test_input_datetime_regex(self):
        input_string = '2019-12-24 11-00'
        with self.assertRaises(ArgumentTypeError):
            maintenance_datetime.dt_regex(input_string)

if __name__ == '__main__':
    unittest.main()
