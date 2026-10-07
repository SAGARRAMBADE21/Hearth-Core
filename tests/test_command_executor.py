import os
import sys
import unittest
from unittest import mock

from utils.commands import CommandSpecError, redact, redact_argv, run, safe_arg


class SafeArgTests(unittest.TestCase):
    def test_rejects_options_and_nul(self):
        self.assertEqual(safe_arg("main"), "main")
        with self.assertRaises(CommandSpecError):
            safe_arg("--upload-pack=evil")
        with self.assertRaises(CommandSpecError):
            safe_arg("a\x00b")
        self.assertEqual(safe_arg("-x", allow_option=True), "-x")


class RedactionTests(unittest.TestCase):
    def test_tokens_and_headers(self):
        self.assertNotIn("ghp_", redact("token ghp_abcdefghijklmnopqrstuvwxyz0123"))
        self.assertNotIn("abc.def", redact("Authorization: Bearer abc.def"))
        self.assertEqual(redact_argv(["gh", "--token", "s3cret", "x"]), ["gh", "--token", "***", "x"])
        self.assertEqual(redact_argv(["x", "--api-key=s3cret"]), ["x", "--api-key=***"])


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def test_ok_and_separate_stderr(self):
        r = await run([sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
                      separate_stderr=True)
        self.assertTrue(r.ok)
        self.assertEqual(r.stdout.strip(), "out")
        self.assertEqual(r.stderr.strip(), "err")

    async def test_input_reaches_stdin(self):
        r = await run([sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"], input="hello")
        self.assertEqual(r.output.strip(), "HELLO")

    async def test_unset_env_removes_variables_from_the_child(self):
        with mock.patch.dict(os.environ, {"GH_TOKEN": "from-env", "KEEP_ME": "yes"}):
            r = await run([sys.executable, "-c", "import os; print(os.environ.get('GH_TOKEN'), os.environ.get('KEEP_ME'))"],
                          unset_env=("GH_TOKEN",))
        self.assertEqual(r.output.strip(), "None yes")

    async def test_missing_binary(self):
        r = await run(["definitely-not-a-real-binary-xyz"])
        self.assertTrue(r.binary_missing)
        self.assertEqual(r.returncode, -1)
        self.assertFalse(r.ok)

    async def test_timeout(self):
        r = await run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.5)
        self.assertTrue(r.timed_out)
        self.assertFalse(r.ok)


if __name__ == "__main__":
    unittest.main()
