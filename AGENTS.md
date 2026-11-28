# AGENTS.md

Notes for coding agents (and people) working in this repository.

## What this is

`simple-phone`: a SIP test phone. The Python package bundles PJSUA2 (PJSIP 2.17), compiled into the wheel, and adds an async API (`AsyncPhone`, `Call`, typed events) and a command (`simple-phone`). It targets Linux x86_64 and Windows x64, Python 3.11 to 3.15. Keep the code valid on 3.11: ruff targets py311, and newer APIs need a version check. The license is GPL-2.0-or-later, because PJSIP is linked in.

Read [docs/architecture.md](docs/architecture.md) before changing anything under `src/simple_phone/core/`. The public API is described in [docs/api.md](docs/api.md) and the command in [docs/cli.md](docs/cli.md); update them, and their `.pt-BR.md` copies, with the code.

## Layout

| Path | Contents |
|---|---|
| `src/simple_phone/core/` | PJSUA2 on one engine thread. Synchronous, no asyncio |
| `src/simple_phone/*.py` | Public API (`phone.py`, `call.py`, `events.py`, `models.py`, `media.py`, `sync.py`) and the CLI (`cli.py`) |
| `src/simple_phone/_native/` | Generated SWIG binding. Never edit it; it is rebuilt by `scripts/build_pjsip.sh` |
| `tests/` | `test_*.py` unit tests (real calls on 127.0.0.1), `native_checks.py`, `test_asterisk.py` plus `tests/asterisk/` |
| `examples/api/` | Runnable examples, each on one machine without a PBX |
| `scripts/` | Setup, checks, tests, build, Asterisk |
| `packaging/config_site.h` | Native limits compiled into PJSIP |
| `packaging/pjsua2_extra.i` | Our additions to the SWIG binding (e.g. `setCompactForm`), appended to `pjsua2.i` by `build_pjsip.sh` |
| `packages/` | Ignored by git. Separate packages built on the core |

## Commands

```bash
bash scripts/dev.sh                 # first time, or after changing dependencies
bash scripts/check.sh               # ruff, ty, metadata, unit tests: run before every commit
bash scripts/ci.sh                  # what CI runs; the pre-push hook runs it for you
bash scripts/ci-windows.sh          # from WSL: the Windows wheel and its tests, on Windows
bash scripts/test.sh --native       # PJSUA2 integration on localhost
bash scripts/asterisk.sh && ASTERISK_HOST=127.0.0.1 .venv/bin/python -m unittest discover -s tests -t tests -p 'test_asterisk.py'
```

Run Python with `.venv/bin/python`, not `uv run`. `uv run` may rebuild the native extension, which takes minutes.

## Rules

- **Only the engine thread calls PJSUA2.** From the API, use `phone._run(function, *args)` or `call._do(core_function, *args)`. Never keep a native object on the asyncio side; look it up by `ref` on the engine thread.
- **Native lifetimes are the usual cause of crashes.** Drop a call in its DISCONNECTED callback. Give REFER and Replaces a child `Call`. Delete ports and buddies with `destroy_native`. Keep `getInfo()` results in a variable while you read their vectors.
- **Events are dataclasses** in `events.py`. The core creates them, and the hub fills `phone` and `call`. A new PJSUA2 callback means a new event type, emitted from the core. Add one only when something uses it.
- **One way to do each thing.** Media is named by the strings of `Settings.media` (`silent`, `echo`, `wav`, `mic`). Handlers are `@phone.on(Type)`. The password is the `password=` argument.
- **Keep `__init__.py` files to imports.** Code goes in regular modules.
- **Keep the code simple.** Prefer the stdlib or what the project already has. Add no abstraction before a second caller needs it. The CLI is one file on argparse and rich.
- **Tests make real calls.** Put new behavior in `tests/test_api.py` with two local accounts on one endpoint. Use `test_asterisk.py` when the behavior needs a PBX.
- **Commits** use Conventional Commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `ci:`, `chore:`), are small, and leave `check.sh` green.

## Gotchas

- PJSUA sends out-of-dialog requests (`phone.request`, `options`) without credentials, so a PBX may answer 401.
- A PJSUA buddy holds one subscription: presence or dialog (BLF), not both.
- PJSUA offers `m=text` on every call by default. The core turns it off unless `Settings.text` is set.
- `hold()` and `unhold()` wait for the re-INVITE answer. Calling `unhold()` before that fails with `PJ_EINVALIDOP`.
- A REGISTER 401 or 407 that reaches `onRegState` is final. PJSUA answers the challenge itself.
- SWIG returns a field whose C type it does not know (e.g. `AudioDevInfo.id`, a `pjmedia_aud_dev_index`) as an opaque pointer. Read only fields that come back as Python values. CI has no sound card: `tests/test_cli.py` runs the audio-device paths on ALSA null devices.

## Windows

`scripts/build_pjsip.ps1` builds PJSIP with MSBuild (`Release-Dynamic`: /MD, like Python) and the SWIG wrapper; `setup.py` links the `.lib` files from `PJSIP_SRC` (default `build\pjproject`). cibuildwheel does it on `windows-2022` in `release.yml`.

- Codecs: only PJSIP's built-in ones (no opus). No TLS.
- The tests run as on Linux; the ALSA sound-card tests are skipped.
- WSL with `networkingMode=mirrored` makes Windows refuse UDP ports from 46000 up: tests that use them fail on such a host, not on CI.
