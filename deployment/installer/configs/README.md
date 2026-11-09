# Deployment profiles

The example profiles describe the intended service layout. The Agent currently
reads the `deployment_mode` and `agent` sections; installer and Core profile
settings are not yet provisioned automatically.

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

## Distributed Agent configuration

The Agent currently handles one Moonraker instance per process. For several
printers, run one Agent per instance, on the same host or different hosts.
Register a distinct Agent and printer in Settings for each, and provide each
process a separate configuration, SQLite buffer and `STUNSAIL_AGENT_TOKEN`.
Never share a buffer or identity between Agents. Existing buffers are bound to
their Agent ID; to change identity, use a new buffer rather than reusing it.

Set `deployment_mode: agent_only` and `agent.core_url` to the Core's HTTPS
origin. The HTTPS endpoint must be provisioned separately (for example with a
TLS reverse proxy on a trusted network); StunSail does not yet install or
configure that proxy. Certificates and hostnames are verified. If necessary,
set `agent.core_ca_file` to a PEM CA bundle readable by the Agent. A custom
bundle replaces the default trust store for Core connections. Missing or
invalid CA files prevent startup. Protect the Agent token as described above.

Existing configuration files without `deployment_mode` remain compatible and
may use HTTP. Do not send Agent credentials over untrusted networks; choose
Agent-only mode and HTTPS for remote connections. Standalone mode may use
loopback HTTP. A second printer registered against the same Agent is rejected:
the current protocol cannot distinguish their telemetry. Existing ambiguous
registrations prevent sync and live status with a 409 error rather than
attributing data to the wrong printer. Back up the database and resolve such
registrations before resuming; there is not yet a printer reassignment UI.
