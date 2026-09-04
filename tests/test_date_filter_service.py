from datetime import date, timedelta
import unittest

from services.date_filter_service import DateFilterService


class DateFilterServiceTests(unittest.TestCase):
    def test_future_window_starts_today(self):
        service = DateFilterService()
        start_date, end_date = service.get_future_event_range()

        self.assertEqual(start_date, date.today())
        self.assertGreaterEqual(end_date, date.today() + timedelta(weeks=52))

    def test_manual_date_parsing_supports_historic_dates(self):
        service = DateFilterService()

        self.assertEqual(service.parse_manual_date("25-10-24"), date(2024, 10, 25))


if __name__ == "__main__":
    unittest.main()
