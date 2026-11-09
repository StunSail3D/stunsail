# Installer

The guided installer and systemd service setup are not yet implemented.
Example Standalone and Agent-only profiles are in `configs/`.

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
