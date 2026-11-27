# Python API

*[Português](api.pt-BR.md)*

```python
from simple_phone import AsyncPhone, Call, Phone, Settings, Limits, Timeouts
from simple_phone import PhoneError, CallFailed, WaitTimeout, RegistrationFailed
```

`AsyncPhone` is one SIP account. `Phone` has the same methods without `await`, on a loop in its own thread. A `Call` comes from `phone.dial()`, `phone.call()`, `phone.incoming()` or an `Incoming` event.

## A phone

```python
phone = AsyncPhone(server="pbx.example.com", user="1001", password="...")
async with phone:  # starts PJSIP and registers; raises RegistrationFailed
    ...  # leaving the block hangs up, unregisters and stops
```

The keyword arguments are the fields of `Settings`. You can also pass a `Settings` object, or load a JSON file with the same fields:

```python
phone = AsyncPhone(Settings(server="pbx.example.com", user="1001"), password="...")
phone = AsyncPhone.from_profile("account.json")  # password from $SIP_PASSWORD
```

The most used settings:

| Setting | Meaning | Default |
|---|---|---|
| `server`, `user` | Registrar and extension | required |
| `port`, `domain`, `proxy`, `auth_user` | Registrar port, identity domain, outbound proxy, Digest login | 5060, `server`, none, `user` |
| `register` | Send REGISTER. `False` for a trunk, or for calls between local accounts | `True` |
| `transport` | `udp`, `tcp`, `tls` | `udp` |
| `local_port`, `rtp_port` | Local SIP port; first of 100 RTP ports | 5070, 40000 |
| `media`, `wav`, `wav_loop` | What a call sends: `silent`, `echo`, `wav`, `mic` | `silent` |
| `speaker`, `record` | Play received audio; record it to a WAV | off |
| `codec` | `auto`, or names such as `PCMA,PCMU,opus` | `auto` |
| `amd` | Classify who answers outgoing calls | `True` |
| `amd_initial_silence_ms`, `amd_greeting_ms`, `amd_after_greeting_silence_ms`, `amd_total_ms`, `amd_voice_rms`, `amd_max_words` | AMD limits; see [docs/cli.md](cli.md#who-answered-amd) | 2500, 1500, 800, 5000, 400, 5 |
| `srtp`, `ice`, `stun_servers`, `public_address` | Media security and NAT | off |
| `prack`, `session_timer` | 100rel and RFC 4028: `off`, `optional`, ... | `off` |
| `text`, `mwi` | Offer real-time text; subscribe to voicemail status | `False` |
| `follow_redirects`, `accept_transfers` | Follow a 3xx; accept a REFER | `False`, `True` |
| `compact_headers` | Send header names in compact form (`i:`, `f:`, `v:`...). Applies to every account of the process | `False` |

`await phone.account(user="1002", password=...)` adds another account on the same endpoint. It keeps this phone's settings except the ones you pass, shares the SIP port, and takes RTP ports 200 above the last account. It also takes a JSON profile path or a `Settings`. With `register=False`, two accounts can call each other at `phone.uri`, with no server.

`Limits(max_calls=4, calls_per_second=None)` paces outgoing calls: `dial()` waits for a free slot and raises `PoolTimeout` after `Timeouts.pool` seconds. `Timeouts(register=30, setup=30, pool=30, request=10)` sets the default waits.

## Calls

```python
async with phone.call("1002", headers={"X-Test": "1"}) as call:
    ...  # answered here; hung up when the block ends
```

`phone.call()` raises `CallFailed` when the call is not answered. The exception carries `code` and `reason` (486, 404...). To drive each step yourself:

```python
call = await phone.dial("1002")  # returns while it rings
await call.answered(timeout=30)  # or CallFailed, or WaitTimeout
report = await call.hangup()
```

Incoming calls arrive as events, or one at a time:

```python
call = await phone.incoming(timeout=60)
await call.answer(media="echo")  # or call.reject(486)
```

`await phone.dial_all(targets, handler)` dials many targets within the `Limits`, runs `await handler(call)` on each, and returns `[(target, result)]`. A target that fails has its exception as the result.

What a call can do:

| Method | What it does |
|---|---|
| `answer(code=200, **media)` | Answer. `answer(183)` starts early media. `media="echo"`, `record="in.wav"` apply to this call |
| `reject(code=486)`, `hangup()` | Refuse; hang up and return the report |
| `dtmf(digits, method="rfc4733")` | Send DTMF. Methods: `rfc4733`, `info`, `inband` |
| `gather(length=None, timeout=5, finish_on="#")` | Collect DTMF received |
| `hold()`, `unhold()` | Return when the re-INVITE is answered |
| `transfer(target)`, `attended_transfer(other)` | REFER; progress arrives as `Call.TransferStatus` |
| `conference(other)` | Mix the audio of two calls |
| `mute()`, `gain(microphone, speaker)` | Levels |
| `request(method, body)`, `message(text)`, `update()` | In-dialog INFO, MESSAGE, UPDATE |
| `send_text(text)` | Real-time text (RFC 4103); needs `Settings(text=True)` on both sides |
| `amd(timeout=10, settle=0, transcribe=0, **limits)` | Who answered: `human`, `machine`, `voicemail`, `sit`, `silence`, `unsure`, `ivr`. `settle` keeps listening for a later decision (a beep, SIT, or a voice after `silence`). `transcribe=8` also judges 8 s of words with the phone's STT (off by default: costly). `limits` are `amd_*` settings for this call only |
| `dump()` | PJSUA's text dump of the call |

What a call knows:

| Attribute | Contents |
|---|---|
| `state`, `code`, `reason` | Current state (`CALLING`, `EARLY`, `CONFIRMED`, `DISCONNECTED`...) and last SIP status |
| `trace`, `trace.flow()` | Every SIP message; `['INVITE', '100', '180', '200', 'ACK', ...]` |
| `history`, `response` | Responses to our INVITE; the final one |
| `report` | After the call: `answered`, `code`, `connected_seconds`, `mos`, `stats`, `amd`, and everything in `raw` |
| `duration` | Seconds connected so far |
| `dtmf_sent`, `dtmf_received`, `text_received`, `transcript` | What arrived |
| `timeline` | Every event of the call, in order |

## Events

Events are dataclasses with `at`, `phone` and `call`. Three ways to use them:

```python
@phone.on(Call.Dtmf, digit="#")  # a handler, with an optional filter
async def done(event):
    await event.call.hangup()


async for event in call.events(Call.Sip):  # a stream (also phone.events())
    print(event.message.first_line)

event = await call.wait_for(Call.Sip, lambda e: e.message.code == 183, timeout=10)
```

`wait_for` raises `CallFailed` if the call ends first and `WaitTimeout` on timeout. Handlers can be plain functions or `async def`; an exception in one is logged and kept in `phone.errors`.

| Call event | Fields |
|---|---|
| `Call.StateChanged` | `state`, `code`, `reason` |
| `Call.Answered`, `Call.Ended` | `Ended.report` |
| `Call.Sip` | `message`: `method`, `code`, `headers`, `raw`, `direction` |
| `Call.Dtmf`, `Call.DtmfSent` | `digit`, `method`; `digits`, `method` |
| `Call.Stats` | `stats`: `codec`, `rx_packets`, `rx_loss_percent`, `jitter_ms`, `rtt_ms`, `mos` |
| `Call.Amd` | `amd.result`, `amd.reason`, `amd.leading_silence_ms` |
| `Call.MediaChanged` | `status`, `held` |
| `Call.Transaction` | `method`, `code`, `reason` of an in-dialog request |
| `Call.TransferStatus`, `Call.TransferRequest` | `code`, `reason`, `final`, `success`; `target`, `accepted` |
| `Call.Redirected`, `Call.Reinvite` | `target`, `followed`; `has_offer` |
| `Call.Message`, `Call.Text` | `body`; `text` |

| Phone event | Fields |
|---|---|
| `AsyncPhone.Incoming` | `call`, `remote_uri` |
| `AsyncPhone.Registration` | `code`, `reason`, `active` |
| `AsyncPhone.Sip` | `message`, for REGISTER, OPTIONS and others outside a call |
| `AsyncPhone.Message`, `AsyncPhone.Typing` | `from_uri`, `body`; `from_uri`, `typing` |
| `AsyncPhone.Presence`, `AsyncPhone.DialogState` | `uri`, `online`, `note`; `uri`, `state` |
| `AsyncPhone.Mwi` | `waiting`, `body` |
| `AsyncPhone.Rejected` | `code`, `reason`, `remote_uri` of an INVITE refused before it became a call |
| `AsyncPhone.Response`, `AsyncPhone.Nat` | Results of `request()` and `nat_type()` |
| `AsyncPhone.Warning`, `AsyncPhone.Log` | `text` |

`Phone.<Name>` is the same type as `AsyncPhone.<Name>`. To add events of your own, subclass `CallEvent` and call `call.emit(event)`.

## Outside a call

```python
response = await phone.options("sip:1002@pbx.example.com")  # .code, .reason
await phone.message("1002", "hello")
await phone.request("NOTIFY", "1002", body, headers={"Event": "..."})
```

PJSUA sends these without credentials, so a PBX that challenges them answers 401.

```python
await phone.subscribe("1002")  # Presence events
await phone.subscribe("1003", dialog=True)  # DialogState events (BLF) instead
await phone.set_presence(True, "at my desk")
await phone.typing("1002")

await phone.register()
await phone.unregister()
nat = await phone.nat_type()  # needs stun_servers
await phone.ip_changed()  # after a network change
await phone.configure(media="echo")  # default for the next calls
```

## Media

```python
await call.send("echo")  # also "silent", "mic"
await call.send("wav", "notice.wav", loop=True)
await call.play("beep.wav")  # over what is being sent; returns when done
await call.record("in.wav")  # record(None) stops
await call.speaker()  # play received audio on the sound card

async for frame in call.audio():  # received audio: 20 ms, 8 kHz, 16-bit mono
    ...
stream = await call.stream(rate=16000)  # audio from Python
stream.write(pcm)

async for stats in call.stats():  # RTP statistics, once a second
    ...
```

Test audio, as 16-bit mono PCM at 8 kHz. `noise()` is as loud as speech but has no pitch, so the AMD and `listen()` take it for someone talking:

```python
from simple_phone.media import noise, save_wav, silence, tone

pcm = tone(1000, 0.5) + silence(0.2) + noise(2)
await call.send("wav", save_wav("test.wav", pcm))
```

With speech engines:

```python
from simple_phone.media import PiperTTS, WhisperSTT

phone = AsyncPhone(..., tts=PiperTTS("en_US-lessac-medium"), stt=WhisperSTT("base"))
await call.say("Press 1 for billing.", interrupt=True)  # stops when the far end talks
text = await call.listen(timeout=10)  # the next sentence heard
```

Any object with `async transcribe(pcm, rate)` works as STT, and any object with `synthesize(text)` that yields `AudioFrame`s works as TTS.

## PJSUA2 directly

```python
from simple_phone import pjsua2 as pj
```

This build allows 64 calls per process; PJSIP's default is 4. Two rules apply to any Python code on PJSUA2:

- Keep `info = call.getInfo()` in a variable before iterating `info.media`. Otherwise the items point to freed memory.
- No `Call`, `Account` or `Buddy` may outlive `libDestroy()`.
