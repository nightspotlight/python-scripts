#!/usr/bin/env python3

import argparse
from re import match
from datetime import datetime
from pytz import timezone
from tzlocal import get_localzone

timezones = [
    'America/Los_Angeles',
    'America/Chicago',
    'Europe/Warsaw',
    'Europe/Moscow',
    'Asia/Kolkata'
]

in_dt_format = '%d.%m.%Y %H:%M'
out_dt_format = '%A, %d %B %Y, %H:%M %Z'

def main():
    args = get_args()

    dt_begin = datetime.strptime(args['dt_begin'], in_dt_format)
    dt_end = datetime.strptime(args['dt_end'], in_dt_format)
    dt_duration = dt_end - dt_begin

    print('Maintenance start time:')
    for tz in timezones:
        print(tz_convert(dt_begin, tz).strftime(out_dt_format))

    print('')
    print('Maintenance end time:')
    for tz in timezones:
        print(tz_convert(dt_end, tz).strftime(out_dt_format))

    if args['duration']:
        print('')
        print(f"Duration: {dt_duration}")

def get_args():
    argparser = argparse.ArgumentParser(
        description='Display provided date and time in different timezones. \
            Expected format: dd.mm.YYYY HH:MM')
    argparser.add_argument('dt_begin',
        metavar='begin_date_time',
        type=dt_regex,
        help='example: "21.05.2018 21:30"')
    argparser.add_argument('dt_end',
        metavar='end_date_time',
        type=dt_regex,
        help='example: "21.05.2018 22:00"')
    argparser.add_argument('-d', '--duration',
        action='store_true',
        help='add duration to the output')
    return vars(argparser.parse_args())

def dt_regex(arg):
    """
    arg - a string to validate against regular expression
    """
    dt_re = r'\d{2}\.\d{2}\.\d{4}\ \d{2}\:\d{2}'
    if not match(dt_re, arg):
        raise argparse.ArgumentTypeError(f"does not match regular expression: {dt_re}")
    return arg

def tz_convert(dt_input, tz_target):
    """
    dt_input - naive datetime object
    tz_target - canonical timezone string, e.g. 'America/Los_Angeles'
    """
    tz_local = get_localzone()
    tz_target = timezone(tz_target)
    dt_target = tz_local.localize(dt_input).astimezone(tz_target)
    return tz_target.normalize(dt_target)

if __name__ == '__main__':
    main()
