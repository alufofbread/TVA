import unittest
from network_membership import merge_report


class NetworkMembershipTests(unittest.TestCase):
    def payload(self, observed='2026-10-19', people=()):
        return {'report': {'end': observed}, 'creators': [{'id': id, 'handle': handle} for id, handle in people]}

    def test_departure_preserves_other_members_and_original_input(self):
        initial={'version':1,'creators':{}}
        active=merge_report(initial,self.payload(people=[('1','alice'),('2','bob')]),[],'2026-10-20T10:00:00Z')
        left=merge_report(active,self.payload('2026-10-20',[('1','alice')]),['bob'],'2026-10-21T10:00:00Z')
        self.assertTrue(left['creators']['alice']['active'])
        self.assertFalse(left['creators']['bob']['active'])
        self.assertTrue(active['creators']['bob']['active'])
        self.assertEqual(initial['creators'],{})

    def test_old_report_cannot_resurrect_departed_member(self):
        left=merge_report({'version':1,'creators':{}},self.payload('2026-10-20'),['bob'],'2026-10-21T10:00:00Z')
        replay=merge_report(left,self.payload(people=[('2','bob')]),[],'2026-10-22T10:00:00Z')
        self.assertFalse(replay['creators']['bob']['active'])
        rejoined=merge_report(replay,self.payload('2026-10-23',[('2','bob')]),[],'2026-10-24T10:00:00Z')
        self.assertTrue(rejoined['creators']['bob']['active'])

    def test_same_day_revision_order_and_utc_offsets(self):
        left=merge_report({'version':1,'creators':{}},self.payload(),['bob'],'2026-10-20T10:00:00+00:00')
        replay=merge_report(left,self.payload(people=[('2','bob')]),[],'2026-10-20T09:30:00Z')
        self.assertFalse(replay['creators']['bob']['active'])

    def test_invalid_or_conflicting_status_does_not_replace_feed(self):
        with self.assertRaises(ValueError):merge_report({'version':1,'creators':{}},self.payload(people=[('1','alice')]),['alice'],'2026-10-20T10:00:00Z')
        with self.assertRaises(ValueError):merge_report({'version':1,'creators':{}},self.payload(),['invalid handle'],'2026-10-20T10:00:00Z')
        with self.assertRaises(ValueError):merge_report({},self.payload(),[],'2026-10-20T10:00:00Z')
