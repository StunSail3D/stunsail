# Phase 0 security and privacy assumptions

## Scope and trust boundaries

- StunSail is self-hosted and local-first. Core/API is loopback-bound by default;
  optional LAN exposure is for a trusted local network only.
- Moonraker remains on the printer host's local network and is never exposed to
  the public internet by StunSail.
- Explicit Agent-only mode requires outbound HTTPS to Core, with certificate and
  hostname verification and an individual revocable Agent credential.
  Configurations without a deployment mode remain compatible with HTTP; they
  should not be used over untrusted networks.
- Core is authoritative for state-changing operations. UI visibility is not
  authorization; Core must validate and authorize all printer-control requests.
- Local filesystem users, host administrators, and the Linux kernel are trusted.
  A compromised host is outside the protection boundary.

## Required controls

- Dedicated non-root service users and least-privilege filesystem permissions.
- No secrets in source control, sample configuration, command arguments, or
  ordinary logs. Restrict secrets/configuration to relevant service accounts.
- Validate all external input; use authenticated transport, event IDs, sequence
  numbers, and idempotency keys to resist replay and duplicate effects.
- Keep local operation functional without a cloud account or permanent internet.
- Export and deletion behavior must be documented. Telemetry policy must be
  transparent; no mandatory cloud telemetry.
- Clearly distinguish estimated from measured energy and expose data quality and
  gaps.

## Explicitly deferred

Public-facing hosting, secure remote access, multi-user accounts, role-based
access, license activation workflows, and printer-control endpoints are not
implemented in Phase 0. A detailed threat model and security review are required
before those capabilities ship.
