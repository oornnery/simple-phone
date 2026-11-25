# Changelog

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
