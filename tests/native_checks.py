"""Local PJSUA2 integration tests. Requires permission to open loopback sockets."""

import faulthandler
import multiprocessing as mp
import socket
import tempfile
import time
import unittest
from pathlib import Path

from simple_phone.core.call import Call as Native
from simple_phone.core.config import Config
from simple_phone.core.engine import Engine
from simple_phone.events import CallEvents as Call
from simple_phone.events import PhoneEvents as Phone

faulthandler.enable()


def on_call(engine, ref, action, *args):
    """action(core call, *args) on the engine thread; refs become calls."""

    def run():
        calls = engine.endpoint.calls
        values = [calls[a] if a in calls else a for a in args]
        return action(calls[ref], *values)

    return engine.run(run)


def free_port(kind=socket.SOCK_DGRAM):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Condition timed out")


def receiver(port, transport, ready, stop, events, reject=False):
    config = Config(
        "127.0.0.1",
        "receiver",
        register=False,
        local_port=port,
        transport=transport,
        rtp_port=44000,
        max_calls=4,
        media="echo",
        log_level=0,
        stats_interval=0.1,
    )
    engine = Engine(config)

    def listener(event):
        if isinstance(event, Phone.Incoming):
            call = engine.endpoint.calls[event.ref]  # engine thread
            engine.submit(
                call.reject if reject else call.accept, 486 if reject else 200
            )
        if isinstance(event, Call.Dtmf):
            events.put(event.digit)

    engine.subscribe(listener)
    try:
        with engine:
            ready.put(None)
            stop.wait(40)
    except BaseException as exc:
        ready.put(str(exc))
        raise


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.context = mp.get_context("spawn")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def peer(self, transport="udp", reject=False):
        port = free_port(
            socket.SOCK_STREAM if transport == "tcp" else socket.SOCK_DGRAM
        )
        ready, stop, events = (
            self.context.Queue(),
            self.context.Event(),
            self.context.Queue(),
        )
        process = self.context.Process(
            target=receiver, args=(port, transport, ready, stop, events, reject)
        )
        process.start()

        def close():
            stop.set()
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(5)
            self.assertEqual(process.exitcode, 0)

        self.addCleanup(close)
        error = ready.get(timeout=10)
        self.assertIsNone(error)
        return port, events

    def config(self, **changes):
        return Config(
            "127.0.0.1",
            "caller",
            register=False,
            local_port=0,
            rtp_port=42000,
            log_level=0,
            stats_interval=0.1,
            **changes,
        )

    def test_multiple_calls_audio_recording_and_accounts(self):
        from dataclasses import replace

        port, digits = self.peer()
        ended, states = [], {}

        def track(event):
            if isinstance(event, Call.Ended):
                ended.append(event.report.raw)
            elif isinstance(event, Call.StateChanged):
                states[event.ref] = event.state

        with Engine(self.config(max_calls=2)) as engine:
            engine.subscribe(track)
            other = replace(
                engine.config, account_id="second", user="second", rtp_port=46000
            )
            self.assertEqual(
                engine.run(engine.endpoint.open_account, None, other), "second"
            )
            first, second = "first", "second"  # call refs
            target = f"sip:receiver@127.0.0.1:{port}"
            engine.run(engine.endpoint.start_call, target, (), None, first)
            wait_for(lambda: states.get(first) == "CONFIRMED")
            on_call(engine, first, Native.mute, True)
            on_call(engine, first, Native.gain, 0.5, 0.5)
            on_call(engine, first, Native.mute, False)
            path = str(Path(self.temp.name) / "received.wav")
            on_call(engine, first, Native.set_recording, path)
            on_call(engine, first, Native.send_dtmf, "123#")
            self.assertEqual("".join(digits.get(timeout=5) for _ in range(4)), "123#")
            engine.run(engine.endpoint.start_call, target, (), "second", second)
            wait_for(lambda: states.get(second) == "CONFIRMED")
            on_call(engine, first, Native.hold)
            time.sleep(1)
            on_call(engine, first, Native.unhold)
            time.sleep(0.2)
            on_call(engine, first, Native.conference, second)
            on_call(engine, first, Native.conference, second, False)
            on_call(engine, first, Native.set_recording, None)
            on_call(engine, first, Native.end)
            wait_for(lambda: len(ended) == 1)
            on_call(engine, second, Native.end)
            wait_for(lambda: len(ended) == 2)
            self.assertEqual({r["account_id"] for r in ended}, {"default", "second"})
            self.assertTrue(all(r["answered"] for r in ended))
            self.assertTrue(
                any(s["rx"]["packets"] > 0 for r in ended for s in r["streams"])
            )
            self.assertGreater(Path(path).stat().st_size, 44)

    def test_tcp_call(self):
        import asyncio

        from simple_phone import AsyncPhone, Call

        port, _ = self.peer("tcp")

        async def check():
            async with AsyncPhone(self.config(transport="tcp")) as phone:
                target = f"sip:receiver@127.0.0.1:{port};transport=tcp"
                async with phone.call(target) as call:
                    await call.wait_for(Call.Stats, lambda e: e.stats.rx_packets >= 20)
                self.assertTrue(call.report.answered)

        asyncio.run(check())

    def test_expected_rejection(self):
        import asyncio

        from simple_phone import AsyncPhone, CallFailed

        port, _ = self.peer(reject=True)

        async def check():
            async with AsyncPhone(self.config()) as phone:
                call = await phone.dial(f"sip:receiver@127.0.0.1:{port}")
                with self.assertRaises(CallFailed) as failure:
                    await call.answered(timeout=10)
                self.assertEqual(failure.exception.code, 486)

        asyncio.run(check())

    def test_deferred_register(self):
        import threading

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as registrar:
            registrar.bind(("127.0.0.1", 0))
            registrar.settimeout(0.1)
            stopped = threading.Event()
            received = []

            def serve():
                while not stopped.is_set():
                    try:
                        raw, address = registrar.recvfrom(65535)
                    except socket.timeout:
                        continue
                    text = raw.decode()
                    received.append(text)
                    headers = {}
                    for line in text.split("\r\n")[1:]:
                        key, sep, value = line.partition(":")
                        if sep:
                            headers[key.lower()] = value.strip()
                    response = "SIP/2.0 200 OK\r\n"
                    for key in ("via", "from", "to", "call-id", "cseq", "contact"):
                        if key in headers:
                            response += f"{key}: {headers[key]}\r\n"
                    response += "Expires: 120\r\nContent-Length: 0\r\n\r\n"
                    registrar.sendto(response.encode(), address)

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            try:
                config = self.config()
                config.port = registrar.getsockname()[1]
                config.register = True
                config.auto_register = False
                registered = []
                with Engine(config) as engine:
                    engine.subscribe(
                        lambda e: (
                            registered.append(e.active)
                            if isinstance(e, Phone.Registration)
                            else None
                        )
                    )
                    time.sleep(0.1)
                    self.assertEqual(received, [])
                    engine.run(engine.endpoint.set_registration, True)
                    wait_for(lambda: registered and registered[-1])
                    engine.run(engine.endpoint.set_registration, False)
                    wait_for(lambda: registered and not registered[-1])
            finally:
                stopped.set()
                thread.join(2)

    def test_single_endpoint_guard(self):
        with Engine(self.config()) as first:
            with self.assertRaisesRegex(RuntimeError, "one Engine"):
                Engine(self.config()).start()
            self.assertTrue(
                first.run(first.endpoint.codecs)
            )  # the first one still works


if __name__ == "__main__":
    unittest.main()
