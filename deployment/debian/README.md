# Debian package payload

The package builder creates an **experimental application payload**, not a
complete installer. It installs no service units, does not create users or
configuration, and never starts services or migrates databases. An operator
must prepare the runtime and provision the system separately; automatic
installation, upgrade, TLS and uninstall are still in development.

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
