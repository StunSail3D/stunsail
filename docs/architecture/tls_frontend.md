# TLS frontend (experimental)

This describes the experimental TLS frontend for an installer-managed StunSail
host. It is not production-ready and has not been validated on target devices.
It does **not** provide client-certificate authentication: any client that trusts
the CA can reach the proxied Core API, and Core's own admin and Agent tokens
remain the access control.

## Design

- Core stays bound to `127.0.0.1:8000` and is never exposed directly. Moonraker
  is never proxied or exposed.
- `deployment/installer/https_frontend.py` is a minimal ASGI reverse proxy served
  by the already-locked `uvicorn` with `--ssl-certfile`/`--ssl-keyfile`, forwarding
  to Core with the already-locked `httpx`. It adds no runtime dependency.
- The frontend listens on `0.0.0.0:8443` as the unprivileged `stunsail-core`
  account (`stunsail-frontend.service`), mirroring Core's hardening. It reads no
  environment file and never sees the Core admin token.
- It forwards the method, path, query string and headers (stripping hop-by-hop
  headers case-insensitively), streams request and response bodies, adds
  `X-Forwarded-For`/`X-Forwarded-Proto`, and returns 502 when Core is unreachable.

## Certificate generation (PC only)

`deployment/installer/generate_ca_and_cert.py` runs on a trusted PC, not on the
printer host. It requires the dev-only `cryptography` dependency, which is
intentionally absent from the host runtime. It creates a private CA and a server
certificate whose public key comes from the **server** key, with an IP SAN for the
host (for example `192.168.101.50`), SubjectKeyIdentifier/AuthorityKeyIdentifier,
KeyUsage and ExtendedKeyUsage `serverAuth`.

```sh
python3 deployment/installer/generate_ca_and_cert.py \
  --ca-cert ca.crt --ca-key ca.key \
  --server-cert server.crt --server-key server.key \
  --ip-address 192.168.101.50
```

The CA private key (`ca.key`) must stay on the PC and must never be copied to the
printer host. Copy only `server.crt`, `server.key` and `ca.crt` to the host. The
generator refuses to overwrite existing outputs and writes private keys with
owner-only permissions on POSIX. Supplied certificates and Let's Encrypt (DNS
validation) are planned alternatives but are not implemented by this tool.

## Provisioning on the host

`provision_tls.py` is a post-install step; it does not change the validated
fresh-install path. As root, with the three files copied to the host:

```sh
sudo python3 /opt/stunsail/current/deployment/installer/provision_tls.py \
  --server-cert /root/server.crt --server-key /root/server.key \
  --ca-bundle /root/ca.crt --ip-address 192.168.101.50 \
  --confirm-provision-tls
```

It validates regular files, certificate/key match, and a CA bundle that parses
and contains no private key; installs `/etc/stunsail/certs` (directory `0750`
root:stunsail-core, `server.key` `0640` root:stunsail-core, certificates `0644`),
refusing overwrites; installs the release's `stunsail-frontend.service`, reloads
systemd and enables it; then verifies HTTPS readiness against the CA with the
host IP as the hostname. That verified handshake enforces the IP SAN, validity
period and chain. The host runtime has no `cryptography`, so validation uses the
standard library only. A failure can leave certificates or the frontend service
partially installed; inspect them before retrying.

## Onboarding an Agent over TLS

1. Register a new Agent ID in Core Settings and copy its one-time token.
2. Run `configure.py`, choose `agent_only`, Core URL `https://192.168.101.50:8443`,
   CA bundle path `/etc/stunsail/certs/ca.crt`, and the registered token.
3. Run `add_agent.py <bundle> --confirm-add-agent`. The Agent gets its own private
   `ca.pem` copy; it verifies the Core certificate against the CA with hostname
   checking. HTTPS is required for `agent_only`.
4. Verify the Agent syncs over HTTPS and register its printer.

See the [installer documentation](../../deployment/installer/README.md) for the
experimental TLS provisioning and full-uninstall commands.

## Negative-test procedure

A positive sync alone does not prove verification. On the host (or a test host),
confirm that a misconfigured Agent **fails** to sync:

- Point `core_ca_file` at a different, unrelated CA bundle: the handshake must fail.
- Use a Core URL whose hostname/IP is not in the certificate SAN: verification
  must fail.
- Remove or expire the server certificate: the frontend must not serve a trusted
  handshake.

Do not disable certificate or hostname verification to make a test pass. The unit
tests exercise a real uvicorn TLS handshake with generated certificates and a
wrong-CA negative; live-host negative tests remain part of target validation.

## Limitations

- No client-certificate authentication; tokens remain the access control.
- The frontend exposes the Core API on the LAN to any client trusting the CA.
  Restrict network access to trusted hosts; do not expose it to the internet.
- Certificate rotation, revocation (CRL/OCSP) and automated renewal are not
  implemented. Regenerate on the PC and re-provision to rotate.
- Experimental; not validated on target devices or against real systemd at scale.
