# Examples

| Path | Contents |
|---|---|
| [api/](api/README.md) | Numbered scripts, from a first call to an IVR. Each one runs on its own, on localhost |
| [accounts/](accounts/) | JSON profiles: `local.json` and `local-b.json` (localhost), `pbx.json` (a template for your PBX) |

With a profile, the command line works the same way:

```bash
simple-phone doctor --profile examples/accounts/pbx.json
```
