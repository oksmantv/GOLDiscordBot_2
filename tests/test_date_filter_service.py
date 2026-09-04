from datetime import date, timedelta
import unittest
from types import SimpleNamespace

from services.date_filter_service import DateFilterService
from services.roster_service import _extract_name_and_rank


class DateFilterServiceTests(unittest.TestCase):
    def test_future_window_starts_today(self):
        service = DateFilterService()
        start_date, end_date = service.get_future_event_range()

        self.assertEqual(start_date, date.today())
        self.assertGreaterEqual(end_date, date.today() + timedelta(weeks=52))

    def test_manual_date_parsing_supports_historic_dates(self):
        service = DateFilterService()

        self.assertEqual(service.parse_manual_date("25-10-24"), date(2024, 10, 25))

    def test_roster_role_aliases_are_recognized(self):
        member = SimpleNamespace(
            display_name="SrAmn. Example User",
            roles=[SimpleNamespace(id=123456789, name="SrAmn.")],
        )

        clean_name, rank_prefix, rank_name, rank_order = _extract_name_and_rank(member)

        self.assertEqual(clean_name, "Example User")
        self.assertEqual(rank_prefix, "SrAmn.")
        self.assertEqual(rank_name, "Senior Airman")
        self.assertEqual(rank_order, 8)

    def test_roster_1ca_role_alias_is_recognized(self):
        member = SimpleNamespace(
            display_name="1CA. Example User",
            roles=[SimpleNamespace(id=999999999, name="1CA")],
        )

        clean_name, rank_prefix, rank_name, rank_order = _extract_name_and_rank(member)

        self.assertEqual(clean_name, "Example User")
        self.assertEqual(rank_prefix, "1CA.")
        self.assertEqual(rank_name, "First Class Airman")
        self.assertEqual(rank_order, 7)

    def test_airman_and_sramn_emoji_mapping(self):
        import services.roster_service as roster_service

        self.assertEqual(
            roster_service.RANK_EMOJI_BY_PREFIX.get("SrAmn."),
            "<:SrAmn:1503128012772610058>",
        )
        self.assertEqual(
            roster_service.RANK_EMOJI_BY_PREFIX.get("Amn."),
            "<:Airman:1545484226240053358>",
        )


if __name__ == "__main__":
    unittest.main()
