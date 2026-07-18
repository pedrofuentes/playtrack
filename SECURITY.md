# Security policy

## Supported version

PlayTrack is pre-1.0 software. Security fixes target the latest commit on `main`; older
commits and local modifications are not maintained as separate supported releases.

## Reporting a vulnerability

Please do not open a public issue for a vulnerability. Use GitHub's private
[security advisory form](https://github.com/pedrofuentes/playtrack/security/advisories/new)
and include the affected commit, impact, reproduction steps, and any suggested mitigation.
Avoid including private video files, model credentials, tokens, or personal data.

You should receive an initial response within seven days. A fix timeline depends on
severity and whether the issue is in PlayTrack or an upstream model/runtime.

## Deployment boundary

PlayTrack is designed as a single-user local application. It binds to `127.0.0.1` by
default and has no authentication. Host and origin checks reduce cross-site browser
requests, but changing `PLAYTRACK_HOST` to `0.0.0.0` does not make the app safe for
public internet exposure. Keep it behind a trusted local network until authentication
and path-registration restrictions are implemented.
