import contextlib
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from simple_phone import Settings, cli

LOCAL = ["--server", "127.0.0.1", "--no-register"]


class ArgumentsTest(unittest.TestCase):
    def test_profile_then_flags_then_set(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(
                {
                    "server": "pbx",
                    "user": "1001",
                    "media": "echo",
                    "password_env": "PW",
                },
                f,
            )
        opt = cli.parse_args(
            ["call", "1002", "--profile", f.name, "--user", "1009",
             "--set", "srtp=optional", "--set", "ice=true"]
        )  # fmt: skip
        settings, password_env = cli.settings_from(opt)
        self.assertEqual((settings.server, settings.user), ("pbx", "1009"))
        self.assertEqual((settings.media, settings.srtp), ("echo", "optional"))
        self.assertIs(settings.ice, True)
        self.assertEqual(password_env, "PW")
        Path(f.name).unlink()

    def test_targets_become_uris(self):
        settings = Settings(server="pbx", user="1001")
        self.assertEqual(settings.uri("1002"), "sip:1002@pbx")
        self.assertEqual(settings.uri("1002@host:5094"), "sip:1002@host:5094")
        self.assertEqual(settings.uri("sips:1002@host"), "sips:1002@host")

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            cli.settings_from(cli.parse_args(["call", "1", "--server", "x"]))
        with self.assertRaises(ValueError):
            opt = cli.parse_args(["answer", "--server", "x", "--user", "y",
                                  "--set", "nope=1"])  # fmt: skip
            cli.settings_from(opt)
        with self.assertRaises(SystemExit):
            cli.parse_args(["call", "1", "--header", "no colon"])


class CommandsTest(unittest.TestCase):
    def test_doctor_without_a_server(self):
        self.assertEqual(cli.main(["doctor"]), 0)

    def test_call_and_answer(self):
        answer = subprocess.Popen(
            [sys.executable, "-m", "simple_phone.cli", "answer", *LOCAL,
             "--user", "1002", "--local-port", "5093", "--rtp-port", "41400",
             "--media", "echo", "--duration", "5", "--timeout", "15"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )  # fmt: skip
        self.addCleanup(answer.kill)
        time.sleep(1.5)  # its endpoint starts
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "call.json"
            status = cli.main(
                ["call", "sip:1002@127.0.0.1:5093", *LOCAL, "--user", "1001",
                 "--duration", "2", "--dtmf", "7", "--dtmf-delay", "0.5",
                 "--json", str(report)]
            )  # fmt: skip
            self.assertEqual(status, 0)
            self.assertTrue(json.loads(report.read_text())["answered"])
        output, _ = answer.communicate(timeout=20)
        self.assertEqual(answer.returncode, 0, output)
        self.assertIn("DTMF ← 7", output)

    def test_options_and_message_print_the_response(self):
        far = subprocess.Popen(
            [sys.executable, "-m", "simple_phone.cli", "answer", *LOCAL,
             "--user", "1002", "--local-port", "5094", "--rtp-port", "41600",
             "--timeout", "15"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )  # fmt: skip
        self.addCleanup(far.wait)
        self.addCleanup(far.kill)
        time.sleep(1.5)  # its endpoint starts
        for command in (["options"], ["message"]):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                args = [*command, "sip:1002@127.0.0.1:5094", *LOCAL, "--user", "1001"]
                if command == ["message"]:
                    args.append("hello")
                status = cli.main([*args, "--header", "X-Test: 1"])
            self.assertEqual(status, 0, output.getvalue())
            self.assertIn("SIP/2.0 200 OK", output.getvalue())
            self.assertIn("CSeq:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
