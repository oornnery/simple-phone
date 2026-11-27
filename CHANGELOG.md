# Changelog

## Unreleased

- `simple-phone amd FILE.wav` replays a recording through the AMD, offline, and prints each decision with its reason; `--amd-*` options try other limits, `--answered-at` marks the answer.

## 0.1.12

- Python 3.11, 3.12 and 3.13 are supported, next to 3.14 and 3.15: wheels for cp311 to cp315 on Linux x86_64. The command's typo suggestions need 3.14 and the lazy imports 3.15; older versions run without them.
- Windows is not supported yet; AGENTS.md lists what a Windows wheel needs.

## 0.1.11

- AMD reads SIP with the audio: speech in early media (183) followed by a failure (4xx-6xx) without an answer is `sit`, a network announcement, with or without SIT tones. Ringback tones do not count as speech.
- Optional, because STT is costly: `call.amd(transcribe=8)` transcribes 8 s of the far end with the phone's STT and corrects the verdict by its words, in Portuguese and English: `voicemail` ("leave a message"), `sit` ("not in service"), and the new result `ivr` ("press 1"). A beep, SIT tones or an announcement still win. The transcript is in `amd.raw["transcript"]`.

## 0.1.10

- AMD: `silence` is provisional. An IVR that answers mute and speaks seconds later used to stay `silence`; now the voice pattern starts over from the first voice, with the same limits, and its result (`machine`, `human` or `unsure`) follows as a new decision. The reason says so (`greeting longer than 1500ms after 3.0 s of silence`), and the result has `leading_silence_ms`. `machine`, `human`, `unsure` and `sit` stay final.
- AMD limits are settings: `amd_initial_silence_ms`, `amd_greeting_ms`, `amd_after_greeting_silence_ms`, `amd_total_ms`, `amd_voice_rms`, `amd_max_words`, with Asterisk's defaults. `call.amd(...)` takes the same names for one call. The command has `--amd-initial-silence` and `--amd-greeting`.

## 0.1.9

- `--compact-headers` (`Settings.compact_headers`) sends SIP header names in compact form: `i:`, `f:`, `t:`, `v:`... PJSUA2 does not expose this, so the binding gets `setCompactForm()` from `packaging/pjsua2_extra.i`.
- Received messages read every compact header form. Only eight were mapped before: a NOTIFY with `o: dialog` was not seen as BLF.
- The command can send generated audio: `--media tone` (`--tone HZ`) and `--media noise`. `--loop` repeats `--wav`.
- `--media-delay` sends silence after the answer before the media starts; `--answer-delay` lets `answer` ring first. Media and DTMF run in the order of their delays.
- Example profiles for a PBX, a trunk, NAT and a test answerer, a Profiles section in `docs/cli.md`, and README recipes for the command.

## 0.1.8

- `call` and `answer` work without an account too: `simple-phone call 1002@192.0.2.10` dials the host directly, and `simple-phone answer` waits on this machine. With neither `--server` nor `--profile`, the `From` user is `simple-phone` and nothing registers.
- A typo names the typo: `--verion` is an unrecognized argument, and a misspelt command gets a suggestion. The help lists `options` and `message`.

## 0.1.7

- `simple-phone options pbx.example.com` works with the target alone, like curl. Without `--server` the target's host is the server, the `From` user is `simple-phone` and nothing registers. A bare host is sent to as `sip:host`.
- `options` and `message` exit with 0 on any response (a PBX answers 401 to requests without credentials) and 1 when none arrives.
- Fixed: the text of `message` went into `Settings.text` (real-time text), whose name it shared.

## 0.1.6

- A failure while PJSIP starts (port in use, unknown codec or audio device) prints `error: ...` instead of a traceback. In the API it is a `PhoneError`.
- `capture_device` and `playback_device` must be ids from `simple-phone devices`. An unknown id used to give a silent call.
- `unregister()` raises `WaitTimeout` on timeout, like the other waits.
- The tests run the audio-device paths (device list, mic, speaker) on ALSA null devices, so they run in CI without a sound card.

## 0.1.5

- Wheels for Python 3.15, next to 3.14. `uvx simple-phone` works without `--python`.
- `simple-phone options DEST` and `simple-phone message DEST TEXT` send one request and print the SIP response like an HTTP client: status line, headers and body.
- A target can be `user@host`, besides a number or a `sip:` URI.
- Fixed: `simple-phone devices` showed a SWIG pointer as the id, and Python warned about a leak per device. The id is now the position in the list.
- On Python 3.15, lazy imports (PEP 810) cut `simple-phone --version` from about 750 ms to 330 ms.

## 0.1.4

- `simple_phone.media` makes test audio: `tone(hz, seconds)`, `noise(seconds)` (as loud as speech, with no pitch), `silence(seconds)` and `save_wav(path, pcm)`.
- The examples and tests use them instead of their own copies.

## 0.1.3

- `phone.account(user="1002")` adds an account from keyword fields: it keeps this phone's settings except the ones passed, and takes RTP ports 200 above the last account. A `Settings` or a profile path still works.
- A `pathlib.Path` works as `wav` and `record` in `Settings` and `call.answer()`.
- The examples stand alone: no `local.py` helper and no `Settings`.

## 0.1.2

- `PiperTTS` and `WhisperSTT` default to English: the voice `en_US-lessac-medium` and `language="en"`. For Portuguese, pass `PiperTTS("pt_BR-faber-medium")` and `WhisperSTT("base", language="pt")`.
- The examples are in English, comments and output included.

## 0.1.1

- The most complex functions are split into smaller ones. complexipy passes its default limit of 15. Behavior is the same.
- `Settings` errors name the field and its allowed values or range, e.g. `port must be between 1 and 65535`.
- The README starts with install and usage. The release steps include `uv lock` and this changelog.

## 0.1.0

The API has one way to do each thing. Code written for 0.0.1 needs these changes:

- Settings go in as keyword arguments, and the password only as `password=`: `AsyncPhone(server=..., user=..., password=...)`. `DigestAuth` is gone.
- Media is named by a string: `call.send("echo")`, `call.send("wav", file, loop=True)`, `call.record(path)`, `call.speaker()`. The source and sink classes are gone.
- Handlers use `@phone.on(Type, **filters)` only. `on_*` methods in a subclass are no longer called.
- Removed events: `Registered`, `RegistrationFailed`, `AccountChanged`, `Info`, `AudioChanged`, `Recording`, `Insight`. Registration state arrives as `AsyncPhone.Registration`.
- `Call.evidence` and `Call.receive` are gone.

Added:

- `call.emit(event)` adds an event of your own to a call. `CallEvent` and `PhoneEvent` are exported for it.
- `Call.dtmf_sent`, next to `Call.dtmf_received`.

Command line:

- Options you leave out no longer override the profile.
- `--dtmf` and `--dtmf-delay` also work with `answer`.

## 0.0.1

First version: PJSIP 2.17 compiled into the wheel, `AsyncPhone` and `Phone` with typed events, the `simple-phone` command (`call`, `answer`, `doctor`, `devices`), tests against Asterisk in Docker, and CI that publishes to PyPI.
