# Phase 5 checklist: installation, multi-printer and distributed Agents

Phase 5 delivers the guided installer and Debian package, Standalone and
Agent-only modes, per-Agent identity and outbound TLS, durable buffering and
acknowledgement-based sync, and safe backup/restore/upgrade/uninstall paths.
Everything here is **experimental**: it has been exercised on a real printer
host but is not production-ready, and licensing/entitlements are not implemented.

## Delivered

- [x] Guided installer (`guided_install.py`) and allowlisted Debian payload
  (`deployment/debian/build_package.py`); fresh install for Standalone and
  Agent-only from the same codebase.
- [x] Read-only preflight (`preflight.py`) with recommended 2 GiB / minimum
  256 MiB disk policy (`LOW SPACE` confirmation) and experimental-platform
  (`EXPERIMENTAL`) confirmation; Debian 13 Trixie is opt-in experimental.
- [x] Per-Agent identity, registration, token reset and revocation; multiple
  Moonraker instances per host and multiple Agents per host; distributed
  Agent-only hosts.
- [x] Durable local SQLite buffering, acknowledgement-based sync, retry/backoff,
  and rejection of conflicting replays / invalid acknowledgements without
  discarding queued data.
- [x] Agent-only requires HTTPS with certificate and hostname verification and
  optional private-CA support; buffers cannot be silently reassigned.
- [x] Experimental TLS frontend: `https_frontend.py` (uvicorn + httpx ASGI reverse
  proxy, port 8443, unprivileged `stunsail-core`, zero new runtime deps),
  PC-side `generate_ca_and_cert.py` (dev-only cryptography), post-install
  `provision_tls.py`. Core stays loopback-only; Moonraker is never exposed.
- [x] Backup (`maintenance_backup.py` / `backup_installation.py`), verification
  (`verify_backup.py`), non-destructive restore staging (`stage_restore.py`) and
  offline restore (`apply_restore.py`); backups include the local TLS certs.
- [x] Experimental offline upgrade (`apply_upgrade.py`) and rollback
  (`rollback_upgrade.py`) with rehearsal (`rehearse_upgrade.py`).
- [x] Backup-first complete uninstall (`full_uninstall.py`); units-only removal
  (`remove_services.py`); read-only running-service check (`check_running.py`).

## Validated on the real printer host (2026-11-14)

Host: Armbian trixie, aarch64, Python 3.13, ~7 GiB eMMC (experimental platform).

- [x] Fresh guided install; Core + Agent services enabled, active, and survived a
  host reboot; `check_running.py --mode standalone` passed.
- [x] TLS frontend served the authenticated UI over HTTPS via the private CA;
  query strings preserved; unauthenticated API access rejected (401).
- [x] A TLS Agent (`agent_only`, `https://<host>:8443` + CA) synced 200 over
  verified HTTPS; a live print was tracked through it with no errors.
- [x] Negative TLS test: an unrelated CA produced `CERTIFICATE_VERIFY_FAILED`;
  restoring the correct CA recovered the sync (verification is enforced).
- [x] Maintenance round-trip on real systemd: backup → verify → stage →
  apply-restore, then a clean reboot with all services auto-starting active.
- [x] `full_uninstall.py` removed a TLS host (2 Agents + frontend + certs)
  completely; host returned to a clean state with 542 MiB free.

## Exit-criteria verification

- [x] Add printers on one host (multiple Agents) and a remote Agent-only host;
  temporary network loss does not lose collected data (durable buffer; covered
  by unit/integration sync-conflict and replay tests).
- [x] Duplicate sync does not duplicate jobs or spool deductions (idempotent
  finalization; integration tests).
- [x] Agent restart mid-print yields one job, no duplicates (real print).
- [ ] Offline upgrade and rollback on real systemd — **deferred to the next
  round** (validated with mocked systemd and integration tests so far).
- [ ] Wall-meter calibration carryover from the Phase 2 checklist.

## Known limits

- Experimental; not production-ready. No production-readiness claim is made.
- Upgrade/rollback have not been validated on real systemd (deferred).
- Licensing and edition entitlements are **not implemented**; the
  Community/Pro/Fleet boundaries are documented intent, not enforced gates.
- Energy is estimated until meter calibration; estimated and measured values
  are kept distinct.
- LAN-only, single-user. Do not expose Core or the frontend to the internet.
- The TLS frontend has no client-certificate authentication; Core tokens remain
  the access control. Certificate rotation/revocation is manual.
