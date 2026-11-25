"""simple-phone: a SIP phone for testing, from the terminal.

    simple-phone call 1002 --server pbx.example.com --user 1001
    simple-phone call 1002@192.0.2.10              # no account: dial a host
    simple-phone answer --profile account.json --media echo
    simple-phone options pbx.example.com
    simple-phone message 1002@pbx.example.com hello
    simple-phone doctor --profile account.json
    simple-phone devices

The password comes from $SIP_PASSWORD (or the profile's password_env), or
is asked on the terminal. Any Settings field not covered by a flag can be
set with --set name=value or in a JSON profile.

Exit status: call/answer 0 answered with audio, 1 anything else;
options/message 0 on any response, 1 on none; 130 interrupted.
"""

from __future__ import annotations

# Python 3.15+ (PEP 810): --help and --version skip PJSIP and asyncio.
__lazy_modules__ = [
    "asyncio",
    "getpass",
    "json",
    "rich.table",
    "simple_phone.call",
    "simple_phone.phone",
]

import argparse
import asyncio
import contextlib
import dataclasses
import getpass
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .call import Call
from .core.config import MEDIA_MODES
from .core.profiles import load_profile
from .models import PhoneError, Settings, Timeouts, WaitTimeout
from .phone import AsyncPhone
from .version import PJSIP_VERSION, __version__

console = Console(highlight=False)
SETTINGS = {f.name for f in dataclasses.fields(Settings)}
STATE_STYLE = {"CONFIRMED": "green", "DISCONNECTED": "red", "EARLY": "yellow"}
# devices, and doctor without a server: the endpoint alone, no network
LOCAL = Settings(server="127.0.0.1", user="local", register=False, log_level=1)

# -- arguments --


def parse_args(argv=None):
    # Options not given stay None, so they never override the profile.
    common = argparse.ArgumentParser(add_help=False)
    group = common.add_argument_group("account")
    add = group.add_argument
    add("--profile", help="JSON profile: Settings fields and password_env")
    add("--server", help="registrar or trunk host")
    add("--port", type=int, help="registrar port (default 5060)")
    add("--user", help="SIP user or extension")
    add("--auth-user", help="Digest login, if not --user")
    add("--domain", help="identity domain (default: --server)")
    add("--proxy", help="outbound proxy, e.g. 'sip:host:5060;lr'")
    add(
        "--no-register",
        dest="register",
        action="store_const",
        const=False,
        help="no REGISTER",
    )
    add("--transport", choices=["udp", "tcp", "tls"])
    add("--local-port", type=int, help="local SIP port (default 5070)")
    add("--rtp-port", type=int, help="first of 100 RTP ports (default 40000)")
    add("--password-env", help="variable with the password (default SIP_PASSWORD)")
    add(
        "--set",
        dest="extra",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="any other Settings field, e.g. --set srtp=mandatory",
    )

    group = common.add_argument_group("media")
    add = group.add_argument
    add("--media", choices=MEDIA_MODES, help="what to send (default silent)")
    add("--wav", help="8 kHz mono WAV to send with --media wav")
    add("--speaker", action="store_const", const=True, help="play received audio")
    add("--record", metavar="WAV", help="record received audio")
    add("--codec", help="auto, or names such as PCMA,PCMU,opus")
    add(
        "--no-amd",
        dest="amd",
        action="store_const",
        const=False,
        help="skip answer detection",
    )

    group = common.add_argument_group("output")
    add = group.add_argument
    add(
        "--timeout",
        type=float,
        default=30.0,
        help="seconds to register, to be answered, to wait for a call (default 30)",
    )
    add("--trace", action="store_true", help="one line per SIP message")
    add("--stats", action="store_true", help="RTP counters every second")
    add("-v", "--verbose", action="store_true", help="PJSIP log")

    parser = argparse.ArgumentParser(
        prog="simple-phone",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        suggest_on_error=True,  # 'optins' -> did you mean 'options'?
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"simple-phone {__version__} (PJSIP {PJSIP_VERSION})",
    )
    # Not required=True: then a typo such as --verion would be reported as a
    # missing command instead of an unknown option.
    commands = parser.add_subparsers(dest="command", metavar="command")
    call = commands.add_parser("call", parents=[common], help="dial and report")
    options = commands.add_parser(
        "options", parents=[common], help="send OPTIONS, print the response"
    )
    message = commands.add_parser(
        "message", parents=[common], help="send a MESSAGE, print the response"
    )
    for sub in (call, options, message):
        sub.add_argument("dest", help="number or sip: URI")
        sub.add_argument(
            "--header",
            action="append",
            default=[],
            metavar="'Name: value'",
            help="extra header, repeatable",
        )
    # not "text": that is a Settings field (real-time text)
    message.add_argument("body", metavar="text", help="the message body (text/plain)")
    answer = commands.add_parser(
        "answer", parents=[common], help="wait for one call and answer it"
    )
    for sub in (call, answer):
        sub.add_argument(
            "--duration",
            type=float,
            default=15.0,
            help="seconds connected (default 15)",
        )
        sub.add_argument("--dtmf", default="", help="digits to send once answered")
        sub.add_argument(
            "--dtmf-delay",
            type=float,
            default=2.0,
            help="seconds after the answer (default 2)",
        )
        sub.add_argument("--json", metavar="FILE", help="save the full report")
    commands.add_parser(
        "doctor",
        parents=[common],
        help="versions, codecs, devices, NAT, REGISTER, OPTIONS",
    )
    commands.add_parser("devices", help="audio devices")

    opt = parser.parse_args(argv)
    if opt.command is None:
        parser.error("choose a command: " + ", ".join(commands.choices))
    if any(":" not in h for h in getattr(opt, "header", [])):
        parser.error("--header must look like 'Name: value'")
    return opt


def headers_from(opt):
    pairs = (h.split(":", 1) for h in opt.header)
    return {name.strip(): value.strip() for name, value in pairs}


def settings_from(opt):
    """Profile, then flags, then --set; returns (Settings, password_env)."""
    values = load_profile(opt.profile) if opt.profile else {}
    password_env = opt.password_env or values.pop("password_env", "SIP_PASSWORD")
    values.pop("password_env", None)
    given = {k: v for k, v in vars(opt).items() if v is not None}
    values |= {k: v for k, v in given.items() if k in SETTINGS}
    for pair in opt.extra:
        name, sep, text = pair.partition("=")
        if not sep or name not in SETTINGS:
            raise ValueError(f"--set {pair}: not a Settings field")
        try:
            values[name] = json.loads(text)  # numbers, true/false, lists
        except json.JSONDecodeError:
            values[name] = text
    # Like curl, without an account: options/message always, call/answer
    # when neither --server nor --profile is given. Flags and profile win.
    if opt.command in ("options", "message") or not (opt.server or opt.profile):
        values = anonymous_defaults(getattr(opt, "dest", None)) | values
    values.setdefault("log_level", 4 if opt.verbose else 1)
    if not values.get("server") or not values.get("user"):
        raise ValueError("--server and --user (or --profile) are required")
    return Settings(**values), password_env


def anonymous_defaults(dest=None):
    """Settings for a phone without an account: the From user is
    simple-phone, nothing registers, and the server is the target's host
    (for answer, which has no target: this machine)."""
    defaults = {"user": "simple-phone", "register": False}
    if dest is None:
        return defaults | {"server": "127.0.0.1"}
    target = dest.split(":", 1)[1] if dest.startswith(("sip:", "sips:")) else dest
    host = target.rpartition("@")[2].split(";")[0].rsplit(":", 1)[0]
    if "." in host or host == "localhost":
        defaults["server"] = host
    return defaults


def target_uri(dest):
    """'pbx.example.com' or 'host:5060' is a host, not an extension."""
    plain = not dest.startswith(("sip:", "sips:")) and "@" not in dest
    return f"sip:{dest}" if plain and ("." in dest or ":" in dest) else dest


def password_for(settings, variable):
    password = os.environ.get(variable)
    needed = settings.register or settings.auth_user
    if password is None and needed and sys.stdin.isatty():
        password = getpass.getpass("SIP password: ")
    return password


# -- live output --


def sip_line(event):
    msg = event.message
    arrow, style = ("→", "cyan") if msg.direction == "TX" else ("←", "magenta")
    return f"[{style}]{arrow} {msg.peer:<21} {msg.label}[/]"


def show(phone, opt):
    lines: dict[type, Callable[[Any], str]] = {
        AsyncPhone.Registration: lambda e: (
            f"[{'green' if e.code < 300 else 'red'}]REGISTER {e.code} {e.reason}[/]"
        ),
        Call.StateChanged: lambda e: (
            f"[{STATE_STYLE.get(e.state, 'blue')}]{e.state}[/] {e.code} {e.reason}"
        ),
        Call.Dtmf: lambda e: f"[bold]DTMF ←[/] {e.digit}",
        Call.Amd: lambda e: f"[bold]AMD[/] {e.amd.result} [dim]({e.amd.reason})[/]",
        AsyncPhone.Warning: lambda e: f"[yellow]warning:[/] {e.text}",
    }
    if opt.verbose:
        lines[AsyncPhone.Log] = lambda e: f"[dim]{e.text}[/]"
    if opt.trace:
        lines |= {Call.Sip: sip_line, AsyncPhone.Sip: sip_line}
    if opt.stats:
        lines[Call.Stats] = lambda e: (
            f"[dim]RTP tx={e.stats.tx_packets} rx={e.stats.rx_packets} "
            f"lost={e.stats.rx_lost} jitter={e.stats.jitter_ms} ms[/]"
        )
    for kind, line in lines.items():
        phone.on(kind)(lambda event, line=line: console.print(line(event)))


# -- commands --


async def one_call(opt, settings, password):
    """Dial or answer, keep the call for --duration, hang up. Returns the
    call (None if it never started) and the error, if any."""
    timeouts = Timeouts(register=opt.timeout, setup=opt.timeout)
    phone = AsyncPhone(settings, password=password, timeouts=timeouts)
    show(phone, opt)
    call, error = None, None
    async with phone:
        try:
            if opt.command == "answer":
                console.print(f"Waiting for a call to [bold]{phone.uri}[/] …")
                call = await phone.incoming(timeout=timeouts.setup)
                console.print(f"[bold]Incoming[/] {call.remote_uri}")
                await call.answer()
            else:
                phone.on(AsyncPhone.Incoming)(lambda e: e.call.reject(486))
                target = target_uri(opt.dest)
                call = await phone.dial(target, headers=headers_from(opt))
                console.print(f"[bold]Calling[/] {call.destination}")
            await call.answered(timeout=timeouts.setup)
            await talk(call, opt)
        except asyncio.CancelledError:  # Ctrl+C: hang up and still report
            if task := asyncio.current_task():
                task.uncancel()
            error = KeyboardInterrupt()
        except PhoneError as exc:
            error = exc
        if call is not None:
            with contextlib.suppress(PhoneError):
                await call.hangup()
    return call, error


async def talk(call, opt):
    """Send --dtmf after --dtmf-delay; return after --duration or hangup."""
    loop = asyncio.get_running_loop()
    end = loop.time() + opt.duration
    if opt.dtmf and opt.dtmf_delay < opt.duration:
        if await ended_within(call, opt.dtmf_delay):
            return
        try:
            await call.dtmf(opt.dtmf)
            console.print(f"[bold]DTMF →[/] {opt.dtmf}")
        except PhoneError as exc:  # e.g. no telephone-event: the call goes on
            console.print(f"[yellow]DTMF not sent:[/] {exc}")
    await ended_within(call, end - loop.time())


async def request(opt, settings, password):
    """options / message: send one request outside a call and print the
    response, like curl. Exit 0 on any response, 1 on none."""
    phone = AsyncPhone(
        settings, password=password, timeouts=Timeouts(register=opt.timeout)
    )
    show(phone, opt)
    received = []
    phone.on(AsyncPhone.Sip)(lambda e: received.append(e.message))
    method, extra = opt.command.upper(), {"headers": headers_from(opt)}
    target = target_uri(opt.dest)
    async with phone:
        if method == "OPTIONS":
            response = await phone.options(target, timeout=opt.timeout, **extra)
        else:
            response = await phone.message(
                target, opt.body, timeout=opt.timeout, **extra
            )
        await asyncio.sleep(0)  # the SIP log of the response
    full = next(
        (
            m
            for m in reversed(received)
            if m.direction == "RX"
            and m.cseq_method == method
            and m.code == response.code
        ),
        None,
    )
    if full is None:
        console.print(status_style(response.code, f"{response.code} {response.reason}"))
    else:
        print_message(full)
    if response.code in (401, 407):
        console.print(
            "[dim]PJSUA sends it without credentials, so a PBX that challenges it answers 401.[/]"
        )
    return 0  # like curl: an answer, whatever its code, is a success


def status_style(code, text):
    style = "green" if code < 300 else "yellow" if code < 400 else "red"
    return f"[bold {style}]{escape(text)}[/]"


def print_message(message):
    """A SIP message like an HTTP client prints a response."""
    head, _, body = message.raw.replace("\r\n", "\n").partition("\n\n")
    first, *lines = head.split("\n")
    console.print(status_style(message.code or 0, first), soft_wrap=True)
    for line in lines:
        name, sep, value = line.partition(":")
        console.print(f"[cyan]{escape(name)}[/]{sep}{escape(value)}", soft_wrap=True)
    if body.strip():
        console.print()
        console.print(escape(body.rstrip()), soft_wrap=True)
    if message.truncated:
        console.print("[dim](truncated)[/]")


async def ended_within(call, seconds):
    try:
        await call.ended(timeout=max(seconds, 0.01))
        return True
    except WaitTimeout:
        return False


def summary(call, error):
    """Print the report; returns the exit status."""
    report = call.report if call is not None else None
    streams = report.raw.get("streams", []) if report else []
    result, status, style = outcome(report, streams, error)
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("result", f"[bold {style}]{result}[/]")
    if error is not None and not isinstance(error, KeyboardInterrupt):
        table.add_row("error", f"[red]{error}[/]")
    if report is not None:
        report_rows(table, call, report)
    console.print()
    console.print(table)
    if streams:
        console.print(streams_table(streams))
        console.print(
            "[dim]MOS is estimated from loss, jitter and RTT. TX loss and "
            "jitter need RTCP from the peer; '-' means no sample.[/]"
        )
    return status


def outcome(report, streams, error):
    """(result, exit status, colour) of the call."""
    if isinstance(error, KeyboardInterrupt):
        return "INTERRUPTED", 130, "yellow"
    if report is None or not report.answered:
        return "FAILED", 1, "red"
    if not streams:
        return "NO MEDIA", 1, "red"  # no codec in common
    return "ANSWERED", 0, "green"


def report_rows(table, call, report):
    table.add_row("SIP", f"{report.code} {report.reason}")
    table.add_row("remote", str(report.raw.get("remote_uri")))
    table.add_row("call-id", str(report.raw.get("call_id")))
    table.add_row("answer time", f"{report.answer_time_seconds} s")
    table.add_row("connected", f"{report.connected_seconds} s")
    if report.amd:
        table.add_row("AMD", f"{report.amd.result} ({report.amd.reason})")
    if call.dtmf_received:
        table.add_row("DTMF ←", call.dtmf_received)


def streams_table(streams):
    table = Table(
        "stream",
        "codec",
        "remote RTP",
        "dir",
        "packets",
        "lost",
        "jitter ms",
        "RTT ms",
        "MOS",
    )
    for s in streams:
        for name in ("tx", "rx"):
            d = s[name]
            jitter = (d.get("jitter_ms") or {}).get("mean")
            table.add_row(
                f"{s['media_index']}.{s['generation']}",
                f"{s['codec']}/{s['clock_rate_hz']}",
                s["remote_rtp"],
                name.upper(),
                str(d["packets"]),
                str(d["lost_packets"]),
                dash(jitter),
                dash((s.get("rtt_ms") or {}).get("mean")),
                dash(s.get("mos_estimated")),
            )
    return table


def dash(value):
    return "-" if value is None else f"{value:g}"


def save_json(path, call, error):
    data = dict(call.report.raw) if call is not None and call.report else {}
    data["error"] = str(error) if error else None
    Path(path).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    console.print(f"[dim]report saved to {path}[/]")


async def devices():
    async with AsyncPhone(LOCAL) as phone:
        found = await phone.devices()
    table = Table("id", "name", "in", "out")
    for d in found:
        table.add_row(str(d["id"]), d["name"], str(d["inputs"]), str(d["outputs"]))
    console.print(table if found else "[yellow]no audio devices[/]")
    return 0


async def doctor(opt, settings, password, network=True):
    python = sys.version.split()[0]
    console.print(
        f"simple-phone {__version__} · PJSIP {PJSIP_VERSION} · Python {python}"
    )
    table = Table("check", "result", show_header=False, box=None, padding=(0, 2))
    healthy = True

    def row(name, ok, text):
        nonlocal healthy
        healthy = healthy and ok
        mark = "[green]✓[/]" if ok else "[red]✗[/]"
        table.add_row(f"{mark} {name}", text)

    async with AsyncPhone(settings, password=password) as phone:
        codecs = [c["id"] for c in await phone.codecs() if c["priority"]]
        row("codecs", bool(codecs), ", ".join(codecs) or "none")
        row("audio devices", True, str(len(await phone.devices())))
        if not network:
            console.print(table)
            return 0
        if settings.stun_servers:
            await probe(row, "NAT", nat_check(phone, opt.timeout))
        if settings.register:
            await probe(row, "REGISTER", register_check(phone, opt.timeout))
        target = f"sip:{settings.server}:{settings.port}"
        await probe(row, f"OPTIONS {target}", options_check(phone, target, opt.timeout))
    console.print(table)
    return 0 if healthy else 1


async def probe(row, name, check):
    """One doctor row from `check`, which returns (ok, text)."""
    try:
        ok, text = await check
    except PhoneError as exc:
        ok, text = False, str(exc)
    row(name, ok, text)


async def nat_check(phone, timeout):
    nat = await phone.nat_type(timeout)
    return nat.ok, nat.type if nat.ok else nat.reason


async def register_check(phone, timeout):
    await phone.wait_registered(timeout)
    return True, str(phone.reg)


async def options_check(phone, target, timeout):
    response = await phone.options(target, timeout=timeout)
    # 401/407 is an answer too: PJSUA sends OPTIONS without credentials
    answered = response.code < 300 or response.code in (401, 407)
    return answered, f"{response.code} {response.reason}"


def main(argv=None):
    opt = parse_args(argv)
    try:
        if opt.command == "devices":
            return asyncio.run(devices())
        if opt.command == "doctor" and not (opt.server or opt.profile):
            return asyncio.run(doctor(opt, LOCAL, None, network=False))
        settings, password_env = settings_from(opt)
        password = password_for(settings, password_env)
        if opt.command == "doctor":
            return asyncio.run(doctor(opt, settings, password))
        if opt.command in ("options", "message"):
            return asyncio.run(request(opt, settings, password))
        call, error = asyncio.run(one_call(opt, settings, password))
        if opt.json:
            save_json(opt.json, call, error)
        return summary(call, error)
    except KeyboardInterrupt:
        return 130
    except (PhoneError, ValueError, OSError) as exc:
        console.print(f"[red]error:[/] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
