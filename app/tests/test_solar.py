from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

import solar


class ScheduleTests(unittest.TestCase):
    def local(self, hour, minute=0, second=0):
        return solar.TZ.localize(datetime(2026, 11, 6, hour, minute, second))

    def setUp(self):
        def times(when):
            date = when.date()
            return (solar.TZ.localize(datetime(date.year, date.month, date.day, 7, 3)),
                    solar.TZ.localize(datetime(date.year, date.month, date.day, 16, 23)))
        self.mock = patch.object(solar, "sun_times", side_effect=times)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_intervals_at_exact_boundaries(self):
        for date, expected in [
            (self.local(6, 59), 3600), (self.local(7, 3), 300),
            (self.local(7, 32, 59), 300), (self.local(7, 33), 1800),
            (self.local(12), 1800), (self.local(15, 52, 59), 1800),
            (self.local(15, 53), 300), (self.local(16, 22, 59), 300),
            (self.local(16, 23), 3600), (self.local(22), 3600),
        ]:
            with self.subTest(date=date):
                self.assertEqual(solar.capture_interval_seconds(date), expected)

    def test_normal_grid_is_half_hourly_by_day_hourly_at_night(self):
        self.assertEqual(solar.next_capture_time(self.local(12, 1)), self.local(12, 30))
        self.assertEqual(solar.next_capture_time(self.local(21, 1)), self.local(22))
        self.assertEqual(solar.next_capture_time(self.local(22)), self.local(23))

    def test_hourly_wait_does_not_skip_sunrise(self):
        self.assertEqual(solar.next_capture_time(self.local(7)), self.local(7, 3))

    def test_half_hour_wait_does_not_skip_sunset_window(self):
        self.assertEqual(solar.next_capture_time(self.local(15, 30)), self.local(15, 53))

    def test_six_evenly_spaced_captures_in_each_solar_window(self):
        for before, start in [(self.local(7), self.local(7, 3)), (self.local(15, 30), self.local(15, 53))]:
            date = before
            for shot in range(6):
                date = solar.next_capture_time(date)
                self.assertEqual(date, start + timedelta(minutes=shot * 5))
            self.assertGreaterEqual(solar.next_capture_time(date), start + timedelta(minutes=30))

    def test_midnight_rollover(self):
        expected = solar.TZ.localize(datetime(2026, 11, 7))
        self.assertEqual(solar.next_capture_time(self.local(23, 59)), expected)

    def test_dst_repeated_and_missing_hours(self):
        autumn = solar.TZ.localize(datetime(2026, 10, 25, 2, 30), is_dst=True)
        next_autumn = solar.next_capture_time(autumn)
        self.assertEqual(next_autumn.hour, 2)
        self.assertEqual(next_autumn.utcoffset(), timedelta(hours=1))
        self.assertGreater(next_autumn.timestamp(), autumn.timestamp())
        spring = solar.TZ.localize(datetime(2026, 3, 29, 1, 30))
        self.assertEqual(solar.next_capture_time(spring).hour, 3)


if __name__ == "__main__":
    unittest.main()
