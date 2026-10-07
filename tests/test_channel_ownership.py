import tempfile
import unittest
from pathlib import Path
from database import Database

class ChannelOwnershipTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.db=Database(Path(temp.name)/'test.db')

    def test_second_creator_cannot_claim_channel(self):
        self.db.set_creator_channel('alice',100,1)
        with self.assertRaisesRegex(ValueError,'another creator'):
            self.db.set_creator_channel('bob',100,1)
        self.db.set_creator_channel('alice',100,1)
        with self.db.connect() as conn:
            self.assertEqual(conn.execute('select creator_id from creator_channels where channel_id=100').fetchone()[0],'alice')

    def test_moving_creator_frees_old_channel(self):
        self.db.set_creator_channel('alice',100,1)
        self.db.set_creator_channel('alice',101,1)
        self.db.set_creator_channel('bob',100,1)

    def test_legacy_shared_channels_are_not_delivered(self):
        with self.db.connect() as conn:
            for name in ['alice','bob']:
                conn.execute("insert into creators(creator_id,creator_name,last_updated) values(?,?, 'now')",(name,name))
                conn.execute("insert into creator_channels values(?,100,1,'now')",(name,))
        self.assertEqual(self.db.get_creator_channels(),[])
        self.db.set_creator_channel('bob',101,1)
        self.assertEqual(len(self.db.get_creator_channels()),2)
