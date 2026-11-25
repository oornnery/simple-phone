# simple-phone

*[Português](README.pt-BR.md)*

A SIP phone for testing calls, as a command and as a Python library. PJSIP 2.17 ships compiled inside the wheel, so there is nothing to build.

## Install

Linux x86_64 and Python 3.14. The only system library it needs is ALSA, which every Linux desktop has.

```bash
pip install simple-phone                  # or: uv add simple-phone
sudo apt install libasound2t64            # only if ALSA is missing (libasound2 before Ubuntu 24.04)
pip install 'simple-phone[stt,tts]'       # optional: Whisper and Piper for say() and listen()
```

Or run it without installing, with [uv](https://docs.astral.sh/uv/). `--python 3.14` is needed while uv defaults to a newer Python:

```bash
uvx --python 3.14 simple-phone doctor --server pbx.example.com --user 1001   # REGISTER and OPTIONS
uvx --python 3.14 simple-phone call 1002 --server pbx.example.com --user 1001
```

Check the install, and then your account:

```bash
simple-phone doctor                                       # this machine: codecs, audio devices
simple-phone doctor --server pbx.example.com --user 1001  # also REGISTER and OPTIONS
```

## Use it from the terminal

The password comes from `$SIP_PASSWORD`, or the command asks for it.

```bash
export SIP_PASSWORD=...
simple-phone call 1002 --server pbx.example.com --user 1001 --media echo   # dial, report, exit
simple-phone answer --server pbx.example.com --user 1002 --media echo      # wait for one call
simple-phone devices                                                       # audio devices
```

`call` prints the SIP status, the time to answer, and loss, jitter, RTT and MOS for each RTP stream. `call` and `answer` exit with 0 when the call was answered with audio, so they work in scripts:

```bash
simple-phone call 1002 --profile account.json --json report.json && echo "route ok"
```

All options, the report and the exit codes: [docs/cli.md](docs/cli.md).

## Use it from Python

```python
import asyncio
from simple_phone import AsyncPhone


async def main():
    async with AsyncPhone(server="pbx", user="1001", password="...") as phone:
        async with phone.call("1002") as call:
            await call.dtmf("1234#")
        print(call.trace.flow())  # ['INVITE', '100', '180', '200', 'ACK', 'BYE', '200']
        print(call.report.mos)


asyncio.run(main())
```

`Phone` is the same API without `await`:

```python
from simple_phone import Phone

with Phone(server="pbx.example.com", user="1001", password="...") as phone:
    with phone.call("1002") as call:
        call.dtmf("1234#")
```

Answer calls and react to events:

```python
from simple_phone import AsyncPhone, Call

async with AsyncPhone(server="pbx.example.com", user="1002", password="...") as phone:

    @phone.on(AsyncPhone.Incoming)
    async def incoming(event):
        await event.call.answer(media="echo")

    @phone.on(Call.Dtmf, digit="#")
    async def done(event):
        await event.call.hangup()

    await phone.serve()
```

Check a route in a test:

```python
async with phone.call("1002") as call:
    event = await call.wait_for(Call.Stats, lambda e: e.stats.rx_packets >= 100)
    assert event.stats.rx_loss_percent < 1
assert call.report.mos >= 3.8
```

The rest of the API: [docs/api.md](docs/api.md). Examples that run on one machine, without a PBX: [examples/api/](examples/api/README.md).

## What it does

- Registers an extension, or uses a trunk without registration.
- Makes and answers calls over UDP or TCP, with G.711 by default.
- Sends silence, an echo of what it hears, a WAV file or the microphone. Records what it receives.
- Sends and receives DTMF by RFC 4733, SIP INFO or in-band tones.
- Reports per call every SIP message, loss, jitter, RTT and an estimated MOS.
- Tells who answered an outgoing call: a person, an IVR, voicemail or a network announcement.
- Holds, transfers and conferences calls.
- Subscribes to presence, BLF and voicemail (MWI). Sends OPTIONS, MESSAGE and real-time text.
- Runs up to 64 calls in one process, paced by `Limits`.
- Speaks and transcribes with Piper and Whisper.

## Docs

- [docs/cli.md](docs/cli.md): the command, its options and its report.
- [docs/api.md](docs/api.md): the Python API.
- [docs/development.md](docs/development.md): building, tests, CI and releases.
- [docs/architecture.md](docs/architecture.md): how the code is organized.
- [CHANGELOG.md](CHANGELOG.md): what changed in each version.

## License

GPL-2.0-or-later. PJSIP is GPL and is linked into this package, so the package carries the same license. Teluu sells a commercial PJSIP license for closed-source use.
