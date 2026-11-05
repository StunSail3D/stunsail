# ADR 0004: Deployment profiles and security boundary

- Status: Accepted for Phase 0
- Date: 2026-11-04

## Context

StunSail must be simple on one printer host but later permit Agents on remote
hosts. The initial product is local-network-only and must not expose Moonraker
to the public internet.

## Decision

- Standalone (Core + Agent) is the default; Agent-only is a supported profile.
- Run Core and Agent as dedicated non-root service users with only required
  filesystem/network permissions.
- Keep mutable data under `/var/lib/stunsail`, configuration under
  `/etc/stunsail`, and transient files under `/var/cache/stunsail`.
- Pass secrets through protected files or service-manager environment, not
  committed configs, command-line arguments, or logs.
- Bind the API to loopback by default. LAN exposure requires explicit
  configuration and firewall controls on a trusted network.
- Agent-only initiates authenticated TLS connections to Core. Do not expose
  Moonraker or Core to the public internet.
- Defer the exact local Core-Agent transport until the communication contract is
  implemented; preserve the same logical event contract across deployment modes.

## Consequences

No phase-0 configuration enables remote access. The production installer must
enforce ownership and permissions and must preserve data on uninstall by
default. Threat modeling must be revisited before remote access or multi-user
features.
