# Security Policy

## Supported versions

Only the latest public release receives security fixes.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. If
that feature is unavailable, open a minimal issue asking for a private contact
channel without including exploit details, credentials, model files, logs, or
personal paths.

Do not publish:

- passwords, one-time codes, access tokens, or API keys;
- Bambu Studio access codes or account credentials;
- private models or sliced G-code;
- unredacted logs that contain usernames or filesystem paths.

## Local service boundary

PrintFarm Assistant exposes an HTTP service on `127.0.0.1` only. The service
checks local `Origin` and `Host` values to block ordinary cross-site requests
and DNS-rebinding attempts. It is not designed to be exposed to a LAN or the
public internet.

## Downloads

Release assets are published through this GitHub repository. Verify the
published SHA-256 checksum before running an installer. Builds are currently
unsigned; Windows may therefore show an unknown-publisher warning.

## Protected core

The installed application verifies `protected_core.exe` against
`protected_core.sha256` before using multicolor planning. Do not replace or
re-pack that file separately from an official installer. A modified or missing
component is rejected rather than executed.
