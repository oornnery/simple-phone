# Development

*[Português](development.pt-BR.md)*

## Requirements

Python 3.14, uv ≥ 0.13.7, git, a C/C++ compiler, make, pkg-config, SWIG ≥ 4.2 and the ALSA headers. Add the OpenSSL headers for TLS. Docker is optional; you need it only for the tests against Asterisk.

```bash
sudo apt-get install build-essential git pkg-config swig libasound2-dev   # Ubuntu 24.04
sudo apt-get install libssl-dev                                           # for PJSIP_TLS=1
```

## Scripts

| Command | What it does |
|---|---|
| `bash scripts/dev.sh` | Builds PJSIP if needed, then `uv sync --locked --all-extras` |
| `bash scripts/check.sh` | Ruff (lint and format), ty, version metadata, shell syntax, unit tests |
| `bash scripts/test.sh` | Unit tests (`tests/test_*.py`) |
| `bash scripts/test.sh --native` | PJSUA2 integration checks on localhost (`tests/native_checks.py`) |
| `bash scripts/asterisk.sh` | Starts Asterisk in Docker on 127.0.0.1:5060 (`stop` removes it) |
| `bash scripts/build.sh` | Builds a wheel into `dist/` |
| `.venv/bin/python scripts/check_package.py` | Checks wheel contents, metadata and the command entry point |
| `bash scripts/build_pjsip.sh` | Rebuilds PJSIP and the SWIG wrapper (`--check` only validates) |

The unit tests make real calls between accounts on 127.0.0.1. Nothing leaves the machine.

## Tests against Asterisk

`tests/asterisk/` holds the configuration of a small PBX: extensions 1001 and 1002 (password `secret`), an echo test at 600, DTMF at 601, busy at 602, hints for BLF, and a mailbox for MWI.

```bash
bash scripts/asterisk.sh
ASTERISK_HOST=127.0.0.1 .venv/bin/python -m unittest discover -s tests -t tests -p 'test_asterisk.py' -v
bash scripts/asterisk.sh stop
```

Asterisk runs on the host network, so SIP and RTP need no port mapping. `ASTERISK_IMAGE` overrides the image, which is pinned by digest.

## Native build

| Variable | Default | Use |
|---|---|---|
| `PJSIP_VERSION` | `2.17` | Tag to build |
| `PJSIP_PREFIX` | `build/pjsip` | Where the static libraries go |
| `PJSIP_SRC` | `build/pjproject` | PJPROJECT checkout |
| `PJSIP_TLS` | `0` | `1` builds with OpenSSL |
| `PJSIP_JOBS` | `nproc` | Parallel make jobs |

Use the same `PJSIP_TLS` for `dev.sh` and `build.sh`. `--check` compares version, limits, TLS and the wrapper, and never reuses a prefix that does not match.

The binding is PJSIP's `pjsua2.i` plus `packaging/pjsua2_extra.i`, which adds what PJSUA2 does not expose (today `setCompactForm`). After changing that file, run `bash scripts/build_pjsip.sh` and `bash scripts/dev.sh`.

Only wheels are distributed. A source build needs `scripts/build_pjsip.sh` first, and a plain sdist cannot run it. Always build with `--wheel`; `build.sh` already does.

## Windows

Visual Studio 2022 Build Tools with the C++ workload, git, uv, and SWIG (`uv tool install swig`). In PowerShell:

```powershell
pwsh scripts/build_pjsip.ps1          # PJSIP (MSBuild, Release-Dynamic) and the SWIG wrapper
uv build --wheel                      # setup.py links build\pjproject's .lib files
```

`PJSIP_SRC` points at another PJPROJECT checkout, `SWIG` at another swig.exe. The Windows build has PJSIP's built-in codecs only (no opus) and no TLS.

## CI

`.github/workflows/ci.yml` runs on pushes to `main` and on pull requests, in one job:

1. Builds PJSIP. The libraries and the SWIG wrapper are cached by the hash of `scripts/build_pjsip.sh`, `packaging/config_site.h` and `packaging/pjsua2_extra.i`.
2. Runs `check.sh`, which covers ruff, ty and the unit tests, then the native checks.
3. Starts Asterisk with `scripts/asterisk.sh` and runs `tests/test_asterisk.py` against it.

To spend Actions minutes only on runs that pass:

- `bash scripts/ci.sh` runs the same steps on this machine; `--wheel` also builds and checks the wheel. The Asterisk tests need Docker.
- `.githooks/pre-push` runs it before every `git push`. `scripts/dev.sh` turns it on (`git config core.hooksPath .githooks`). When a push changes only text (`*.md`, `docs/`, `examples/api/`), the hook runs `check.sh` only. Skip it once with `git push --no-verify`.
- CI skips pushes that change only text, and a newer push cancels the run in progress.
- [act](https://github.com/nektos/act) can run the workflow itself in Docker, if you want the exact GitHub steps; it downloads a runner image of several GB.

## Releases

`.github/workflows/release.yml` runs on a `v*` tag:

1. The tag must equal `v` + the version in `pyproject.toml`.
2. cibuildwheel builds `manylinux_2_28` wheels, then runs the unit and native tests against each one.
3. The wheels are published to PyPI with trusted publishing, so no token is stored.

One-time setup on PyPI: add a trusted publisher (Account → Publishing) with this repository, the workflow `release.yml` and the environment `pypi`. On GitHub, create the environment `pypi`.

To release:

1. Bump `version` in `pyproject.toml` and `__version__` in `src/simple_phone/version.py`. `check_package.py --metadata` fails if they differ.
2. Run `uv lock`, so `uv sync --locked` accepts the new version.
   Then `bash scripts/ci.sh --wheel`: the release builds the wheels without running CI again.
3. Add the version to `CHANGELOG.md` and commit as `chore: release X.Y.Z`.
4. Tag and push:

   ```bash
   git tag vX.Y.Z && git push origin main vX.Y.Z
   ```

PyPI never accepts the same version twice. To try a release first, build locally with `uvx cibuildwheel --platform linux` (needs Docker) and upload to TestPyPI: `uv publish --publish-url https://test.pypi.org/legacy/ wheelhouse/*`.
