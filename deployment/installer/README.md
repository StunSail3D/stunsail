# Installer

An experimental first-install command is available, but has not yet been
validated on a target device or in an isolated systemd environment. Do not use
it for a production installation yet. Upgrades and uninstall are not complete.
Example Standalone and Agent-only profiles are in `configs/`.

## Experimental fresh system installation

`install_fresh.py` combines a trusted extracted release, a root-owned bundle
created by `configure.py`, and the service templates. It is intentionally
limited to a **new**, empty installation; it refuses existing StunSail
directories, service accounts, or conflicting units. It requires root, an
active systemd manager, `uv`, the system account tools, internet access for
locked dependencies, and a passing platform preflight. Run the preflight
separately first and verify Moonraker connectivity. The release must be an
allowlisted Debian payload, not a development checkout.

The explicit invocation is:

```sh
sudo python3 /usr/share/stunsail/source/deployment/installer/guided_install.py \
  /usr/share/stunsail/source /root/stunsail-setup
```

The guided command first creates a private configuration bundle, then asks
for an explicit `INSTALL` confirmation before calling the shared fresh-install
workflow. Its new bundle must be in an existing root-owned directory whose
ancestors are not group/world writable or symlinked. Cancelling leaves the
bundle in place without installing services; protect it or remove it securely.
For standalone, leave the Agent token empty when prompted.

Alternatively, after preparing a bundle separately:

```sh
sudo python3 /usr/share/stunsail/source/deployment/installer/install_fresh.py \
  /usr/share/stunsail/source /secure/root-owned-bundle --confirm-fresh-install
```

For standalone, prepare the bundle as root with an empty Agent token. The
installer creates dedicated accounts, prepares a runtime in its final location,
migrates a new Core database as the Core user, starts and checks Core, registers
the Agent, then starts and enables the services. The one-time Agent token is
also saved in the original bundle: keep it private. Afterward, use the Core
admin token from the bundle in Settings and **register a printer** for the
Agent. A running service alone does not prove Moonraker or synchronization is
healthy.

Agent-only requires an already registered Agent token and an HTTPS Core URL.
An optional supplied CA trust bundle is validated and copied as a publicly
readable certificate file; it must not contain a private key. Neither mode
provisions a TLS endpoint: remote Agents need
a separately configured trusted HTTPS endpoint. The Core unit listens only on
loopback, and does not expose Moonraker.

The installer does not overwrite existing data or attempt automatic rollback.
An error can leave accounts, files, a database, or running services behind. Its
failure message requires inspecting those resources before any recovery; do not
blindly rerun it or delete data. Do not use this command for an upgrade, an
existing installation, or additional Agents. Service activation and filesystem
ownership still require validation in a genuinely isolated systemd environment
and on the supported target images.

## Experimental additional Agents

The experimental `add_agent.py` adds a separately registered Agent to an
existing installer-managed host without replacing other Agent configuration
or buffers. It still requires real systemd and target-device validation; do
not use it for production yet.

1. In Core Settings, register a **new unique Agent ID**, save its one-time
   token securely, and register a printer for that Agent.
2. As root, prepare a new private bundle using `configure.py`. Enter that
   Agent ID and token. Choose `standalone` for a Core on this host
   (`http://127.0.0.1:8000`), or `agent_only` for a remote HTTPS Core.
   The generated standalone bundle also contains a new `core.env`; it is
   **not installed or used** by this command. The existing Core admin token
   remains unchanged. Protect the whole bundle.
3. Run:

   ```sh
   sudo python3 /usr/share/stunsail/source/deployment/installer/add_agent.py \
     /root/new-agent-bundle --confirm-add-agent
   ```

The command refuses an existing Agent directory, data directory, active or
enabled instance, or an unexpected service template. It creates a separate
buffer directory and starts and enables only the new instance. It does not
register the Agent or printer and service status does not prove synchronization:
verify Moonraker connectivity and Core sync afterward. If it fails, partial
files or a running service may remain; inspect them before retrying. Do not
remove another Agent's files. For other hosts, use a separate installation and
HTTPS with certificate verification.

## Guided configuration preparation

`python3 deployment/installer/configure.py /secure/new-directory` prompts for
the deployment mode, unique Agent ID, Moonraker URL, Core URL, optional CA
bundle and Agent token. Agent-only mode requires HTTPS and an existing Agent
token. For a first standalone setup, leave the Agent token empty; register the
Agent in the UI after starting Core and add the resulting token to `agent.env`.

The command creates a new private directory with `agent.yaml`, `agent.env`
and, for standalone, `core.env` containing a newly generated admin token.
It refuses an existing destination and does not print the tokens. JSON syntax
in `agent.yaml` is valid YAML. Treat the whole directory as sensitive: the
environment files contain credentials. An interrupted or failed write can leave
a partial directory; inspect it securely before removing or retrying.
This only prepares configuration: it does not provision users, install files,
obtain certificates, register Agents, migrate databases or start services.

After a migrated standalone Core is running at `127.0.0.1:8000`, the bundle
owner can instead run
`python3 deployment/installer/register_local_agent.py /secure/new-directory`.
This registers the configured Agent and stores its token in the existing empty
`agent.env` without displaying it. The private directory must be owned by the
current user with mode 0700 and its configuration files must be owned by that
user with mode 0600. The command refuses to replace a non-empty token, does not
register a printer, install configuration or start services, and connects only
to the loopback Core without proxies or redirects.

If registration fails, Core may already have registered the Agent even if the
response was lost. Check Core before retrying and use the UI token reset if
needed. A `.agent.env.pending` file may contain the one-time token: inspect it
securely and retain it until recovery is complete. Never share credentials.

## Read-only preflight

`python3 deployment/installer/preflight.py --disk-path /` checks Linux
distribution metadata, 64-bit architecture, Python, selected system tools,
an active systemd manager, available disk space and root privileges. Pass
`--mode standalone` to test whether the local Core port is available.
Optionally pass `--moonraker-url http://PRINTER:7125` and
`--dependency-index-url https://pypi.org/simple/` to test the chosen services.
These network requests are made only when explicitly supplied. HTTPS uses
the system's default certificate validation. A nonzero exit indicates at
least one check failed.

The initial candidate policy is Debian 12, Raspberry Pi OS Bookworm, Ubuntu
24.04, or Armbian 26 with a Bookworm or Noble base, on x86-64 or AArch64.
Armbian image metadata and actual platform compatibility still need validation
on the target device. Port availability is only a point-in-time check.
The preflight does not detect all service conflicts, provision certificates,
authenticate to Moonraker, or install dependencies; a pass does not mean
installation is supported.

## SQLite recovery

`sqlite_snapshot.py` creates a consistent backup or restored copy in a new
file. See [operations](../../docs/architecture/operations.md#backup-and-restore)
for its scope, security requirements and limitations.

For an installer-managed system, `backup_installation.py` creates a private
backup of Core and Agent SQLite databases plus configuration. **Before running
it, stop Core and every Agent, prevent automatic restarts, and stop all other
writers; keep them stopped until the command exits.** Stop remote Agents too
if a coordinated fleet-wide recovery point is required. The tool checks local
systemd service state before and after copying, but cannot lock services or
detect other writers, so an operator must maintain the maintenance window.

For the experimental installer-managed system, the following command first
disables and stops all identified local Agents, then disables and stops Core
if present, and invokes the backup tool:

```sh
sudo python3 /usr/share/stunsail/source/deployment/installer/maintenance_backup.py \
  /root/stunsail-backup-1 --confirm-stop-services
```

Services **remain disabled and stopped**, including after a failure; the tool
does not automatically resume them or remember their prior enablement. Check
their state and explicitly restart/re-enable the desired services after
maintenance. Stop other writers and coordinate remote Agents separately. This
command does not uninstall anything and is not yet validated against a real
isolated systemd installation or target device. A failure can leave a partial
backup and some services disabled or stopped. Inspect both before continuing.

An experimental, data-preserving service removal command is also available:

```sh
sudo python3 /usr/share/stunsail/source/deployment/installer/remove_services.py \
  /root/stunsail-removal-backup --confirm-remove-services
```

It creates and verifies a new backup after disabling and stopping the managed
services, then removes only the verified installer-managed systemd unit files.
It refuses unexpected StunSail unit links, aliases, drop-ins and alternate
definitions in the standard systemd directories. It retains configuration,
databases, buffers, runtimes and service accounts; it does not uninstall the
Debian package or remove remote Agents, TLS configuration or credentials.
Coordinate remote Agents and all other writers throughout the maintenance
window. These checks do not lock out other processes or systemd changes.
The backup contains secrets and needs secure storage, and its checksums do
not authenticate it. A failure can leave services stopped, disabled or
partially removed; inspect service state and the backup before recovery.
This workflow is experimental and has not been validated with real systemd
or on target devices. It is not a complete uninstall.

Alternatively, after stopping and disabling the services yourself:

```sh
sudo python3 /usr/share/stunsail/source/deployment/installer/backup_installation.py \
  /root/stunsail-backup-1
```

The destination must be new and have root-owned, non-writable ancestors. The
tool refuses unknown data/configuration paths and external Agent CA files
rather than claiming they were backed up. It writes an integrity-checked
SQLite snapshot for each configured Agent and Core, protects files with mode
0600, records SHA-256 checksums, and writes `manifest.json` only after
successful checks. Verify the backup without changing it:

```sh
sudo python3 /usr/share/stunsail/source/deployment/installer/verify_backup.py \
  /root/stunsail-backup-1
```

Verification checks the expected file set, checksums, Agent identities,
referenced CA files, Core database path and SQLite integrity. It requires the
format 2 or 3 manifest; older format 1 backups have no checksums and cannot be
verified with this command. New backups use format 3, which also records a
fingerprint of the release files, excluding the virtual environment and
Python bytecode caches. To compare a preserved release with a format 3 backup:

```sh
sudo python3 /usr/share/stunsail/source/deployment/installer/verify_release.py \
  /root/stunsail-backup-1 /opt/stunsail/releases/initial
```

The release argument must be its actual absolute path, not the `current`
symlink. This compares the version, lockfile and release file fingerprint; it
does not check the prepared virtual environment or prove the release is
trusted or compatible with a database. Format 2 backups remain verifiable but
cannot be compared this way because they lack a release fingerprint.
A checksum stored alongside the backup detects
accidental corruption, **not malicious alteration**; secure and independently
protect the backup and its manifest. An interrupted backup can leave a private
partial directory; do not treat it as complete.
The backup includes credentials. The manifest identifies the current release
and lockfile hash, but **does not contain the runtime, TLS proxy configuration,
external certificates or backups from other hosts**. Preserve those separately,
including the matching release and the original Agent identities. Restore and
automated rollback are not implemented; do not replace a live database.

To make a separate, verified restore copy without changing live data:

```sh
sudo python3 /usr/share/stunsail/source/deployment/installer/stage_restore.py \
  /root/stunsail-backup-1 /root/stunsail-restore-stage
```

The staging destination must be new, outside the installation and backup
directories, with a root-owned secure parent. The command verifies the source,
copies it into a private directory, and verifies the copy. This does **not**
install the restore, set service ownership, restart services, or coordinate
remote Agents. Files in the staged copy contain secrets and the original
database identity. If staging fails, a partial directory can remain; inspect it
securely. See [operations](../../docs/architecture/operations.md#backup-and-restore)
before manually recovering data.

## Runtime preparation

`python3 deployment/installer/prepare_runtime.py SOURCE DESTINATION` copies a
trusted release payload into a new final runtime directory, then uses `uv sync
--locked --all-packages --no-default-groups --group runtime` to prepare its
Python environment. It
requires an existing `uv` executable, internet access for missing locked
dependencies, and a prebuilt web UI. The runtime group includes Alembic without
installing the development test and lint tools. The destination must not exist and
must be outside the source tree. Runtime console scripts refer to their
installation path: do not move the prepared directory afterward.

Use the allowlisted package payload as the source, not a development checkout:
the tool copies the complete source directory. It does not activate the
runtime, migrate a database, create service users, install units, configure
TLS or start a service. If preparation fails, inspect the partial directory
before removing it and retrying. Do not remove or replace an existing release
or database to retry.
