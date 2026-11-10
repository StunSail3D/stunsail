# Debian package payload

The package builder creates an **experimental application payload**, not a
complete installer. Installing the package itself installs no service units,
creates no users or configuration, and never starts services or migrates
databases. An experimental, separately invoked fresh-install command is
included in the payload; it has not yet been validated on target devices.
Upgrade, TLS provisioning and complete uninstall remain in development. An
experimental, separately invoked service removal tool retains application
data and has not been validated with real systemd or on target devices.
The experimental offline restore command has the same validation limitation;
package installation or removal does not invoke it.
The payload also includes an experimental upgrade migration rehearsal; it
does not activate a candidate or perform an upgrade. A separate experimental
offline upgrade command can switch the release and Core data, but has not been
validated with real systemd or on target devices and is not production-ready.
The experimental offline rollback command also requires coordinated downtime,
a verified backup and explicit acceptance of data loss; it is not automatic.
The experimental running-service check validates local service state and Core
readiness after manual startup; it does not verify printer or Agent connectivity.

On a Debian-family build host with Python 3.11+, `dpkg-deb`, Node.js and npm:

```sh
cd apps/web
npm ci
npm run build
cd ../..
python3 deployment/debian/build_package.py /path/to/new/stunsail.deb
dpkg-deb --info /path/to/new/stunsail.deb
dpkg-deb --contents /path/to/new/stunsail.deb
```

The output file must not already exist. The build uses an explicit allowlist
for source, migrations, installer tools, unit templates and web assets. It
does not package workspace databases, local configuration or credentials.
Review the built package before distribution. The builder does not sign it or
verify that prebuilt web assets match the source; build the web UI first.

The resulting `stunsail` package places the payload under
`/usr/share/stunsail/source`. Package installation and removal manage only
that payload: they do not configure, migrate, activate or remove application
data. See [installer documentation](../installer/README.md) for runtime
preparation and the remaining work before a supported installation.
