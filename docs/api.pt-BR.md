# API Python

*[English](api.md)*

```python
from simple_phone import AsyncPhone, Call, Phone, Settings, Limits, Timeouts
from simple_phone import PhoneError, CallFailed, WaitTimeout, RegistrationFailed
```

`AsyncPhone` é uma conta SIP. `Phone` tem os mesmos métodos sem `await`, num loop em thread própria. Uma `Call` vem de `phone.dial()`, `phone.call()`, `phone.incoming()` ou de um evento `Incoming`.

## Um telefone

```python
phone = AsyncPhone(server="pbx.example.com", user="1001", password="...")
async with phone:  # inicia o PJSIP e registra; levanta RegistrationFailed
    ...  # ao sair do bloco: desliga as chamadas, desregistra e para
```

Os argumentos nomeados são os campos de `Settings`. Também dá para passar um objeto `Settings`, ou carregar um arquivo JSON com os mesmos campos:

```python
phone = AsyncPhone(Settings(server="pbx.example.com", user="1001"), password="...")
phone = AsyncPhone.from_profile("conta.json")  # senha em $SIP_PASSWORD
```

As configurações mais usadas:

| Campo | Significado | Padrão |
|---|---|---|
| `server`, `user` | Registrador e ramal | obrigatórios |
| `port`, `domain`, `proxy`, `auth_user` | Porta do registrador, domínio da identidade, proxy de saída, login Digest | 5060, `server`, nenhum, `user` |
| `register` | Envia REGISTER. `False` para trunk, ou para chamadas entre contas locais | `True` |
| `transport` | `udp`, `tcp`, `tls` | `udp` |
| `local_port`, `rtp_port` | Porta SIP local; primeira de 100 portas RTP | 5070, 40000 |
| `media`, `wav`, `wav_loop` | O que a chamada envia: `silent`, `echo`, `wav`, `mic` | `silent` |
| `speaker`, `record` | Toca o áudio recebido; grava em WAV | desligados |
| `codec` | `auto`, ou nomes como `PCMA,PCMU,opus` | `auto` |
| `amd` | Classifica quem atende as chamadas feitas | `True` |
| `amd_initial_silence_ms`, `amd_greeting_ms`, `amd_after_greeting_silence_ms`, `amd_total_ms`, `amd_voice_rms`, `amd_max_words` | Limites do AMD; veja [docs/cli.pt-BR.md](cli.pt-BR.md#quem-atendeu-amd) | 2500, 1500, 800, 5000, 400, 5 |
| `srtp`, `ice`, `stun_servers`, `public_address` | Segurança da mídia e NAT | desligados |
| `prack`, `session_timer` | 100rel e RFC 4028: `off`, `optional`, ... | `off` |
| `text`, `mwi` | Oferece texto em tempo real; assina o estado da caixa postal | `False` |
| `follow_redirects`, `accept_transfers` | Segue um 3xx; aceita um REFER | `False`, `True` |
| `compact_headers` | Envia os nomes de header na forma compacta (`i:`, `f:`, `v:`...). Vale para todas as contas do processo | `False` |

`await phone.account(user="1002", password=...)` adiciona outra conta no mesmo endpoint. Ela herda as configurações deste telefone, menos as que você passar, divide a porta SIP e usa portas RTP 200 acima da última conta. Também aceita o caminho de um perfil JSON ou um `Settings`. Com `register=False`, duas contas ligam uma para a outra em `phone.uri`, sem servidor.

`Limits(max_calls=4, calls_per_second=None)` dita o ritmo das chamadas feitas: `dial()` espera uma vaga e levanta `PoolTimeout` depois de `Timeouts.pool` segundos. `Timeouts(register=30, setup=30, pool=30, request=10)` define as esperas padrão.

## Chamadas

```python
async with phone.call("1002", headers={"X-Teste": "1"}) as call:
    ...  # atendida aqui; desligada quando o bloco termina
```

`phone.call()` levanta `CallFailed` quando a chamada não é atendida. A exceção traz `code` e `reason` (486, 404...). Para conduzir cada passo:

```python
call = await phone.dial("1002")  # volta enquanto toca
await call.answered(timeout=30)  # ou CallFailed, ou WaitTimeout
report = await call.hangup()
```

As chamadas recebidas chegam como eventos, ou uma por vez:

```python
call = await phone.incoming(timeout=60)
await call.answer(media="echo")  # ou call.reject(486)
```

`await phone.dial_all(destinos, handler)` disca vários destinos dentro dos `Limits`, roda `await handler(call)` em cada um e devolve `[(destino, resultado)]`. O resultado de um destino que falha é a exceção.

O que uma chamada faz:

| Método | O que faz |
|---|---|
| `answer(code=200, **media)` | Atende. `answer(183)` inicia early media. `media="echo"`, `record="in.wav"` valem para esta chamada |
| `reject(code=486)`, `hangup()` | Recusa; desliga e devolve o relatório |
| `dtmf(digits, method="rfc4733")` | Envia DTMF. Métodos: `rfc4733`, `info`, `inband` |
| `gather(length=None, timeout=5, finish_on="#")` | Coleta o DTMF recebido |
| `hold()`, `unhold()` | Voltam quando o re-INVITE é respondido |
| `transfer(target)`, `attended_transfer(outra)` | REFER; o andamento chega como `Call.TransferStatus` |
| `conference(outra)` | Mistura o áudio de duas chamadas |
| `mute()`, `gain(microphone, speaker)` | Níveis |
| `request(method, body)`, `message(text)`, `update()` | INFO, MESSAGE e UPDATE dentro do diálogo |
| `send_text(text)` | Texto em tempo real (RFC 4103); exige `Settings(text=True)` nos dois lados |
| `amd(timeout=10, settle=0, transcribe=0, **limits)` | Quem atendeu: `human`, `machine`, `voicemail`, `sit`, `silence`, `unsure`, `ivr`. `settle` continua ouvindo por uma decisão posterior (bipe, SIT, ou voz depois de `silence`). `transcribe=8` também julga 8 s de palavras com o STT do telefone (desligado por padrão: custa caro). `limits` são campos `amd_*` só para esta chamada |
| `dump()` | O dump em texto que o PJSUA faz da chamada |

O que uma chamada sabe:

| Atributo | Conteúdo |
|---|---|
| `state`, `code`, `reason` | Estado atual (`CALLING`, `EARLY`, `CONFIRMED`, `DISCONNECTED`...) e último status SIP |
| `trace`, `trace.flow()` | Todas as mensagens SIP; `['INVITE', '100', '180', '200', 'ACK', ...]` |
| `history`, `response` | As respostas ao nosso INVITE; a final |
| `report` | Depois da chamada: `answered`, `code`, `connected_seconds`, `mos`, `stats`, `amd`, e tudo em `raw` |
| `duration` | Segundos conectada até agora |
| `dtmf_sent`, `dtmf_received`, `text_received`, `transcript` | O que chegou |
| `timeline` | Todos os eventos da chamada, em ordem |

## Eventos

Os eventos são dataclasses com `at`, `phone` e `call`. Três formas de usar:

```python
@phone.on(Call.Dtmf, digit="#")  # um handler, com filtro opcional
async def fim(event):
    await event.call.hangup()


async for event in call.events(Call.Sip):  # um fluxo (também phone.events())
    print(event.message.first_line)

event = await call.wait_for(Call.Sip, lambda e: e.message.code == 183, timeout=10)
```

`wait_for` levanta `CallFailed` se a chamada terminar antes e `WaitTimeout` se o tempo acabar. Os handlers podem ser funções comuns ou `async def`; uma exceção num deles é logada e guardada em `phone.errors`.

| Evento de chamada | Campos |
|---|---|
| `Call.StateChanged` | `state`, `code`, `reason` |
| `Call.Answered`, `Call.Ended` | `Ended.report` |
| `Call.Sip` | `message`: `method`, `code`, `headers`, `raw`, `direction` |
| `Call.Dtmf`, `Call.DtmfSent` | `digit`, `method`; `digits`, `method` |
| `Call.Stats` | `stats`: `codec`, `rx_packets`, `rx_loss_percent`, `jitter_ms`, `rtt_ms`, `mos` |
| `Call.Amd` | `amd.result`, `amd.reason`, `amd.leading_silence_ms` |
| `Call.MediaChanged` | `status`, `held` |
| `Call.Transaction` | `method`, `code`, `reason` de uma requisição dentro do diálogo |
| `Call.TransferStatus`, `Call.TransferRequest` | `code`, `reason`, `final`, `success`; `target`, `accepted` |
| `Call.Redirected`, `Call.Reinvite` | `target`, `followed`; `has_offer` |
| `Call.Message`, `Call.Text` | `body`; `text` |

| Evento do telefone | Campos |
|---|---|
| `AsyncPhone.Incoming` | `call`, `remote_uri` |
| `AsyncPhone.Registration` | `code`, `reason`, `active` |
| `AsyncPhone.Sip` | `message`, para REGISTER, OPTIONS e outras fora de chamada |
| `AsyncPhone.Message`, `AsyncPhone.Typing` | `from_uri`, `body`; `from_uri`, `typing` |
| `AsyncPhone.Presence`, `AsyncPhone.DialogState` | `uri`, `online`, `note`; `uri`, `state` |
| `AsyncPhone.Mwi` | `waiting`, `body` |
| `AsyncPhone.Rejected` | `code`, `reason`, `remote_uri` de um INVITE recusado antes de virar chamada |
| `AsyncPhone.Response`, `AsyncPhone.Nat` | Resultados de `request()` e `nat_type()` |
| `AsyncPhone.Warning`, `AsyncPhone.Log` | `text` |

`Phone.<Nome>` é o mesmo tipo que `AsyncPhone.<Nome>`. Para criar eventos seus, herde de `CallEvent` e chame `call.emit(evento)`.

## Fora de chamada

```python
response = await phone.options("sip:1002@pbx.example.com")  # .code, .reason
await phone.message("1002", "olá")
await phone.request("NOTIFY", "1002", body, headers={"Event": "..."})
```

O PJSUA envia essas requisições sem credenciais, então um PABX que as desafia responde 401.

```python
await phone.subscribe("1002")  # eventos Presence
await phone.subscribe("1003", dialog=True)  # eventos DialogState (BLF) no lugar
await phone.set_presence(True, "na mesa")
await phone.typing("1002")

await phone.register()
await phone.unregister()
nat = await phone.nat_type()  # precisa de stun_servers
await phone.ip_changed()  # depois de trocar de rede
await phone.configure(media="echo")  # padrão das próximas chamadas
```

## Mídia

```python
await call.send("echo")  # também "silent", "mic"
await call.send("wav", "aviso.wav", loop=True)
await call.play("bipe.wav")  # por cima do que é enviado; volta ao terminar
await call.record("entrada.wav")  # record(None) para
await call.speaker()  # toca o áudio recebido na placa de som

async for frame in call.audio():  # áudio recebido: 20 ms, 8 kHz, 16 bits mono
    ...
stream = await call.stream(rate=16000)  # áudio gerado em Python
stream.write(pcm)

async for stats in call.stats():  # estatísticas RTP, uma vez por segundo
    ...
```

Áudio de teste, em PCM 16 bits mono a 8 kHz. `noise()` é tão alto quanto a fala, mas não tem tom, então o AMD e o `listen()` o tomam por alguém falando:

```python
from simple_phone.media import noise, save_wav, silence, tone

pcm = tone(1000, 0.5) + silence(0.2) + noise(2)
await call.send("wav", save_wav("teste.wav", pcm))
```

Com motores de voz:

```python
from simple_phone.media import PiperTTS, WhisperSTT

phone = AsyncPhone(
    ..., tts=PiperTTS("pt_BR-faber-medium"), stt=WhisperSTT("base", language="pt")
)
await call.say(
    "Para segunda via, digite 1.", interrupt=True
)  # para quando o outro lado fala
texto = await call.listen(timeout=10)  # a próxima frase ouvida
```

Qualquer objeto com `async transcribe(pcm, rate)` serve de STT, e qualquer objeto com `synthesize(text)` que gere `AudioFrame`s serve de TTS.

## PJSUA2 direto

```python
from simple_phone import pjsua2 as pj
```

Este build aceita 64 chamadas por processo; o padrão do PJSIP é 4. Duas regras valem para qualquer código Python sobre PJSUA2:

- Guarde `info = call.getInfo()` numa variável antes de percorrer `info.media`. Sem isso, os itens apontam para memória liberada.
- Nenhum `Call`, `Account` ou `Buddy` pode viver depois de `libDestroy()`.
