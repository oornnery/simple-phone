# Examples

| Path | Contents |
|---|---|
| [api/](api/README.md) | Numbered scripts, from a first call to an IVR. Each one runs on its own, on localhost |
| [accounts/](accounts/) | JSON profiles: `pbx.json` and `pbx-full.json` (a PBX), `trunk.json` (IP trunk), `nat.json` (behind NAT), `answer-echo.json` (test answerer), `local.json` and `local-b.json` (this machine). See [docs/cli.md](../docs/cli.md#profiles) |

With a profile, the command line works the same way:

```bash
simple-phone doctor --profile examples/accounts/pbx.json
```
