# Deployment profiles

These are illustrative Phase 0 profiles, not yet accepted by a runtime
configuration parser. The profile names and concepts are stable; exact key names
remain implementation choices.

| Profile | Services | Data paths | Service identities |
| --- | --- | --- | --- |
| Standalone (default) | Core, Agent, UI/API | `/var/lib/stunsail/core`, `/var/lib/stunsail/agent` | `stunsail-core`, `stunsail-agent` |
| Agent-only | Agent | `/var/lib/stunsail/agent` | `stunsail-agent` |

Configuration belongs in `/etc/stunsail` and must be readable only by the
relevant service account (target mode `0640`). Secret values are injected through
the service manager or protected files (target mode `0600`); never put actual
credentials in these examples, command-line arguments, logs, or source control.
Core and Agent data directories are owned by their respective service users with
least-privilege access. Logs go to standard output/error and are collected by
systemd journald. Transient files belong under `/var/cache/stunsail`.

The API binds to loopback by default. LAN access requires an explicit bind
configuration and firewall policy on a trusted local network. Do not port
forward StunSail or expose Moonraker to the public internet. Agent-only
connections are outbound TLS to Core; the co-located Core/Agent transport is an
open technical decision to settle before implementing communication.

Both deployment methods must share configuration validation and service setup.
Upgrades must preserve data and printer configuration. Uninstall preserves data
unless the operator explicitly requests its removal.
