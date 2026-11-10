# systemd service templates

`stunsail-core.service` and `stunsail-agent@.service` are initial service
definitions. An experimental fresh-install command can provision them, but it
has not yet been validated on a target device or isolated systemd environment.
They assume a prepared runtime at `/opt/stunsail/current`, with its virtual
environment, built web assets and Alembic files, plus dedicated
`stunsail-core` and `stunsail-agent` users.

Core reads `/etc/stunsail/core.env` and listens on loopback port 8000. Each
Agent instance reads `/etc/stunsail/agent/<id>/agent.yaml` and `agent.env`,
and keeps its buffer under `/var/lib/stunsail/agent/<id>`. Use the same ID in
the configuration and systemd instance. When selecting a unit, escape the ID:

```sh
unit="$(systemd-escape --template=stunsail-agent@.service -- 'printer-1')"
printf '%s\n' "$unit"
```

The unit uses systemd's unescaped instance (`%i`) for paths, so the on-disk
directory names match the raw ID even for IDs containing hyphens or leading
dots. The escaped unit name must still be generated with
`systemd-escape --template=stunsail-agent@.service -- '<id>'` even for IDs
containing hyphens or leading dots. Do not construct unit names by
concatenating a raw ID.
Credentials belong in protected
environment files, not service command lines. `systemd` reads those files;
the Agent configuration and CA bundle must also be readable by the Agent user.
Keep configuration and tokens private to their respective service identities.

These units deliberately do not run database migrations. Back up the database,
apply compatible migrations, and validate recovery before starting or
upgrading services. No HTTPS endpoint is provided by these units; a TLS
terminator is required for remote Agents. Upgrade, package hooks and safe
complete uninstall are not yet automated or verified on target hosts. An
experimental service removal command retains application data and requires a
verified backup; it has only been exercised with mocked systemd. See
`../installer/README.md` for experimental fresh installation and
`../installer/configs/README.md` for deployment requirements.
