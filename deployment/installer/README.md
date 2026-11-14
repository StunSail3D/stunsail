# Installer

A one-command installer is available. It has been exercised on a real printer
host but remains **experimental** — do not use it for a production installation
yet. Upgrades, restore, rollback, TLS provisioning and full uninstall are also
experimental. Example Standalone and Agent-only profiles are in `configs/`.

A single command opens an interactive menu: install Standalone or Agent-only,
back up, uninstall, or run a health check. Installing runs the preflight, the
guided install, an automatic health check, and optional TLS certificate
creation. Start with the prerequisites:

- [Before you begin](#before-you-begin) — get the release source onto the host
  and install `uv`.
- [Installation](#installation-interactive-menu) — run the interactive installer.
- [After installation](#after-installation) — open the UI and register a printer.

## Before you begin

The installer needs the following prerequisites: a Linux host with an active
systemd manager, root access, the system account tools (`groupadd`, `useradd`,
`runuser`, `systemd-escape`), `uv`, and internet access to fetch the locked
runtime dependencies. The release must be an allowlisted Debian payload, not a
development checkout. Installation is limited to a **new**, empty system: it
refuses existing StunSail directories, service accounts, or conflicting units.

### Step 1 — Get the release source onto the host

Build the Debian payload on a trusted machine that has `dpkg-deb`:

```sh
python3 deployment/debian/build_package.py /tmp/stunsail.deb
```

Copy it to the printer host (from your PC), then extract it (on the host):

```sh
scp -P <ssh-port> /tmp/stunsail.deb <user>@<host>:/tmp/stunsail.deb
dpkg-deb -x /tmp/stunsail.deb /tmp/stunsail-src
```

The release source is then `/tmp/stunsail-src/usr/share/stunsail/source`. The
commands below refer to it as `SOURCE`; set it once per shell:

```sh
SOURCE=/tmp/stunsail-src/usr/share/stunsail/source
```

`/tmp` is often a volatile tmpfs; that is fine here because the installer copies
the runtime into `/opt/stunsail` and only reads the source during installation.

### Step 2 — Install uv on the host

`uv` prepares the locked Python runtime. Install it (the script detects the
architecture), then place it where the root installer can find it:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo install -m 0755 ~/.local/bin/uv /usr/local/bin/uv
/usr/local/bin/uv --version
```

The installer runs as root through `sudo`, which uses a restricted `PATH`;
`/usr/local/bin` is on that path, so `uv` must be there, not only in your user's
`~/.local/bin`. On a small disk, keep the dependency cache off the root
filesystem by prefixing install commands with `UV_CACHE_DIR=/tmp/uv-cache`.

The installer runs the preflight automatically before installing. To run it
manually first, see [Read-only preflight](#read-only-preflight).

## Installation (interactive menu)

Run the tool with the extracted release as the argument. It opens a menu:

```sh
sudo env UV_CACHE_DIR=/tmp/uv-cache python3 \
  "$SOURCE/deployment/installer/install.py" "$SOURCE"
```

| Option | Action |
| --- | --- |
| Install Standalone | Core + Agent on this host |
| Install Agent-only | Agent connecting to a remote Core over HTTPS |
| Install TLS certificate | (Re)create and install the frontend certificate — use this if the certificate step failed during an install |
| Backup | Stop services and create a verified backup |
| Uninstall | Optionally back up, then remove StunSail completely; also removes the configuration bundle and exits |
| Health check | Run the read-only running-service check |

Backup and uninstall ask for a backup destination, defaulting to your home
directory (for example `/home/<user>/stunsail-backup`). If that folder already
exists, a timestamped name is suggested so an existing backup is never
overwritten. Uninstall first asks whether to create a backup at all — answering
`n` skips it and permanently deletes the data. After a successful uninstall the
tool removes the configuration bundle (it asks for the location, defaulting to
`~/stunsail-setup`) and exits.

For an install, the tool then walks you through, in order:

1. **Bundle destination** — where to put the private configuration bundle. It
   defaults to your home directory (for example `/home/<user>/stunsail-setup`);
   you can choose another location, such as alongside Klipper. The bundle is
   created root-owned `0700` (only root reads the tokens); its parent folders
   must not be group/world writable or symlinked.
2. **Preflight** — platform, disk, systemd and port checks. A hard failure stops
   the install; low disk space and experimental platforms ask for confirmation.
3. **Configuration** — unique Agent ID, Moonraker URL (defaults to
   `http://127.0.0.1:7125`; a bare `IP:port` is accepted and `http://` is added
   automatically), Core URL, optional CA bundle, and Agent token (the mode is
   already chosen from the menu). For a first standalone install, leave the
   Agent token empty.
4. **Confirmation** — type `INSTALL` to proceed (Enter cancels and leaves the
   bundle in place). If free space is below the recommended 2 GiB (but at least
   256 MiB), or the platform is experimental (for example Debian 13 Trixie),
   confirm the risk with `y`.
5. **Installation** — creates dedicated service accounts, prepares the runtime
   in `/opt/stunsail`, migrates a new Core database, starts and checks Core,
   registers the Agent, and enables the services. The one-time Agent token and
   the Core admin token are saved in the bundle: keep it private.
6. **Health check** — runs `check_running.py` automatically.
7. **TLS (optional, Standalone only)** — asks whether to create a certificate
   for the web frontend. If you accept, enter the host's LAN IP; the installer
   generates a certificate (the CA private key is created in memory and never
   written to disk) and provisions the TLS frontend on port 8443.

The StunSail services, runtime and data always install to the system paths
`/opt/stunsail`, `/etc/stunsail` and `/var/lib/stunsail`; only the configuration
bundle location is choosable.

## After installation

- **Open the UI.** If you created a TLS certificate, browse to
  `https://<host-ip>:8443` (import `/etc/stunsail/certs/ca.crt` as a trusted root
  in your browser to avoid a warning). If you skipped TLS, Core listens on
  loopback only — reach the UI with an SSH tunnel, for example
  `ssh -p <ssh-port> -L 8000:127.0.0.1:8000 <user>@<host>`, then open
  `http://localhost:8000`.
- Use the Core admin token from the bundle in **Settings**, then **register a
  printer** for the Agent. A running service alone does not prove Moonraker or
  synchronization is healthy.
- The installer already ran `check_running.py`; to re-run it manually:

  ```sh
  sudo python3 /opt/stunsail/current/deployment/installer/check_running.py --mode standalone
  ```

Agent-only mode requires an already registered Agent token and an HTTPS Core
URL. An optional supplied CA trust bundle is validated and copied as a publicly
readable certificate file; it must not contain a private key. The Core unit
listens only on loopback and does not expose Moonraker; the TLS frontend is the
only network-facing listener (see
[TLS frontend](../../docs/architecture/tls_frontend.md)).

The installer does not overwrite existing data or attempt automatic rollback.
An error can leave accounts, files, a database, or running services behind;
inspect those resources before any recovery, and do not blindly rerun it or
delete data. Do not use it for an upgrade, an existing installation, or
additional Agents (see
[Experimental additional Agents](#experimental-additional-agents)).

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
Debian 13 Trixie (including images reporting `ID=debian`) can be used only as
an **experimental, unvalidated** test platform. The guided installer requires
the additional `EXPERIMENTAL` confirmation; the direct installer requires
`--confirm-experimental-platform`. This does not bypass architecture, disk
space, or other platform checks and does not imply Trixie support.
Armbian image metadata and actual platform compatibility still need validation
on the target device. Port availability is only a point-in-time check.
The preflight does not detect all service conflicts, provision certificates,
authenticate to Moonraker, or install dependencies; a pass does not mean
installation is supported. It reports less than 2 GiB as a warning and exits
nonzero, so scripts do not silently treat low disk space as a normal pass.

## Experimental running-service check

After explicitly starting the intended services, run:

```sh
sudo python3 /usr/share/stunsail/source/deployment/installer/check_running.py --mode standalone
```

For an Agent-only host use `--mode agent-only` instead. The expected mode is
required so a missing local Core is not mistaken for an Agent-only host.
This read-only check verifies the installer-managed unit templates and that
the configured local Agent services are active and running. On a standalone
host it also checks local Core readiness, rejects unauthenticated access to the
Agent list, uses loopback without proxies, and refuses HTTP redirects. It does
not send or validate an admin credential because the check cannot prove the
identity of the loopback listener. Agent-only hosts do not check a
remote Core. The check never enables, starts, stops or rolls back services.

Passing is a point-in-time result, not proof of Agent-to-Core synchronization,
Moonraker connectivity, printer health, TLS, or durable data correctness.
It does not prove that the loopback HTTP listener belongs to the checked
systemd process. Consult service logs and the UI and test these separately. This check is
experimental and has not been validated against real systemd or target devices.

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
including the matching release and the original Agent identities. Automated
rollback is not implemented; never replace a database while it is in use.

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
securely.

### Experimental offline restore

`apply_restore.py` can replace the configuration and databases of an existing
installer-managed host with a **format 3** backup of the same Core/Agent
topology and matching current release. This is experimental: systemd behavior,
service-user ownership and recovery after interruption have not been validated
on target devices. Do not use it for production yet.

Before attempting it, coordinate a maintenance window: stop remote Agents and
every other process that might read or write this host's installation, and keep
them stopped throughout. Restoring an older snapshot discards subsequent
changes from the active installation; retained previous directories and the
new safety backup are recovery material, not an automatic merge. Restored
credentials and Agent buffers may be outdated relative to other hosts. Do not
run duplicate copies of an Agent identity.

```sh
sudo python3 /usr/share/stunsail/source/deployment/installer/apply_restore.py \
  /root/stunsail-backup-1 /root/stunsail-pre-restore \
  --confirm-restore --confirm-writers-stopped
```

Both paths must be absolute, outside the installation and not contain one
another. The source must have root-owned private directories and files, with
root-owned, non-writable, non-symlinked ancestors. The safety backup path must
be new and have secure root-owned ancestors. The command verifies the source,
checks the release fingerprint and topology, disables and stops local services,
creates and verifies the safety backup, prepares replacement directories with
installer-style permissions, and checks services again. It then renames the
existing `/etc/stunsail` and `/var/lib/stunsail` directories to sibling
`stunsail.restore-previous` directories before installing the replacements.
The original directories retain any SQLite WAL/SHM files. The releases,
service definitions, accounts, remote hosts and TLS configuration are not
replaced. Services remain **disabled and stopped**.

The two directory swaps are not atomic as a pair, and services are not locked
against concurrent starts. If anything fails or power is lost, the system may
be partially swapped: do not restart services or retry blindly. Inspect both
installation paths, their `stunsail.restore-new` and `stunsail.restore-previous`
siblings, and the safety backup before manual recovery. Existing recovery
siblings prevent another attempt; never delete them without confirming what
they contain. Verify ownership, database state, credentials, matching runtime
and remote synchronization before explicitly enabling or starting services.
The tool does not authenticate backups or validate the virtual environment.
See [operations](../../docs/architecture/operations.md#backup-and-restore).

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

The Core uses base Uvicorn instead of the optional `standard` extras; it still
uses the separately required WebSocket library for Moonraker. This reduces disk
use but may reduce HTTP throughput compared with the optional native event loop
and parser; performance on target devices has not yet been benchmarked.
In an isolated x86-64 Ubuntu 24.04 test, a fresh payload and prepared release
used approximately 3 MiB and 39 MiB respectively, plus a 39 MiB cold `uv`
cache and a 36 MiB `uv` executable. These are measurements, not guarantees:
architecture, Python, wheel versions, filesystem allocation and temporary
files affect size. Database and Agent buffer growth, logs, printer files,
backups and retained upgrade releases require additional space.
The experimental fresh-install preflight recommends 2 GiB and requires at least
256 MiB free on the root filesystem; between these limits explicit low-space
confirmation is required. The 256 MiB floor is an estimate based on the
isolated test above, not a guarantee of installation space or operating
headroom on another architecture or filesystem. Check `/opt`, `/var/lib`,
temporary storage and the `uv` cache separately if they are on other
filesystems. Database growth, printer files, backups and upgrades may quickly
exhaust remaining space and disrupt printing. Do not treat the small runtime
measurement as evidence that a nearly full printer host is safe.

Use the allowlisted package payload as the source, not a development checkout:
the tool copies the complete source directory. It does not activate the
runtime, migrate a database, create service users, install units, configure
TLS or start a service. If preparation fails, inspect the partial directory
before removing it and retrying. Do not remove or replace an existing release
or database to retry.

## Experimental upgrade rehearsal

`rehearse_upgrade.py` is a preparation and migration test, **not an upgrade**.
It does not activate the candidate, migrate the live Core database, restart
services, or perform rollback. It is not production-ready or validated against
real systemd on supported target devices.

Prepare a trusted candidate at a new final path directly under
`/opt/stunsail/releases` using `prepare_runtime.py`; do not move its virtual
environment afterward. Review and authenticate the release and its dependencies
independently. The rehearsal checks the candidate's source-file fingerprint
for changes, but does not authenticate it or verify its virtual environment.
It refuses candidate service templates that differ from the installed ones.

Stop and coordinate remote Agents and all other writers throughout the
maintenance window. Then, for example:

```sh
sudo python3 /usr/share/stunsail/source/deployment/installer/rehearse_upgrade.py \
  /opt/stunsail/releases/candidate /root/stunsail-before-upgrade \
  --confirm-stop-services --confirm-writers-stopped
```

The command disables and stops the local services, creates and verifies a new
backup, and checks the current release and stopped units again. For a Core host,
it copies the backed-up database to
`/var/lib/stunsail.upgrade-rehearsal/stunsail.db` and runs the candidate's
Alembic migrations and head check as `stunsail-core`, then checks SQLite
integrity. It also snapshots that migrated database to `smoke.db` in the same
rehearsal directory, starts the candidate Core application in a separate
unprivileged process without opening a network port, and checks readiness plus
admin authentication using a temporary token. For every configured Agent, it
copies the Agent configuration and buffer to
`/var/lib/stunsail.upgrade-rehearsal-agents/<id>` and runs the candidate's
Agent configuration, schema migration, identity and queued-data checks as
`stunsail-agent`, without connecting to Core or Moonraker. Buffers with newer
schema versions than the candidate supports are rejected. The Agent copies
are separate from the backup and live buffers. On an Agent-only host, it does
not run Core migrations or Core checks. The backup and database copies
include sensitive data; protect them. The rehearsal directory must not already
exist; the Agent rehearsal directory must also be absent, even on an
Agent-only host. A failed operation may leave them or the backup partially populated, and
services remain stopped and disabled; inspect them before recovery or retrying.

A successful rehearsal only demonstrates that those migrations and limited
Core and Agent checks passed on that snapshot. It does not check the web UI, Agent sync
or TLS, validate later writes or prove that a live upgrade or rollback is safe.
Service-state checks do not lock
out other processes or starts. Keep all writers coordinated, retain the
original release and backup, and explicitly restart/re-enable services only
after deciding how to proceed.

## Experimental offline upgrade

`apply_upgrade.py` runs a **new** full rehearsal and backup, then replaces
the Core database directory with a snapshot of the migrated rehearsal database
and switches the `current` release symlink to the candidate. Agent-only hosts
switch only the release. It retains the old release, the original Core
directory (including SQLite WAL/SHM files), the backup and rehearsal copies.
Services remain disabled and stopped; the command does not start them or perform
a post-start health check. After inspection and explicit service activation,
the separate running-service check above provides limited local validation.

This workflow is experimental and **not production-ready**. It has not been
validated against real systemd or target hardware. It requires the same
trusted candidate, unchanged service templates and maintenance coordination as
the rehearsal above. Stop remote Agents and all other writers before beginning,
and keep them stopped until the installation has been inspected and validated.
Service checks are point-in-time checks and do not lock out other starts or
external writers; violating the maintenance window can lose data.

```sh
sudo python3 /usr/share/stunsail/source/deployment/installer/apply_upgrade.py \
  /opt/stunsail/releases/candidate /root/stunsail-before-upgrade \
  --confirm-upgrade --confirm-writers-stopped
```

The Core directory and release symlink cannot be switched atomically as a
pair. For a caught filesystem error during the switch, the command attempts to
restore the original Core directory only if the release link still points to
the original release, the local services remain stopped, and the directory
identities match. It retains the prepared directory and reports recovery
failure explicitly. This is not a crash, power-loss, or post-start rollback
mechanism, and local checks cannot prevent external writers or concurrent
starts. Interruption or failure can leave the release and data mismatched. Do **not** start
services or retry blindly after failure; inspect `/opt/stunsail/current`,
`/opt/stunsail/current.upgrade-new`, `/var/lib/stunsail/core`,
`/var/lib/stunsail.upgrade-core-new`, `/var/lib/stunsail.upgrade-core-previous`,
the rehearsal copies and the
verified backup first. Existing recovery paths block another attempt.
Restoring an older snapshot after new writes can discard those writes.
Keep the backup private and retain the old
release and data until recovery and application health have been verified.
The Core data directory and its parent must reside on the same filesystem so
the directory renames can succeed.

## Experimental offline rollback

`rollback_upgrade.py` can revert a **completed** offline upgrade to the
release and Core database in its trusted format 3 pre-upgrade backup. It is
experimental, is not automatic, and has not been validated with real systemd
or on target devices. It cannot safely recover a partially switched upgrade;
inspect and repair that state manually first.

**Core changes since the backup will be lost from the active database.**
The command first creates and verifies a new safety backup of the current
installation and retains the current Core directory, including WAL/SHM files.
It refuses changed local configuration or Agent topology, checks that the
previous release and unit templates match, and tests its Core and Agent
compatibility on separate copies. It does not roll back Agent buffers or
remote hosts: newer Agent events, acknowledgements, credentials or remote Core
changes can be inconsistent with the older Core database. Coordinate and
reconcile these separately; never run two copies of the same Agent identity.

Stop remote Agents and all other writers for the entire maintenance window,
then, for example:

```sh
sudo python3 /usr/share/stunsail/source/deployment/installer/rollback_upgrade.py \
  /root/stunsail-before-upgrade /root/stunsail-before-rollback \
  --confirm-rollback --confirm-writers-stopped --confirm-data-loss
```

Both backups must be protected, the first must be root-owned and private,
and the second must be a new path with secure root-owned ancestors. The old
release and its prepared runtime must still be present under
`/opt/stunsail/releases`. Checksums do not authenticate the backup or verify
the virtual environment. Services stay disabled and stopped.

The database and release switches are not atomic together. The same limited
in-process Core recovery described for offline upgrade is attempted on a
caught switch error; it does not recover crashes or power loss. If interrupted,
do not start services or retry blindly. Inspect `/opt/stunsail/current`,
`/opt/stunsail/current.rollback-new`, `/var/lib/stunsail/core`,
`/var/lib/stunsail.rollback-core-new`, `/var/lib/stunsail.rollback-core-previous`,
the rollback rehearsal directories and both backups before manual recovery.
Existing recovery paths prevent retrying. Verify data, credentials, Agent sync
and health before manually starting services.

## Experimental TLS provisioning

An installer-managed standalone host can expose Core over HTTPS through a small
TLS frontend, without changing the loopback-only Core listener. This is
experimental and has not been validated on target devices. See
[TLS frontend](../../docs/architecture/tls_frontend.md) for the design,
PC-side certificate generation, Agent onboarding and the negative-test procedure.

Generate a private CA and a server certificate **on a trusted PC** with
`generate_ca_and_cert.py` (a dev-only tool; the host runtime has no
`cryptography`). The certificate uses an IP SAN for the host. Keep the CA private
key on the PC; copy only `server.crt`, `server.key` and `ca.crt` to the host.
Then, as root:

```sh
sudo python3 /opt/stunsail/current/deployment/installer/provision_tls.py \
  --server-cert /root/server.crt --server-key /root/server.key \
  --ca-bundle /root/ca.crt --ip-address 192.168.101.50 \
  --confirm-provision-tls
```

The command validates the inputs, installs `/etc/stunsail/certs` and the
`stunsail-frontend.service` unit (port 8443, unprivileged `stunsail-core`),
enables it, and verifies HTTPS readiness against the CA using the host IP. It
refuses to overwrite existing certificates or the unit. The frontend proxies to
the loopback Core; it never exposes Moonraker and never reads the admin token.
There is no client-certificate authentication: Core's tokens remain the access
control, so restrict network access to trusted hosts. A failure can leave
certificates or the service partially installed; inspect them before retrying.
The local frontend certificates are included in installation backups; the CA
private key and any external TLS infrastructure are not.

## Experimental full uninstall

`full_uninstall.py` completely removes an installer-managed host. By default it
first creates a verified backup; with `--no-backup` it skips the backup and the
data is permanently lost. It is experimental, destructive, and has not been
validated on target devices. **It deletes all StunSail data, configuration,
databases, buffers, services and service accounts.** Retain the backup securely
if you may need the data again; removing the backup later reclaims its space.

Stop remote Agents and coordinate all other writers first. Then, as root:

```sh
sudo python3 /opt/stunsail/current/deployment/installer/full_uninstall.py \
  /root/stunsail-uninstall-backup --confirm-full-uninstall
```

To skip the backup (permanent data loss), omit the destination and add
`--no-backup`:

```sh
sudo python3 /opt/stunsail/current/deployment/installer/full_uninstall.py \
  --no-backup --confirm-full-uninstall
```

The command first creates and verifies a backup (disabling and stopping the
managed Core and Agent services), then stops and disables the TLS frontend if
present, removes all StunSail unit files and enablement links, reloads systemd,
deletes `/opt/stunsail`, `/etc/stunsail` and `/var/lib/stunsail`, and removes the
`stunsail-core` and `stunsail-agent` accounts. It verifies that no StunSail units,
directories or accounts remain and reports the backup location and the change in
free space (the retained backup still occupies space). It does not remove the
Debian package itself, remote Agents, or the PC-side CA key.

Without `--confirm-full-uninstall` the command refuses to run. If it fails, the
installation may be partially removed; inspect the backup, remaining directories,
units and accounts before retrying. Do not assume the system is clean. This is
the complete uninstall that `remove_services.py` (units only) is not.
