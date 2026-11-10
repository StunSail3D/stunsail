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

- `deployment/installer/backup_installation.py` backs up an installer-managed
  host's configuration and Core/Agent databases into a new private directory.
  Follow the maintenance-window and scope requirements in the
  [installer documentation](../../deployment/installer/README.md#sqlite-recovery).
  `verify_backup.py` checks format 2 and 3 backups for missing files, corruption
  and SQLite integrity without modifying them. New format 3 backups also
  record a release file fingerprint; `verify_release.py` compares it with a
  preserved release, excluding the virtual environment and Python caches.
  Format 2 backups lack that fingerprint. These checks do not authenticate
  the backup; protect the manifest independently.
  The experimental `maintenance_backup.py` can disable and stop managed local
  services before backing up; it leaves them disabled and does not coordinate
  external writers or automatically resume services.
  It does not back up the runtime, other hosts or external TLS infrastructure.
  An experimental `apply_restore.py` performs an offline host restore while
  retaining original directories and a new safety backup; it requires manual
  coordination, has non-atomic multi-directory swaps and has not been
  validated with real systemd or on target devices. It does not automate
  rollback.
- `deployment/installer/sqlite_snapshot.py` can create a consistent snapshot of
  an existing Core or Agent SQLite database, including committed WAL data, and
  checks the resulting database's integrity. It uses SQLite's online backup API.
  Supply a destination that does not exist in a trusted, access-restricted
  directory; the tool creates the file with owner-only permissions on POSIX.
- For example, with Python 3.11+:

  ```sh
  python3 deployment/installer/sqlite_snapshot.py /path/to/core.db /secure/backup/core.db
  python3 deployment/installer/sqlite_snapshot.py /secure/backup/core.db /secure/restore/core.db
  ```

- This copies a database only. Back up configuration, credentials and any
  separate Agent buffers securely as well; their snapshots are not automatically
  coordinated. Never publish backup files: they may contain sensitive data.
  To restore, stop the relevant service and preserve its current database,
  including any WAL/SHM files, before an operator installs the restored file.
  Use the matching application version and migrations. An Agent buffer restore
  may replay old data; keep its original identity and do not run two copies.
  Restoring an older Core database loses changes made after that snapshot.
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

- Experimental `rehearse_upgrade.py` backs up stopped services and tests
  candidate Core migrations, readiness and admin authentication, plus Agent
  buffer compatibility, on separate copies; it does not activate the
  release or migrate live data. Follow the installer documentation and
  coordinate all writers. This does not substitute for target validation,
  application health checks, a live upgrade or rollback.
- Experimental `apply_upgrade.py` performs that rehearsal, preserves the
  original release and Core directory, then switches to the candidate with
  services stopped. The database and release switches are not atomic together.
  A guarded in-process Core recovery is attempted for caught switch errors
  before the link changes; crash recovery, post-start rollback and validation
  with real systemd remain outstanding.
- Experimental `rollback_upgrade.py` restores a pre-upgrade Core snapshot and
  matching release after a new safety backup and offline compatibility checks.
  It does not restore Agent buffers or remote hosts, and Core changes after
  the old snapshot are lost from the active database. It is not an automatic
  crash recovery mechanism and has not been validated with real systemd.
- Experimental `check_running.py` checks local unit state and standalone Core
  readiness and unauthenticated access after an operator starts services. It does not
  check Agent sync, printer connectivity or remote Core, and has not been
  validated against real systemd.
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
