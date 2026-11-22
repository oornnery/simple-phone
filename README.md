# simple-phone

*[Português](README.pt-BR.md)*

A SIP phone for testing calls, built on PJSUA2 (PJSIP 2.17), which ships compiled inside the wheel. It has two parts:

- **`simple-phone` command:** registers an extension (or uses a trunk without registration), makes or answers one call, and prints the SIP and RTP/RTCP report.
- **Python API:** `AsyncPhone`, plus `Phone` with the same methods without `await`. Use it for test automation, voice bots and load runs.

Platform: Linux x86_64, Python 3.14. Transports: UDP and TCP; TLS needs a build with `PJSIP_TLS=1`. Default codecs: G.711 PCMA and PCMU.

## Install

```bash
uv tool install simple-phone    # the command
pip install simple-phone        # the library
pip install 'simple-phone[stt,tts]'   # speech: faster-whisper and Piper
```

The only system dependency is ALSA, which every Linux desktop already has. On a server or a slim container:

```bash
sudo apt install -y libasound2t64    # Debian 13, Ubuntu 24.04+
sudo apt install -y libasound2       # Debian 12, Ubuntu 22.04
sudo pacman -S --needed alsa-lib     # Arch
```

## Command line

```bash
simple-phone call 1002 --server pbx.example.com --user 1001 --media echo --duration 30
simple-phone answer --server pbx.example.com --user 1002 --media echo --timeout 600
simple-phone doctor --server pbx.example.com --user 1001
simple-phone devices
```

`call` registers, dials, stays connected for `--duration` seconds, hangs up and prints a summary. The call also ends early if the far end hangs up or you press Ctrl+C. `answer` waits up to `--timeout` seconds for a call. `doctor` checks versions, codecs, audio devices, NAT (when `stun_servers` is set), REGISTER and an OPTIONS ping. `devices` lists audio devices.

The password comes from `$SIP_PASSWORD` or is asked on the terminal:

```bash
read -rs SIP_PASSWORD && export SIP_PASSWORD   # keeps it out of the shell history
```

Trunk authenticated by IP, with an extra header:

```bash
simple-phone call sip:5511999990001@192.0.2.20 --server 192.0.2.20 --user 551130000000 \
  --no-register --header 'P-Asserted-Identity: <sip:551130000000@192.0.2.10>'
```

End-to-end check: run `answer --media echo` on one host. On another host, send a WAV and record what comes back:

```bash
simple-phone call 1002 --server pbx --user 1001 --media wav --wav reference.wav \
  --record back.wav --dtmf '1234#'
```

`back.wav` holds your own audio, and the receiver prints the DTMF digits it got. One call covers signalling, audio in both directions and DTMF.

### Options

| Option | Meaning | Default |
|---|---|---|
| `--server`, `--user` | Registrar or trunk host, and the extension | required (or `--profile`) |
| `--port` | Registrar port | 5060 |
| `--auth-user` | Digest login, when it differs from `--user` | `--user` |
| `--domain` | Domain of the SIP identity | `--server` |
| `--proxy` | Outbound proxy, e.g. `'sip:10.0.0.1:5060;lr'` (quote the `;`) | none |
| `--no-register` | No REGISTER (IP-authenticated trunk) | registers |
| `--transport` | `udp`, `tcp` or `tls` | udp |
| `--local-port`, `--rtp-port` | Local SIP port; first of 100 RTP ports | 5070, 40000 |
| `--profile FILE` | JSON with any `Settings` fields, plus `password_env` | |
| `--password-env` | Variable that holds the password | `SIP_PASSWORD` |
| `--set NAME=VALUE` | Any other `Settings` field, e.g. `--set srtp=mandatory` | |
| `--media` | `silent`, `echo`, `wav` or `mic` | silent |
| `--wav`, `--record` | WAV to send; WAV to record what is received | |
| `--listen` | Play received audio on this machine | off |
| `--codec` | `auto`, or names such as `PCMA,PCMU,opus` | auto |
| `--no-amd` | Skip answering-machine detection | on |
| `--duration` | Seconds connected (`call`, `answer`) | 15 |
| `--timeout` | Limit for REGISTER, call setup and waiting for a call | 30 |
| `--header 'Name: value'` | Extra INVITE header, repeatable (`call`) | |
| `--dtmf`, `--dtmf-delay` | RFC 4733 digits, sent this many seconds after the answer (`call`) | none, 2 |
| `--json FILE` | Save the full report | |
| `--trace`, `--stats`, `-v` | One line per SIP message; RTP counters every second; PJSIP log | off |

Flags override the profile, and `--set` overrides both. `--set` reads JSON values: numbers, `true`/`false`, lists.

### Media modes

| Mode | What it sends |
|---|---|
| `silent` | Silence. RTP still flows (default) |
| `echo` | The audio it receives, decoded and encoded again |
| `wav` | `--wav` once, then silence. 8 kHz mono 16-bit PCM |
| `mic` | The microphone |

```bash
ffmpeg -f lavfi -i "sine=frequency=1000:sample_rate=8000:duration=60" -ac 1 -c:a pcm_s16le reference.wav
ffmpeg -i speech.mp3 -ar 8000 -ac 1 -c:a pcm_s16le reference.wav
```

### Results

The summary shows the result, the final SIP status, the Call-ID, the time to answer, the time connected, and the AMD verdict. Below it, one table row per RTP stream and direction: codec, remote address, packets, loss, jitter, RTT and estimated MOS.

| Result | Exit status | Meaning |
|---|---|---|
| `ANSWERED` | 0 | Answered, with an audio stream |
| `NO MEDIA` | 1 | 200 OK but no audio stream: usually no codec in common |
| `FAILED` | 1 | Not registered, not answered, or an error |
| `INTERRUPTED` | 130 | Ctrl+C |

```bash
simple-phone call 1002 --server pbx --user 1001 --json r.json && echo "route ok"
```

How to read the numbers:

- `ANSWERED` does not prove the audio was audible: RTP can carry silence. Record and listen, or use the end-to-end check.
- RX is what this side received. TX loss and jitter come from the far end's RTCP.
- RTT is the RTCP round trip, not one-way audio delay.
- `-` (or `null` in the JSON) means no sample, not zero.
- MOS is a network estimate: the E-model (ITU-T G.107) applied to loss, jitter and RTT with G.711 parameters. It never looks at the audio and tops out near 4.4. Use it to compare routes.
- A re-INVITE that rebuilds a stream adds a new entry (`stream 0.2`).

The JSON report adds the SIP and registration events with UTC times, the DTMF received, and the warnings. It never contains the password. It does contain numbers and identifiers, so review it before you share it.

### Who answered (AMD)

Every outgoing call is classified while it runs, in three layers:

1. **SIP:** an answer in under 1 s, with no 18x, hints at a machine.
2. **Speech pattern**, like Asterisk's `AMD()`: a short "hello?" and then silence is `human`. Speech longer than 1.5 s, or 3 words in a row, is `machine` (an IVR or a voicemail greeting).
3. **Tones** (Goertzel): SIT tones (913.8, 1370.6 and 1776.7 Hz), even in early media, give `sit`. A plain beep after the answer gives `voicemail`.

| Result | Meaning |
|---|---|
| `human` | Short greeting, then waited |
| `machine` | IVR or recorded greeting |
| `voicemail` | Voicemail beep |
| `sit` | Network announcement (e.g. number not in service) |
| `silence` | Nobody spoke within 2.5 s |
| `unsure` | No decision within 5 s |

The thresholds are Asterisk's defaults, checked only with synthetic audio. Calibrate them with recordings of your own traffic before you trust the result. Hold music, noise and long human greetings confuse layer 2. Incoming calls are not classified.

## Python API

```python
import asyncio
from simple_phone import AsyncPhone, Call, DigestAuth, Settings


async def main():
    settings = Settings(server="pbx.example.com", user="1001")
    async with AsyncPhone(settings, auth=DigestAuth(password="...")) as phone:
        # answered here, or CallFailed (486...) is raised
        async with phone.call("1002") as call:
            print((await call.amd()).result)  # human, machine, voicemail, sit...
            await call.dtmf("1234#")
        print(call.trace.flow())  # INVITE 100 180 200 ACK BYE 200
        print(call.report.mos)


asyncio.run(main())
```

`AsyncPhone` is one SIP account. `await phone.account(...)` adds another account on the same endpoint. `Phone` has the same API without `await`, like `httpx.Client` and `httpx.AsyncClient`. `Limits(max_calls, calls_per_second)` paces what `dial()` and `dial_all()` send, and `Timeouts` sets the default waits.

**Typed events.** The main ones are `Call.StateChanged`, `Call.Answered`, `Call.Ended`, `Call.Sip`, `Call.Dtmf`, `Call.Stats`, `Call.Amd`, `Call.Transaction`, `Call.TransferRequest`, `Call.Text`, `AsyncPhone.Incoming`, `AsyncPhone.Registered`, `AsyncPhone.Message`, `AsyncPhone.Presence`, `AsyncPhone.DialogState` and `AsyncPhone.Mwi`. There are four ways to consume them:

```python
@phone.on(Call.Dtmf, digit="#")  # decorator with a filter
async def done(event):
    await event.call.hangup()


class Extension(AsyncPhone):  # on_<group>_<event> methods
    async def on_phone_incoming(self, event):
        await event.call.answer(media="echo")


async for event in call.events(Call.Sip, Call.Dtmf):  # a stream
    ...
await call.wait_for(Call.Sip, lambda e: e.message.code == 183)  # a wait
```

**Calls:**

- Answering: `answer(183)` (early media), `reject`, `hangup`.
- DTMF: `dtmf`, by RFC 4733, SIP INFO or in-band tones.
- Control: `hold` and `unhold` (each returns once the re-INVITE is answered), `transfer`, `attended_transfer(other)`, `conference(other)`, `update`, `mute`, `gain`.
- Requests: `request("INFO", ...)` and `message` inside the call.
- Real-time text: `send_text` (RTT, RFC 4103, with `Settings(text=True)`).
- Inspection: `history`, `response`, `trace`, `evidence`, `duration`, `dump()`.
- Your own events: `emit(event)`.

**Phone:**

- Calls: `dial`, `call` (a context manager), `dial_all(targets, handler)`, `incoming()`.
- Out-of-dialog requests: `options`, `message`, `request` for any method. PJSUA sends these without credentials, so a PBX that challenges them answers 401.
- Registration: `register` and `unregister`.
- Presence and BLF: `subscribe(uri)` gives `Presence` events; `subscribe(uri, dialog=True)` gives `DialogState` events instead (idle, ringing, in a call). Also `set_presence` and `typing`.
- Network: `nat_type()` and `ip_changed()`.

**Settings:** `prack` (100rel), `session_timer` (RFC 4028), `mwi=True` (voicemail status as `Mwi` events), `follow_redirects`, `accept_transfers`, `srtp`, `ice`, `stun_servers`. Without a server, `Settings(register=False)` and `phone.uri` let two local accounts call each other.

**Media** (`simple_phone.media`):

```python
from simple_phone.media import PiperTTS, Recorder, Speaker, WavFile, WhisperSTT

tts, stt = PiperTTS("en_US-lessac-medium"), WhisperSTT("base")
phone = AsyncPhone(settings, tts=tts, stt=stt)
async with phone.call("1002") as call:
    # what is sent; change it any time
    await call.send(WavFile("notice.wav", loop=True))
    # where received audio goes
    await call.receive(Speaker(), Recorder("in.wav"))
    # stops when the far end starts talking
    await call.say("Press 1 for billing.", interrupt=True)
    choice = await call.gather(length=1, timeout=5)  # DTMF received
    text = await call.listen(timeout=10)  # the next sentence, transcribed
    async for frame in call.audio():  # raw PCM frames
        ...
```

STT and TTS are protocols: any object with `transcribe(pcm, rate)` or `synthesize(text)` works. The [examples](examples/README.md) run on one machine without a PBX.

## Using PJSUA2 directly

The binding is importable:

```python
from simple_phone import pjsua2 as pj
```

This build allows 64 calls per process; PJSIP's default is 4. For the endpoint lifecycle, callbacks, statistics and shutdown order, see `src/simple_phone/core/`. Two rules apply to any Python code on PJSUA2:

- Keep `info = call.getInfo()` in a variable before iterating `info.media`. Otherwise the items point to freed memory.
- No `Call`, `Account` or `Buddy` may outlive `libDestroy()`.

## Audio on WSL

You need this only for `--media mic` and `--listen`. WSLg provides PulseAudio, which ALSA reaches through its `pulse` plugin:

```bash
sudo apt install -y libasound2-plugins alsa-utils pulseaudio-utils
export PULSE_SERVER=unix:/mnt/wslg/PulseServer
pactl info
```

On `PJMEDIA_EAUD_NODEFDEV`, write this to `alsa-wslg.conf`:

```text
</usr/share/alsa/alsa.conf>
pcm.!default { type pulse }
ctl.!default { type pulse }
```

Then run the command with `ALSA_CONFIG_PATH="$PWD/alsa-wslg.conf" simple-phone ...`.

## Docker

```dockerfile
FROM python:3.14-slim-trixie
RUN apt-get update && apt-get install -y --no-install-recommends libasound2t64 \
    && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir simple-phone
ENTRYPOINT ["simple-phone"]
```

```bash
docker run --rm --network host -e SIP_PASSWORD simple-phone call 1002 --server pbx --user 1001
```

Use the host network. With a bridge network, the SDP still announces the container's address, and publishing ports does not change that.

## Troubleshooting

| Symptom | Check |
|---|---|
| `libasound.so.2: cannot open shared object file` | Install ALSA (see Install) |
| `REGISTER rejected: 401` or `403` | Login, password, domain, PBX policy |
| `REGISTER: nothing within 30s` | Address, port, UDP allowed, firewall |
| `NO MEDIA`, 488 or 415 | Codecs in common, SRTP policy, the SDP offer |
| RTP both ways but silence | Record and listen: the packets can carry silence |
| `DTMF not sent` | The far end did not negotiate `telephone-event` |
| `PJMEDIA_EAUD_NODEFDEV` | ALSA plugins and the default device (see WSL) |

## Development

See [docs/development.md](docs/development.md) for building PJSIP, running the tests (including the Asterisk ones in Docker), CI and releases. See [docs/architecture.md](docs/architecture.md) for how the code is organized.

## License

GPL-2.0-or-later. PJSIP is GPL v2 or later and is linked into this package, so the package carries the same license. Teluu sells a commercial PJSIP license for closed-source use.
