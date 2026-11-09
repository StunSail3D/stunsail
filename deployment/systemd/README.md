# systemd service templates

`stunsail-core.service` and `stunsail-agent@.service` are initial service
definitions. They are **not installed or managed by an installer yet**.
They assume a prepared runtime at `/opt/stunsail/current`, with its virtual
environment, built web assets and Alembic files, plus dedicated
`stunsail-core` and `stunsail-agent` users.

Core reads `/etc/stunsail/core.env` and listens on loopback port 8000. Each
Agent instance reads `/etc/stunsail/agent/<id>/agent.yaml` and `agent.env`,
and keeps its buffer under `/var/lib/stunsail/agent/<id>`. Use the same ID in
the configuration and systemd instance. Credentials belong in protected
environment files, not service command lines. `systemd` reads those files;
the Agent configuration and CA bundle must also be readable by the Agent user.
Keep configuration and tokens private to their respective service identities.

These units deliberately do not run database migrations. Back up the database,
apply compatible migrations, and validate recovery before starting or
upgrading services. No HTTPS endpoint is provided by these units; a TLS
terminator is required for remote Agents. Installation, upgrade, ownership,
package hooks, and safe uninstall are not yet automated or verified on target
hosts. See `../installer/configs/README.md` for deployment requirements.
