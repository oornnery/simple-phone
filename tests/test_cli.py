import contextlib
import io
import json
import os
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

    def test_without_an_account_the_target_is_enough(self):
        opt = cli.parse_args(["options", "proxy.example.com"])
        settings, _ = cli.settings_from(opt)
        self.assertEqual(
            (settings.server, settings.user), ("proxy.example.com", "simple-phone")
        )
        self.assertIs(settings.register, False)
        self.assertEqual(cli.target_uri("proxy.example.com"), "sip:proxy.example.com")
        self.assertEqual(cli.target_uri("1002"), "1002")
        opt = cli.parse_args(["message", "sip:1002@pbx.example.com:5080", "hello"])
        settings, _ = cli.settings_from(opt)
        self.assertEqual(settings.server, "pbx.example.com")
        self.assertIs(settings.text, False)  # the body is not Settings.text
        answer, _ = cli.settings_from(cli.parse_args(["answer"]))
        self.assertEqual((answer.server, answer.user), ("127.0.0.1", "simple-phone"))
        opt = cli.parse_args(["call", "1002", "--server", "pbx", "--user", "1001"])
        self.assertIs(cli.settings_from(opt)[0].register, True)  # an account registers
        with self.assertRaises(ValueError):  # an extension says nothing of the server
            cli.settings_from(cli.parse_args(["options", "1002"]))

    def test_a_typo_names_the_typo(self):
        for argv, expected in (
            (["--verion"], "unrecognized arguments: --verion"),
            (["optins"], "maybe you meant 'options'"),
            ([], "choose a command"),
        ):
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit):
                cli.parse_args(argv)
            self.assertIn(expected, errors.getvalue())

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

    def test_call_and_answer_without_an_account(self):
        answer = subprocess.Popen(
            [sys.executable, "-m", "simple_phone.cli", "answer", "--local-port", "5099",
             "--rtp-port", "42600", "--media", "echo", "--duration", "3", "--timeout", "15"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )  # fmt: skip
        self.addCleanup(answer.wait)
        self.addCleanup(answer.kill)
        time.sleep(1.5)  # its endpoint starts
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["call", "127.0.0.1:5099", "--duration", "1"]), 0)

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
                args = [*command, "127.0.0.1:5094"]  # like curl: the target alone
                if command == ["message"]:
                    args.append("hello")
                status = cli.main([*args, "--header", "X-Test: 1"])
            self.assertEqual(status, 0, output.getvalue())
            self.assertIn("SIP/2.0 200 OK", output.getvalue())
            self.assertIn("CSeq:", output.getvalue())

    def test_a_startup_error_is_an_error_line_not_a_traceback(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = cli.main(
                ["call", "1", *LOCAL, "--user", "1001", "--codec", "nope"]
            )
        self.assertEqual(status, 1)
        self.assertIn("error: Codec unavailable", output.getvalue())


NULL_SOUND_CARD = """
pcm.!default { type null hint { show on description "Null (default)" } }
pcm.nulldev { type null hint { show on description "Null device" } }
"""


class SoundCardTest(unittest.TestCase):
    """mic, speaker and device ids, on ALSA null devices (no hardware)."""

    def run_cli(self, *args, wait=True):
        command = [sys.executable, "-m", "simple_phone.cli", *args]
        output = subprocess.PIPE if wait else subprocess.DEVNULL
        process = subprocess.Popen(
            command, env=self.env, text=True, stdout=output, stderr=subprocess.STDOUT
        )
        if not wait:
            self.addCleanup(process.wait)
            self.addCleanup(process.kill)
            return process
        output, _ = process.communicate(timeout=60)
        return process.returncode, output

    def setUp(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "alsa.conf").write_text(NULL_SOUND_CARD)
        self.env = {**os.environ, "ALSA_CONFIG_PATH": str(folder / "alsa.conf")}

    def test_devices_have_numeric_ids(self):
        status, output = self.run_cli("devices")
        self.assertEqual(status, 0, output)
        self.assertRegex(output, r"1 +│ nulldev")

    def test_mic_and_speaker_on_a_chosen_device(self):
        self.run_cli("answer", *LOCAL, "--user", "1002", "--local-port", "5095",
                     "--rtp-port", "41800", "--media", "echo", "--speaker",
                     "--duration", "3", "--timeout", "20", wait=False)  # fmt: skip
        time.sleep(1.5)  # its endpoint starts
        status, output = self.run_cli(
            "call", "sip:1002@127.0.0.1:5095", *LOCAL, "--user", "1001",
            "--media", "mic", "--speaker", "--set", "capture_device=1",
            "--set", "playback_device=1", "--duration", "2",
        )  # fmt: skip
        self.assertEqual(status, 0, output)

    def test_an_unknown_device_is_an_error(self):
        status, output = self.run_cli(
            "call", "1", *LOCAL, "--user", "1001", "--media", "mic",
            "--set", "capture_device=99",
        )  # fmt: skip
        self.assertEqual(status, 1)
        self.assertIn("capture_device=99: no such audio device", output)
        self.assertNotIn("Traceback", output)


if __name__ == "__main__":
    unittest.main()
