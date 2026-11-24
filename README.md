# simple-phone

*[Português](README.pt-BR.md)*

A SIP phone for testing calls, as a command and as a Python library. PJSIP 2.17 ships compiled inside the wheel, so there is nothing to build.

```bash
pip install simple-phone
```

Make a call from the terminal and get a report of the SIP exchange and the RTP quality:

```bash
simple-phone call 1002 --server pbx.example.com --user 1001 --media echo
```

Or from Python:

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

Linux x86_64, Python 3.14. The only system library it needs is ALSA (`libasound2`), which every Linux desktop has.

## What it does

- Registers an extension, or uses a trunk without registration.
- Makes and answers calls over UDP or TCP, with G.711 by default.
- Sends silence, an echo of what it hears, a WAV file or the microphone. Records what it receives.
- Sends and receives DTMF by RFC 4733, SIP INFO or in-band tones.
- Reports per call: every SIP message, loss, jitter, RTT and an estimated MOS.
- Tells who answered an outgoing call: a person, an IVR, voicemail or a network announcement.
- Holds, transfers and conferences calls.
- Subscribes to presence, BLF and voicemail (MWI). Sends OPTIONS, MESSAGE and real-time text.
- Runs up to 64 calls in one process, paced by `Limits`.
- Speaks and transcribes with Piper and Whisper: `pip install 'simple-phone[stt,tts]'`.

## Command line

```bash
simple-phone call 1002 --server pbx.example.com --user 1001    # dial, report, exit
simple-phone answer --server pbx.example.com --user 1002       # wait for one call
simple-phone doctor --server pbx.example.com --user 1001       # check the setup
simple-phone devices                                           # audio devices
```

The password comes from `$SIP_PASSWORD`, or the command asks for it. `call` and `answer` exit with 0 when the call was answered with audio, so they work in scripts:

```bash
simple-phone call 1002 --profile account.json --json report.json && echo "route ok"
```

All options, the report and the exit codes: [docs/cli.md](docs/cli.md).

## Python

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

## More

- [docs/cli.md](docs/cli.md): the command, its options and its report.
- [docs/api.md](docs/api.md): the Python API.
- [docs/development.md](docs/development.md): building, tests, CI and releases.
- [docs/architecture.md](docs/architecture.md): how the code is organized.

## License

GPL-2.0-or-later. PJSIP is GPL and is linked into this package, so the package carries the same license. Teluu sells a commercial PJSIP license for closed-source use.
