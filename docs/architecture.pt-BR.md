# Arquitetura

*[English](architecture.md)*

```text
src/simple_phone/
  _native/      binding SWIG do PJSUA2 (gerado por scripts/build_pjsip.sh, compilado pelo setup.py)
  core/         PJSUA2 numa thread: Engine, Endpoint, Account, Call, AMD, parser do trace SIP
  events.py     eventos tipados: CallEvents e PhoneEvents
  models.py     Settings, Limits, Timeouts, DigestAuth, erros, Report/Stats/Amd
  phone.py      AsyncPhone e o hub que leva os eventos do core às contas e chamadas
  call.py       Call: ações, esperas, streams, evidências
  sync.py       Phone: o AsyncPhone sem await, num loop em thread própria
  media.py      fontes e destinos, frames de áudio, STT/TTS (Whisper, Piper)
  cli.py        o comando simple-phone
```

Cada camada só importa as de baixo: o `core` não conhece asyncio, e `phone.py` e `call.py` não conhecem a CLI.

## Threads

O PJSUA2 roda com `mainThreadOnly`. Uma thread do engine (`core/engine.py`) cria a biblioteca, roda `libHandleEvents()` e executa todos os comandos. Nenhuma outra thread chama o PJSUA2.

- **Comandos:** `engine.submit(funcao, *args)` devolve um `Future`. O `AsyncPhone._run` o adapta ao asyncio, e `pj.Error` vira `PhoneError`.
- **Eventos:** o core monta eventos tipados (`events.py`) e os entrega aos listeners do engine, na thread do engine. O hub (`_Hub` em `phone.py`) passa cada evento ao event loop com `call_soon_threadsafe`.
- **Callbacks de mídia** (`onFrameReceived`, `onFrameRequested`) rodam numa thread do PJMEDIA. Só mexem em buffers Python, nunca no PJSUA2, e nunca deixam exceção subir para o C++.

## Roteamento

Todo evento traz `account_id`, `ref` (o id da chamada) e `call_id` (o Call-ID do SIP). O hub:

- Acha o `AsyncPhone` pelo `account_id` e a `Call` pela `ref`. Depois preenche `event.phone` e `event.call` com `dataclasses.replace`.
- Registra a `Call` de saída (`acquire`) antes de o core discar, para que os primeiros eventos já tenham destino.
- Guarda as mensagens SIP de um INVITE recebido (`early`) até o PJSUA criar a chamada.
- Guarda as últimas 100 chamadas encerradas (`ended`) para o BYE e o 200 que são logados depois do DISCONNECTED.

O trace SIP vem do log do PJSIP (nível 4). O `LogWriter` interpreta cada mensagem (`core/sip.py`), e `Endpoint.sip_identity` decide a que conta e chamada ela pertence. O mesmo parser lê o estado de BLF dos NOTIFY de dialog-event, porque o PJSUA2 não expõe o dialog-info.

## Ciclo de vida dos objetos

Quebrar qualquer uma destas regras derruba o processo:

- **O objeto PJSUA2 de uma chamada** é liberado dentro do callback DISCONNECTED (`Endpoint.finish`). Liberá-lo depois faz o `~Call` limpar o slot que uma chamada nova pode já estar usando. A API nunca guarda objetos nativos: `Call._do` busca a chamada do core pela `ref`, na thread do engine.
- **REFER e Replaces** precisam de um novo objeto `Call` para a chamada nova (`Endpoint.child_call`). Sem isso, duas chamadas dividem um objeto, e apagá-lo deixa um ponteiro solto.
- **Ports e buddies com código Python** são apagados explicitamente (`destroy_native`) enquanto o objeto Python existe. Um port pode estar dentro de um callback de mídia. O `Account.shutdown()` apagaria o `Buddy` uma segunda vez.
- **`info = call.getInfo()`** precisa ficar numa variável enquanto `info.media` é usado.

## Build

O `scripts/build_pjsip.sh` compila o PJSIP 2.17 como bibliotecas estáticas PIC, com os limites de `packaging/config_site.h` (64 chamadas, players e gravadores), sem vídeo e, por padrão, sem TLS. Depois gera o wrapper SWIG em `_native/`. O `setup.py` compila esse wrapper e o linka às bibliotecas estáticas, então o wheel só precisa da `libasound.so.2` do sistema.
