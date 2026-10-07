"""GitHub credential lifecycle, after quirq-ai/xo-space#197.

gh holds the token and exactly one github.com account; a classic token without the
scopes gh needs is refused before gh sees it; disconnect signs gh out of every
account and removes what connecting wrote to the global gitconfig. No network: gh
is a mock, git is real (against a throwaway GIT_CONFIG_GLOBAL).
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from routers.hearth_agent.connectors import github_pat as github_pat_routes
from services.hearth_agent.connectors import token_store
from services.hearth_agent.connectors.github import common, gh_api, pat
from services.hearth_agent.connectors.github.gh_api import STORE_BYPASS_ENV, GhAccount, GhCli, GhErrorKind, GhResult
from utils.commands import CommandResult

CLASSIC = "ghp_" + "c" * 36
FINE = "github_pat_" + "f" * 60
VALID = {"valid": True, "status": "connected", "username": "hearth-bot", "name": "HEARTH Bot",
         "token_kind": "classic", "expires_at": None, "warnings": [], "scopes": "repo, read:org"}


def acct(login: str, active: bool = False, state: str = "success") -> GhAccount:
    return GhAccount(login, active, state)


class _StateDir(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"HEARTH_STATE_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class ScopeTests(unittest.TestCase):
    def test_only_scoped_tokens_are_checked_and_org_scopes_include_read_org(self):
        self.assertEqual(pat.missing_required_scopes(FINE, ""), [])  # fine-grained: no scopes to check
        self.assertEqual(pat.missing_required_scopes(CLASSIC, "repo, read:org"), [])
        self.assertEqual(pat.missing_required_scopes(CLASSIC, "repo, write:org"), [])
        self.assertEqual(pat.missing_required_scopes(CLASSIC, "repo"), ["read:org"])
        self.assertEqual(pat.missing_required_scopes(CLASSIC, "gist"), ["repo", "read:org"])
        self.assertEqual(pat.missing_required_scopes("a" * 40, ""), ["repo", "read:org"])  # old 40-hex classic
        self.assertEqual(pat.missing_required_scopes("gho_" + "o" * 36, "repo"), ["read:org"])


class PatConnectTests(_StateDir):
    def _gh(self, accounts=None, login=None):
        gh = mock.AsyncMock()
        gh.login_with_token.return_value = login or GhResult(True)
        gh.accounts.return_value = accounts if accounts is not None else [acct("hearth-bot", True)]
        return gh

    def _patches(self, validation=VALID, available=True):
        return [mock.patch.object(pat, "gh_available", return_value=available),
                mock.patch.object(pat, "validate_token", mock.AsyncMock(return_value=dict(validation))),
                mock.patch.object(pat, "configure_git_identity", mock.AsyncMock())]

    async def _connect(self, token, gh, **kw):
        patches = self._patches(**kw)
        for p in patches:
            p.start()
        try:
            return await pat.connect(token, gh=gh)
        finally:
            for p in patches:
                p.stop()

    async def test_classic_token_without_scopes_is_refused_before_gh(self):
        gh = self._gh()
        out = await self._connect(CLASSIC, gh, validation={**VALID, "scopes": "gist"})
        self.assertEqual((out["ok"], out["status"], out["code"]), (False, "needs_auth", pat.MISSING_SCOPES))
        self.assertEqual(out["missing_scopes"], ["repo", "read:org"])
        self.assertIn("`repo` and `read:org` scopes", out["error"])
        gh.login_with_token.assert_not_called()

    async def test_without_gh_the_token_is_refused_before_validation(self):
        validate = mock.AsyncMock()
        with mock.patch.object(pat, "gh_available", return_value=False), \
             mock.patch.object(pat, "validate_token", validate):
            out = await pat.connect(FINE, gh=self._gh())
        self.assertEqual((out["ok"], out["status"]), (False, "failed"))
        validate.assert_not_called()

    async def test_token_gh_rejects_is_stored_nowhere_and_keeps_the_current_connection(self):
        common.save_github_credential({"username": "previous-bot"}, auth_method="pat")
        gh = self._gh(login=GhResult(False, kind=GhErrorKind.ERROR, message="error validating token: missing scope"))
        out = await self._connect(FINE, gh, validation={**VALID, "token_kind": "fine_grained", "scopes": ""})
        self.assertEqual((out["ok"], out["status"]), (False, "needs_auth"))
        self.assertIn("GitHub CLI rejected this token", out["error"])
        gh.logout.assert_not_called()
        self.assertEqual(common.get_github_credential()["login"], "previous-bot")

    async def test_gh_infrastructure_failure_is_failed_not_needs_auth(self):
        gh = self._gh(login=GhResult(False, kind=GhErrorKind.TIMEOUT, message="timed out"))
        out = await self._connect(FINE, gh, validation={**VALID, "scopes": ""})
        self.assertEqual(out["status"], "failed")

    async def test_connecting_another_account_signs_gh_out_of_the_first(self):
        gh = self._gh(accounts=[acct("old-bot"), acct("hearth-bot", active=True)])
        out = await self._connect(CLASSIC, gh)
        self.assertTrue(out["ok"])
        gh.logout.assert_awaited_once_with("old-bot")
        stored = token_store.token_file().read_text(encoding="utf-8")
        self.assertIn('"login": "hearth-bot"', stored)
        self.assertNotIn(CLASSIC, stored)


class DisconnectTests(_StateDir):
    async def test_disconnect_signs_gh_out_of_every_account(self):
        common.save_github_credential({"username": "a"})
        gh = mock.AsyncMock()
        gh.accounts.side_effect = [[acct("a", True), acct("b")], []]
        with mock.patch.object(common, "_clear_git_config", mock.AsyncMock()) as clear:
            self.assertTrue(await common.disconnect_github_account(gh))
        self.assertEqual([c.args for c in gh.logout.await_args_list], [("a",), ("b",)])
        clear.assert_awaited_once()
        self.assertIsNone(common.get_github_credential())

    async def test_disconnect_reports_an_account_gh_keeps(self):
        common.save_github_credential({"username": "a"})
        gh = mock.AsyncMock()
        gh.accounts.return_value = [acct("a", True)]  # logout did not take
        with mock.patch.object(common, "_clear_git_config", mock.AsyncMock()):
            self.assertFalse(await common.disconnect_github_account(gh))
        self.assertIsNotNone(common.get_github_credential())  # a failed disconnect keeps the record

    async def test_without_an_account_list_gh_gets_the_bare_logout(self):
        gh = mock.AsyncMock()
        gh.accounts.return_value = None
        gh.auth_token.return_value = None
        with mock.patch.object(common, "_clear_git_config", mock.AsyncMock()):
            self.assertTrue(await common.disconnect_github_account(gh))
        gh.logout.assert_awaited_once_with()


@unittest.skipIf(shutil.which("git") is None, "git not installed")
class GitConfigTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / "gitconfig"
        self.cfg.write_text("", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(self.cfg)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _git(self, *args: str) -> str:
        return subprocess.run(["git", "config", "--global", *args], capture_output=True, text=True).stdout.strip()

    async def test_disconnect_removes_what_connecting_wrote_to_gitconfig(self):
        for key, value in (("user.name", "Old Bot"), ("user.email", "old@example.com"),
                           ("credential.https://github.com.helper", "!gh auth git-credential"),
                           ("credential.https://gist.github.com.helper", "!gh auth git-credential"),
                           ("core.editor", "vim")):
            subprocess.run(["git", "config", "--global", key, value], check=True)
        await common._clear_git_config()
        self.assertEqual(self._git("--get", "user.name"), "")
        self.assertEqual(self._git("--get", "credential.https://github.com.helper"), "")
        self.assertEqual(self._git("--get", "core.editor"), "vim")  # other settings stay

    async def test_the_next_account_to_connect_writes_its_own_identity(self):
        subprocess.run(["git", "config", "--global", "user.name", "Old Bot"], check=True)
        await common._clear_git_config()
        await common.configure_git_identity({"username": "hearth-bot", "user_id": 7})
        self.assertEqual(self._git("--get", "user.name"), "hearth-bot")
        self.assertEqual(self._git("--get", "user.email"), "7+hearth-bot@users.noreply.github.com")

    async def test_disconnecting_with_nothing_in_gitconfig_is_quiet(self):
        with self.assertNoLogs(common.log, level="WARNING"):
            await common._clear_git_config()


class StatusTests(_StateDir):
    def _gh(self, accounts):
        gh = mock.AsyncMock()
        gh.accounts.return_value = accounts
        gh.auth_status.return_value = mock.Mock(ok=True, login=None, message="Logged in")
        return gh

    async def test_a_terminal_sign_in_is_the_connection(self):
        out = await common.get_status(self._gh([acct("someone", True)]))
        self.assertEqual((out["status"], out["username"], out["auth_method"]), ("connected", "someone", None))

    async def test_metadata_only_describes_its_own_account(self):
        common.save_github_credential({"username": "hearth-bot", "expires_at": "2027-01-01T00:00:00+00:00"},
                                      auth_method="cli")
        mine = await common.get_status(self._gh([acct("hearth-bot", True)]))
        self.assertEqual((mine["auth_method"], mine["expires_at"]), ("cli", "2027-01-01T00:00:00+00:00"))
        other = await common.get_status(self._gh([acct("someone", True), acct("hearth-bot")]))
        self.assertEqual((other["username"], other["auth_method"]), ("someone", None))

    async def test_an_active_account_gh_cannot_use_is_not_connected(self):
        out = await common.get_status(self._gh([acct("hearth-bot", True, state="error")]))
        self.assertEqual(out["status"], "needs_auth")


class GhCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_gh_call_runs_without_the_store_bypass_variables(self):
        fake = mock.AsyncMock(return_value=CommandResult(["gh"], 0, "token", 0.1))
        with mock.patch.object(gh_api, "run", fake):
            await GhCli().auth_token()
        self.assertEqual(tuple(fake.await_args.kwargs["unset_env"]), STORE_BYPASS_ENV)

    async def test_accounts_parses_gh_json(self):
        payload = {"hosts": {"github.com": [
            {"login": "a", "active": True, "state": "success"},
            {"login": "b", "active": False, "state": "error"},
        ]}}
        fake = mock.AsyncMock(return_value=CommandResult(["gh"], 0, json.dumps(payload), 0.1))
        with mock.patch.object(gh_api, "run", fake):
            accounts = await GhCli().accounts()
        self.assertEqual(accounts, [acct("a", True), acct("b", False, "error")])
        self.assertIn("--json", fake.await_args.args[0])

    async def test_accounts_is_none_when_gh_cannot_tell(self):
        for result in (CommandResult(["gh"], 1, "", 0.1), CommandResult(["gh"], 0, "not json", 0.1)):
            with self.subTest(result=result), mock.patch.object(gh_api, "run", mock.AsyncMock(return_value=result)):
                self.assertIsNone(await GhCli().accounts())

    async def test_logout_names_the_account(self):
        fake = mock.AsyncMock(return_value=CommandResult(["gh"], 0, "", 0.1))
        with mock.patch.object(gh_api, "run", fake):
            await GhCli().logout("hearth-bot")
        self.assertEqual(fake.await_args.args[0][-2:], ["--user", "hearth-bot"])


class RouteTests(unittest.TestCase):
    def setUp(self):
        from server import app

        self.client = TestClient(app)

    def test_a_missing_scopes_refusal_reaches_the_client_as_a_code(self):
        refusal = {"ok": False, "status": "needs_auth", "code": "missing_scopes", "missing_scopes": ["read:org"],
                   "error": "missing"}
        with mock.patch.object(pat, "connect", mock.AsyncMock(return_value=refusal)):
            r = self.client.post("/api/connectors/github/token", json={"token": CLASSIC})
        self.assertEqual(r.status_code, 400)
        self.assertEqual((r.json()["code"], r.json()["missing_scopes"]), ("missing_scopes", ["read:org"]))

    def test_other_refusals_keep_their_body(self):
        with mock.patch.object(pat, "connect", mock.AsyncMock(return_value={"ok": False, "status": "failed",
                                                                            "error": "boom"})):
            r = self.client.post("/api/connectors/github/token", json={"token": CLASSIC})
        self.assertEqual((r.status_code, r.json()), (502, {"status": "failed", "error": "boom"}))

    def test_signed_out_answers_needs_auth(self):
        with mock.patch.object(github_pat_routes, "disconnect_github_account", mock.AsyncMock(return_value=True)):
            r = self.client.post("/api/connectors/github/disconnect")
        self.assertEqual((r.status_code, r.json()), (200, {"status": "needs_auth"}))

    def test_an_account_gh_still_holds_is_not_reported_as_signed_out(self):
        with mock.patch.object(github_pat_routes, "disconnect_github_account", mock.AsyncMock(return_value=False)):
            r = self.client.post("/api/connectors/github/disconnect")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()["status"], "failed")


if __name__ == "__main__":
    unittest.main()
