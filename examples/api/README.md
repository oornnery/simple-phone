# API examples (AsyncPhone / Phone)

Each example runs without a PBX and stands on its own. `phone` is `AsyncPhone(server="127.0.0.1", user="1001", register=False)`, and the far end is a second account in the same process, `await phone.account(user="1002")`, answered in the same file. On a real PBX, use `AsyncPhone(server=..., user=..., password=...)` and dial extensions.

```bash
cd examples/api
python 01_call.py
```

| File | What it shows |
|---|---|
| [01_call.py](01_call.py) | `async with phone.call()`, `history`, DTMF, `duration`, the report, `CallFailed` (486), `dial`/`answered`/`hangup` step by step |
| [02_handlers.py](02_handlers.py) | Receiving calls: `@phone.on(Type)`, with a filter, `phone.events()`, early media (183) |
| [03_sip.py](03_sip.py) | Headers, `wait_for(Call.Sip)`, `response`, `trace.flow()` and the ladder; OPTIONS and MESSAGE outside a call; INFO, MESSAGE and UPDATE inside; `dump()` |
| [04_media.py](04_media.py) | `send("wav", file)`, `record(file)`, `audio()`, `stats()`, `play`, `stream()`, gain, mute, DTMF rfc4733/info/inband |
| [05_call_control.py](05_call_control.py) | Hold, conference, attended and blind transfer, REFER received |
| [06_amd.py](06_amd.py) | Person, IVR, voicemail or announcement (`amd()`, SIP hints) |
| [07_dialer.py](07_dialer.py) | `dial_all` within `Limits(max_calls, calls_per_second)`; `PoolTimeout` |
| [08_sync.py](08_sync.py) | `Phone`: the same API without async/await |
| [09_accounts.py](09_accounts.py) | Several accounts, codecs, audio devices, `configure`, `ip_changed`; with a profile: `from_profile`, REGISTER and unREGISTER |
| [10_ivr_server.py](10_ivr_server.py) | An IVR on the answering side: `say` (Piper, with barge-in) and `gather` (extra `tts`) |
| [11_listen.py](11_listen.py) | `listen()` (Whisper) and `transcript` against that IVR (extra `stt`) |
| [12_presence_text.py](12_presence_text.py) | Presence (`subscribe`, `set_presence`), `typing`, real-time text (`text=True`, `send_text`), `Phone.Rejected` |

Start `python 10_ivr_server.py` in another terminal before 11. Generated files (WAVs) go to `/tmp/simple-phone-examples/`.
