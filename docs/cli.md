# Command line

*[Português](cli.pt-BR.md)*

```bash
simple-phone call 1002 --server pbx.example.com --user 1001 --media echo --duration 30
simple-phone answer --server pbx.example.com --user 1002 --media echo --timeout 600
simple-phone doctor --server pbx.example.com --user 1001
simple-phone options pbx.example.com
simple-phone message 1002 'hello' --server pbx.example.com --user 1001
simple-phone devices
```

- `call` registers, dials, stays connected for `--duration` seconds, hangs up and prints a summary. The call ends early if the far end hangs up or you press Ctrl+C.
- `answer` waits up to `--timeout` seconds for a call, then does the same.
- `doctor` checks versions, codecs, audio devices, NAT (when `stun_servers` is set), REGISTER and an OPTIONS ping. Without `--server` it checks only this machine.
- `options` and `message` send one request outside a call and print the response, like curl: status line, headers and body. The target alone is enough: `simple-phone options pbx.example.com`. Without `--server` the target's host is the server, the `From` user is `simple-phone`, and nothing registers. They exit with 0 on any response and 1 when none arrives. PJSUA sends them without credentials, so a PBX that challenges them answers 401.
- `devices` lists audio devices.

A target is a number (`1002`, which becomes `sip:1002@<domain>`), `user@host`, or a `sip:` URI.

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

## Options

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
| `--speaker` | Play received audio on this machine | off |
| `--codec` | `auto`, or names such as `PCMA,PCMU,opus` | auto |
| `--no-amd` | Skip answering-machine detection | on |
| `--duration` | Seconds connected (`call`, `answer`) | 15 |
| `--timeout` | Seconds to register, to be answered, and to wait for a call | 30 |
| `--header 'Name: value'` | Extra header, repeatable (`call`, `options`, `message`) | |
| `--dtmf`, `--dtmf-delay` | RFC 4733 digits, sent this many seconds after the answer (`call`, `answer`) | none, 2 |
| `--json FILE` | Save the full report | |
| `--trace`, `--stats`, `-v` | One line per SIP message; RTP counters every second; PJSIP log | off |

Flags override the profile, and `--set` overrides both. `--set` reads JSON values: numbers, `true`/`false`, lists.

## Media modes

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

## Results

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

## Who answered (AMD)

Every outgoing call is classified while it runs, in three layers:

1. **SIP:** An answer in under 1 s, with no 18x, hints at a machine.
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

## Audio on WSL

You need this only for `--media mic` and `--speaker`. WSLg provides PulseAudio, which ALSA reaches through its `pulse` plugin:

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
| `libasound.so.2: cannot open shared object file` | Install ALSA: `sudo apt install libasound2t64` (Debian 13, Ubuntu 24.04+) or `libasound2` |
| `REGISTER rejected: 401` or `403` | Login, password, domain, PBX policy |
| `REGISTER: nothing within 30s` | Address, port, UDP allowed, firewall |
| `NO MEDIA`, 488 or 415 | Codecs in common, SRTP policy, the SDP offer |
| RTP both ways but silence | Record and listen: the packets can carry silence |
| `DTMF not sent` | The far end did not negotiate `telephone-event` |
| `PJMEDIA_EAUD_NODEFDEV` | ALSA plugins and the default device (see WSL) |
