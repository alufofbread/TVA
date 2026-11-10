import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from database import Database
from website_sync import sync_channel_mappings


class ChannelDepartureTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.db=Database(Path(folder.name)/'test.db')
        with self.db.connect() as conn:
            conn.execute("insert into creators(creator_id,creator_name,last_updated) values('creator','handle','now')")
        self.db.set_creator_channel('creator',100,1)

    def sync(self, rows):
        with patch.dict(os.environ,{'DISCORD_GUILD_ID':'123'}),patch('onboarding.rpc',return_value=rows):
            sync_channel_mappings(self.db)

    def test_departure_preserves_deleted_channel_mapping_and_history(self):
        self.sync([dict(id='creator',agency_active=False,channel_id='100')])
        self.assertEqual(self.db.get_creator_channels(),[])
        with self.db.connect() as conn:
            self.assertEqual(conn.execute('select channel_id from creator_channels').fetchone()[0],100)
            self.assertEqual(conn.execute('select count(*) from creators').fetchone()[0],1)
        self.sync([dict(id='creator',agency_active=True,channel_id='101')])
        self.assertEqual(self.db.get_creator_channels()[0].channel_id,101)

    def test_legacy_roster_without_departure_flag_remains_deliverable(self):
        self.sync([dict(id='creator',channel_id='100')])
        self.assertEqual(len(self.db.get_creator_channels()),1)

    def test_empty_or_invalid_roster_does_not_infer_departures(self):
        self.sync([])
        self.assertEqual(len(self.db.get_creator_channels()),1)
        with self.assertRaises(ValueError):self.sync({'unavailable':True})
        self.assertEqual(len(self.db.get_creator_channels()),1)

    def test_rpc_outage_keeps_previous_delivery_state(self):
        self.sync([dict(id='creator',agency_active=False)])
        with patch.dict(os.environ,{'DISCORD_GUILD_ID':'123'}),patch('onboarding.rpc',side_effect=OSError('unavailable')):
            with self.assertRaises(OSError):sync_channel_mappings(self.db)
        self.assertEqual(self.db.get_creator_channels(),[])
