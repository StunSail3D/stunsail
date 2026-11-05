# Operations baseline

This is the Phase 0 operating contract for the future services. The installer
and runtime implementation must make these paths and behaviors real before a
release.

## Logging and diagnostics

- Emit structured logs to standard output/error; systemd captures them in
  journald. Include service, version, timestamp, severity, and correlation or
  event ID where applicable.
- Redact credentials, tokens, private keys, and sensitive configuration. Do not
  log full Moonraker credentials or license secrets.
- Expose explicit health/version/capability information and distinguish
  unavailable Moonraker/Core, stale data, and partial telemetry from healthy
  operation.
- A diagnostics bundle should contain versions, sanitized configuration,
  service status, recent redacted logs, migration state, queue depth, and disk
  health. Require review before sharing it; exclude credentials, database
  contents, and raw printer configuration by default.

## Backup and restore

- Back up Core database, configuration, and required license material as
  applicable; protect backup permissions and store it separately from the host.
- Use SQLite's online backup API or a coordinated service stop/checkpoint
  procedure. Do not copy a live SQLite database file without accounting for WAL
  state.
- Back up before upgrades and retain a known-good copy until validation passes.
- Test restore on a clean installation, including configuration and service
  ownership; backup creation alone is not a restore test.
- Agent buffers are durable operational data and need a documented retention
  and recovery policy before distributed sync ships.

## Upgrade, rollback, and uninstall

- Updates are notified but user-initiated in the initial release.
- Verify release/package integrity, stop or quiesce writers, create a backup,
  apply reviewed migrations, then start and health-check services.
- On failed upgrade, stop services and restore the pre-upgrade backup and
  matching application version. Do not assume a downgrade migration can recover
  data destroyed by a forward migration.
- Preserve user data and printer configuration on uninstall unless explicit
  data removal is requested.

## Service baseline

Standalone runs `stunsail-core` and `stunsail-agent` Linux systemd services;
Agent-only runs `stunsail-agent`. Services run as dedicated non-root identities.
Core and Agent own separate subdirectories under `/var/lib/stunsail`; config is
under `/etc/stunsail`; logs use journald.
