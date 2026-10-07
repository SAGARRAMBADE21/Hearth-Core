import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from services.hearth_agent.connectors import token_store
from services.hearth_agent.connectors.github import (
    GhErrorKind,
    RepoMirror,
    branch_name,
    common,
    expiry_warning,
    parse_bot_command,
    pat,
    render_pr,
)
from services.hearth_agent.connectors.github.gh_api import GhResult, _parse_include_output, classify
from services.hearth_agent.models import AgentResult, ValidationCommandResult, ValidationResult
from tests import fixtures
from utils.commands import CommandResult


class GhApiTests(unittest.TestCase):
    def test_parse_include_output(self):
        out = 'HTTP/2.0 200 OK\r\nEtag: W/"abc"\r\nX-Ratelimit-Remaining: 4999\r\n\r\n{"sha": "1"}'
        status, headers, body = _parse_include_output(out)
        self.assertEqual((status, headers["etag"], body), (200, 'W/"abc"', '{"sha": "1"}'))
        self.assertIsNone(_parse_include_output("not http")[0])
        self.assertEqual(GhResult(True, headers=headers).rate.remaining, 4999)

    def test_classify(self):
        cases = [
            (CommandResult(["gh"], 4, "", 0.1), None, GhErrorKind.NOT_AUTHENTICATED),
            (CommandResult(["gh"], 1, "", 0.1, stderr="gh: Not Found (HTTP 404)"), None, GhErrorKind.NOT_FOUND),
            (CommandResult(["gh"], 1, "", 0.1, stderr="API rate limit exceeded"), None, GhErrorKind.RATE_LIMITED),
            (CommandResult(["gh"], 1, "", 0.1), 403, GhErrorKind.FORBIDDEN),
            (CommandResult(["gh"], 1, "", 0.1), 422, GhErrorKind.CONFLICT),
            (CommandResult(["gh"], -1, "", 0, binary_missing=True), None, GhErrorKind.NO_CLI),
            (CommandResult(["gh"], -9, "", 0, timed_out=True), None, GhErrorKind.TIMEOUT),
        ]
        for result, status, kind in cases:
            with self.subTest(kind=kind):
                self.assertEqual(classify(result, status), kind)


class BotAndPrTests(unittest.TestCase):
    def test_bot_commands(self):
        self.assertEqual(parse_bot_command("/hearth retry").action, "retry")
        cmd = parse_bot_command("thanks!\n/hearth revise use the shared client wrapper")
        self.assertEqual((cmd.action, cmd.argument), ("revise", "use the shared client wrapper"))
        self.assertIsNone(parse_bot_command("/hearth revise"))  # revise needs instructions
        self.assertIsNone(parse_bot_command("hearth retry"))
        self.assertIsNone(parse_bot_command("/hearth deploy"))

    def test_branch_and_pr_body(self):
        cr, job = fixtures.change_record(), fixtures.job()
        self.assertTrue(branch_name(cr).startswith("hearth/stripe-17.0.0-"))
        result = AgentResult(
            job_id="job_1", intelligence="claude_code", status="passed", summary="Swapped to paymentIntents.",
            files_changed=["src/pay.ts"], needs_human_attention=["Check webhook handler"],
            validation=ValidationResult(phase="candidate", passed=True, commands=[
                ValidationCommandResult(command="pnpm test", exit_code=0, duration_seconds=3.0)]),
        )
        baseline = ValidationResult(phase="baseline", passed=True, commands=[
            ValidationCommandResult(command="pnpm test", exit_code=0, duration_seconds=3.0)])
        pr = render_pr(cr, job.impact_report, result, baseline=baseline)
        self.assertTrue(pr.title.startswith("chore(deps): migrate stripe to v17.0.0"))
        self.assertIn("| `pnpm test` | ✅ pass | ✅ pass |", pr.body)
        self.assertIn("Check webhook handler", pr.body)
        self.assertIn("hearth:migration", pr.labels)


class CredentialTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"HEARTH_STATE_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_expiry_warning(self):
        now = datetime(2026, 10, 8, tzinfo=UTC)
        self.assertIsNone(expiry_warning((now + timedelta(days=60)).isoformat(), now=now))
        self.assertIn("expires in 10", expiry_warning((now + timedelta(days=10)).isoformat(), now=now))
        self.assertIn("expired", expiry_warning((now - timedelta(days=1)).isoformat(), now=now))

    async def test_connect_hands_token_to_gh_and_stores_no_token(self):
        token = "github_pat_" + "a" * 40
        validation = {"valid": True, "status": "connected", "username": "hearth-bot", "token_kind": "fine_grained",
                      "expires_at": None, "warnings": []}
        gh = mock.AsyncMock()
        gh.login_with_token.return_value = GhResult(True)
        with mock.patch.object(pat, "validate_token", mock.AsyncMock(return_value=validation)), \
             mock.patch.object(pat, "configure_git_identity", mock.AsyncMock()):
            out = await pat.connect(token, gh=gh)
        self.assertTrue(out["ok"])
        gh.login_with_token.assert_awaited_once_with(token)
        stored = token_store.token_file().read_text(encoding="utf-8")
        self.assertIn("hearth-bot", stored)
        self.assertNotIn(token, stored)  # the token lives in gh, never in token.json

    async def test_connect_rejects_invalid_token_before_gh(self):
        gh = mock.AsyncMock()
        bad = {"valid": False, "status": "needs_auth", "error": "Token is invalid or revoked."}
        with mock.patch.object(pat, "validate_token", mock.AsyncMock(return_value=bad)):
            out = await pat.connect("ghp_" + "x" * 36, gh=gh)
        self.assertFalse(out["ok"])
        gh.login_with_token.assert_not_called()

    async def test_status_marks_unhealthy_when_gh_logged_out(self):
        common.save_github_credential({"username": "hearth-bot"})
        gh = mock.AsyncMock()
        gh.auth_status.return_value = mock.Mock(ok=False, login=None, message="not logged in")
        status = await common.get_status(gh)
        self.assertEqual(status["status"], "needs_auth")
        self.assertFalse(common.get_github_credential()["healthy"])


@unittest.skipIf(shutil.which("git") is None, "git not installed")
class RepoMirrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_export_has_no_remote_and_diffs(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            src = tmp / "src"
            git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
            subprocess.run([*git, "init", "-q", "-b", "main", str(src)], check=True)
            (src / "app.py").write_text("import stripe\nstripe.Charge.create()\n")
            subprocess.run([*git, "-C", str(src), "add", "."], check=True)
            subprocess.run([*git, "-C", str(src), "commit", "-q", "-m", "init"], check=True)

            mirror = RepoMirror(root=tmp / "vol", repo="acme/shop")
            mirror.mirror_dir.parent.mkdir(parents=True)
            subprocess.run(["git", "clone", "-q", "--bare", str(src), str(mirror.mirror_dir)], check=True)

            sha = await mirror.resolve("main")
            ws = tmp / "ws"
            await mirror.export_tree(sha, ws)
            self.assertTrue((ws / "app.py").exists())
            remotes = subprocess.run(["git", "-C", str(ws), "remote"], capture_output=True, text=True).stdout
            self.assertEqual(remotes.strip(), "")  # the sandbox never gets a remote (or a credential)

            (ws / "app.py").write_text("import stripe\nstripe.PaymentIntent.create()\n")
            self.assertEqual(await RepoMirror.changed_files(ws), ["app.py"])
            self.assertIn("PaymentIntent", await RepoMirror.diff_against_baseline(ws))


if __name__ == "__main__":
    unittest.main()
