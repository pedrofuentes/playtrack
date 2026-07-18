# Contributing to PlayTrack

Thanks for helping improve PlayTrack. The most useful contributions are focused,
reproducible, and preserve the app's local-first data boundaries.

## Before you start

- Use the [bug report form](https://github.com/pedrofuentes/playtrack/issues/new?template=bug_report.yml) for defects.
- Use the [feature request form](https://github.com/pedrofuentes/playtrack/issues/new?template=feature_request.yml) for product proposals.
- For security issues, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
- For substantial behavior or UI changes, open an issue before investing in an implementation.

Do not attach footage unless you have the right to share it. A minimal synthetic clip,
precise frame range, source dimensions/fps, and hardware details are usually more useful.

## Development setup

Follow [README.md](README.md) for platform setup. The standard local gates are:

```bash
cd backend
uv sync --extra dev
uv run --extra dev pytest -m "not integration"

cd ../frontend
npm install
npm test
npm run typecheck
npm run build

cd ..
node website/test-site.mjs
```

Unmarked backend tests must stay independent of network access, model weights, and GPUs.
Integration tests must skip cleanly when their checkpoint or device is unavailable.

## Pull requests

1. Keep the change scoped and explain the user-visible outcome.
2. Add a failing test first for behavior changes, then implement the smallest fix.
3. Preserve HTTP payloads, WebSocket protocols, smoothing compatibility keys, and user-data boundaries unless an approved change explicitly replaces them.
4. Report every verification command actually run and any hardware-dependent test not run.
5. Never commit `data/`, `exports/`, checkpoints, model weights, source footage, or generated caches.

Use imperative commit subjects. Milestone work uses `M<n>: summary`; normal fixes and
features use a plain imperative subject.

## Licensing

Contributions to PlayTrack are accepted under the repository's [MIT License](LICENSE).
Third-party dependencies and model weights retain their upstream terms. In particular,
optional LocateAnything weights are non-commercial under NVIDIA's research license and
must not be redistributed with PlayTrack.
