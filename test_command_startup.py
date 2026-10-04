import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock
import discord
from discord import app_commands
from command_startup import register_commands,EXPECTED_GUILD_ID


class RegistrationTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        client=discord.Client(intents=discord.Intents.none())
        tree=app_commands.CommandTree(client)
        async def callback(interaction):pass
        for name in ['stats','leaderboard','import']:tree.add_command(app_commands.Command(name=name,description='Test command',callback=callback))
        commands=[SimpleNamespace(name=n) for n in ['stats','leaderboard','import']]
        tree.sync=AsyncMock(return_value=commands);tree.fetch_commands=AsyncMock(return_value=commands)
        return SimpleNamespace(tree=tree,application_id=123),discord.Object(id=EXPECTED_GUILD_ID)

    async def test_global_commands_copied_and_actual_remote_names_logged(self):
        client,guild=self.fixture();output=io.StringIO()
        with redirect_stdout(output):await register_commands(client,guild)
        client.tree.sync.assert_awaited_once_with(guild=guild)
        self.assertEqual(len(client.tree.get_commands(guild=guild)),3)
        self.assertIn('Loaded commands locally: 3',output.getvalue())
        self.assertIn(f'Synced 3 commands to guild {EXPECTED_GUILD_ID}',output.getvalue())
        self.assertIn("['stats', 'leaderboard', 'import']",output.getvalue())
        self.assertIn('bot%20applications.commands',output.getvalue())

    async def test_wrong_guild_rejected_before_registration(self):
        client,_=self.fixture()
        with self.assertRaisesRegex(RuntimeError,'wrong server'):await register_commands(client,discord.Object(id=123))
        client.tree.sync.assert_not_awaited()

    async def test_missing_remote_commands_are_reported(self):
        client,guild=self.fixture();client.tree.fetch_commands=AsyncMock(return_value=[])
        with redirect_stdout(io.StringIO()),self.assertRaisesRegex(RuntimeError,'verification failed'):await register_commands(client,guild)

    async def test_sync_failure_is_not_reported_as_success(self):
        client,guild=self.fixture();client.tree.sync=AsyncMock(side_effect=RuntimeError('Forbidden'));output=io.StringIO()
        with redirect_stdout(output),self.assertRaises(RuntimeError):await register_commands(client,guild)
        self.assertIn('registration FAILED',output.getvalue());self.assertNotIn('Synced 3',output.getvalue())


if __name__=='__main__':unittest.main()
