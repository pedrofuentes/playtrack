# PlayTrack Dev Network Mode Design

**Date:** 2026-07-21  
**Status:** Approved for implementation planning

## Goal

Make the Unix development launcher usable from another device on the local network without making unauthenticated network exposure the default. `scripts/dev.sh` remains localhost-only unless the operator explicitly selects network mode.

## Command Interface

The launcher supports these invocations:

```bash
scripts/dev.sh
scripts/dev.sh --network
scripts/dev.sh --help
```

- With no arguments, FastAPI and Vite bind to `127.0.0.1`.
- With `--network`, FastAPI and Vite bind to `0.0.0.0`.
- With `--help`, the launcher prints concise usage and exits successfully without starting either process.
- Unknown arguments print usage to standard error and exit nonzero without starting either process.

`PLAYTRACK_HOST` remains supported for backward compatibility. When `--network` is supplied, it takes precedence and selects `0.0.0.0`. Without the flag, an explicit `PLAYTRACK_HOST` continues to control the FastAPI and Vite bind host. The default remains `127.0.0.1`.

## Process Architecture

The launcher continues to own two child processes and shut down the survivor if either child stops:

- FastAPI: `uvicorn app.main:app --reload --host <bind-host> --port 8000`
- Vite: `npm run dev -- --host <bind-host> --port 5173`

Vite's API and WebSocket proxy targets remain `127.0.0.1:8000`. Those are server-side proxy connections on the PlayTrack machine, so they do not need a LAN address even when browsers connect to Vite over the network.

The backend's existing request-boundary policy already accepts private-network host addresses and same-origin requests. This change does not add authentication, broaden path-registration authorization, or change CORS/security middleware.

## Operator Output

Local mode prints the existing localhost URLs.

Network mode prints:

- the local frontend URL
- a network-access hint using the machine's detected private LAN address when one can be determined
- a fallback instruction to open `http://<this-machine-ip>:5173` when automatic detection is unavailable
- a prominent warning that network mode has no authentication and should be used only on a trusted local network

LAN address discovery is informational only. Failure to discover an address must not prevent either server from starting. The launcher must not depend on network access, DNS, or a new package.

## Documentation

`README.md` and `AGENTS.md` document the new `--network` invocation, the localhost default, both exposed development ports, and the lack of authentication. The existing `PLAYTRACK_HOST` configuration row remains accurate and notes that the command-line flag is the preferred development interface.

Windows launchers are out of scope. `run.ps1` already exposes the single-process production app through `PLAYTRACK_HOST`, while `dev.ps1` retains its existing localhost development behavior.

## Testing

The weight-free backend suite extends its Unix launcher source checks to verify:

- default localhost binding
- `--network`, `--help`, and unknown-argument handling
- the same resolved bind host is passed to uvicorn and Vite
- explicit Vite port 5173 and FastAPI port 8000
- the trusted-network/no-authentication warning
- preservation of `PLAYTRACK_HOST`

A focused shell integration test runs the launcher with stub `uv`, `npm`, and child-process commands so it can validate argument parsing, emitted commands, usage, warnings, and cleanup without opening sockets or starting real servers. Tests remain independent of network access, model weights, and GPUs.

Final verification runs the backend weight-free suite and shell syntax validation, then manually starts network mode long enough to confirm both listeners bind to all interfaces and the frontend asset/API proxy respond from the PlayTrack machine. It does not alter or delete live `data/`.

## Safety and Compatibility

- Localhost remains the default.
- Network exposure requires an explicit flag or the existing explicit environment variable.
- No authentication is implied; the launcher states this clearly.
- Existing cleanup/trap behavior is preserved.
- Existing users of `PLAYTRACK_HOST` are not broken.
- No frontend production build, PWA caching, backend API, or persisted-data format changes.

## Out of Scope

- Authentication or authorization for LAN access
- TLS certificates or HTTPS development serving
- Automatic firewall configuration
- Router configuration, port forwarding, or internet exposure
- Windows development-launcher changes
- Production deployment behavior
