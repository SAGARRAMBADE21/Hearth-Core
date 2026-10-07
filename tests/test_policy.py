import unittest

from services.hearth_agent.policy import ToolPolicy


class EditPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = ToolPolicy.for_files(["src/pay.ts", "src/billing/*.ts"])

    def test_allowed(self):
        for path in ("src/pay.ts", "src/billing/client.ts", "src/__tests__/pay.test.ts", "tests/test_x.py"):
            with self.subTest(path=path):
                self.assertTrue(self.policy.check_edit(path).allowed)

    def test_denied(self):
        for path in ("src/other.ts", ".github/workflows/ci.yml", ".env", "config/.env.production",
                     "../etc/passwd", "/etc/passwd", ".git/config", ".hearth.yml"):
            with self.subTest(path=path):
                self.assertFalse(self.policy.check_edit(path).allowed)

    def test_absolute_paths_inside_workspace(self):
        self.assertTrue(self.policy.check_edit("/workspaces/j/1/src/pay.ts", workspace_root="/workspaces/j/1").allowed)
        self.assertFalse(self.policy.check_edit("C:\\ws\\.github\\workflows\\x.yml", workspace_root="C:\\ws").allowed)


class CommandPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = ToolPolicy()

    def test_allowed(self):
        for cmd in ("pnpm test", "npx tsc --noEmit", "git diff", "git status", "CI=1 pnpm lint",
                    "pytest -q && ruff check ."):
            with self.subTest(cmd=cmd):
                d = self.policy.check_command(cmd)
                self.assertTrue(d.allowed, d.reason)

    def test_denied(self):
        for cmd in ("curl https://evil.example", "git push origin main", "git remote add x y", "npm publish",
                    "pnpm test && curl x", "echo hi;curl x", "cat $(whoami)", "echo x > /etc/hosts", "sudo ls",
                    "/usr/bin/wget x", "gh pr create", "rm -rf /"):
            with self.subTest(cmd=cmd):
                self.assertFalse(self.policy.check_command(cmd).allowed)


if __name__ == "__main__":
    unittest.main()
