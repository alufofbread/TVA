import unittest
from importer import get_tier
from dashboard.style import league_name
from dashboard.league_badges import badge_name


class LeagueBoundaryTests(unittest.TestCase):
    def test_league_changes_only_at_confirmed_boundary(self):
        cases=[(0,1,'Rising'),(99999,1,'Rising'),(100000,2,'Star'),
               (199999,2,'Star'),(200000,3,'Star'),(299999,3,'Star'),
               (300000,4,'Premier'),(499999,4,'Premier'),
               (500000,5,'Elite'),(699999,5,'Elite'),(700000,6,'Elite'),
               (999999,6,'Elite'),(1000000,7,'Millionaire'),
               (1599999,7,'Millionaire'),(1600000,8,'Millionaire'),
               (2499999,8,'Millionaire'),(2500000,9,'Icon'),
               (4999999,9,'Icon'),(5000000,10,'Icon')]
        for diamonds,tier,name in cases:
            with self.subTest(diamonds=diamonds):
                self.assertEqual(get_tier(diamonds),tier)
                self.assertEqual(league_name(get_tier(diamonds)),name)
                self.assertEqual(badge_name(name),name.lower())
