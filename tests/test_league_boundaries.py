import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from database import Creator
from dashboard.creator_stats import render_creator_stats
from importer import get_tier
from dashboard.style import league_name
from dashboard.league_badges import badge_name


class LeagueBoundaryTests(unittest.TestCase):
    def test_card_does_not_show_stale_saved_tier(self):
        creator=Creator('fixture','example.creator',1000000,40,15,0,100,1,2,'ACHIEVED','','','','')
        with TemporaryDirectory() as folder:
            stale=Path(folder)/'stale.png'
            current=Path(folder)/'current.png'
            render_creator_stats(creator,10,stale,trend_points=[])
            render_creator_stats(replace(creator,tier=7),10,current,trend_points=[])
            self.assertEqual(stale.read_bytes(),current.read_bytes(),
                             'Saved tier 1 must not override the monthly Millionaire badge, tier label or border')
            self.assertEqual(creator.tier,1,'Rendering must preserve historical database values')

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
