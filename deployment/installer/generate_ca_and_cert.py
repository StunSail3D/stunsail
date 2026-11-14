#!/usr/bin/env python3
"""Generate a private CA and a TLS server certificate for the StunSail frontend.

By default this is a PC-side tool: the CA private key is written to ``--ca-key``
and must stay on that computer, never copied to the printer host. With
``--no-ca-key`` the CA is generated in memory and its private key is never written
to disk, so the command can run on the printer host without persisting a CA key
(only the server certificate/key and the public CA certificate are written).

Requires the ``cryptography`` dependency: the dev group on a PC, or a transient
``uv run --with cryptography`` environment on the host (it is intentionally absent
from the host runtime group).
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CA_COMMON_NAME = "StunSail Private CA"
CA_KEY_BITS = 4096
SERVER_KEY_BITS = 2048
CA_VALIDITY = timedelta(days=3650)
SERVER_VALIDITY = timedelta(days=365)
CLOCK_SKEW = timedelta(days=1)


def _new_key(bits: int) -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=bits)


def _common_name(value: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, value)])


def generate_ca() -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    """Create a self-signed CA restricted to issuing end-entity certificates."""
    key = _new_key(CA_KEY_BITS)
    now = datetime.now(UTC)
    subject = _common_name(CA_COMMON_NAME)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - CLOCK_SKEW)
        .not_valid_after(now + CA_VALIDITY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    return certificate, key


def generate_server_cert(
    ca_cert: x509.Certificate,
    ca_key: rsa.RSAPrivateKey,
    ip_addresses: list[str],
    server_names: list[str],
) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    """Issue a server certificate whose public key comes from the SERVER key."""
    if not ip_addresses and not server_names:
        raise ValueError("at least one IP address or server name is required")
    key = _new_key(SERVER_KEY_BITS)
    now = datetime.now(UTC)
    names: list[x509.GeneralName] = [
        x509.IPAddress(ipaddress.ip_address(value)) for value in ip_addresses
    ]
    names.extend(x509.DNSName(value) for value in server_names)
    common_name = server_names[0] if server_names else ip_addresses[0]
    certificate = (
        x509.CertificateBuilder()
        .subject_name(_common_name(common_name))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - CLOCK_SKEW)
        .not_valid_after(now + SERVER_VALIDITY)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return certificate, key


def certificate_pem(certificate: x509.Certificate) -> bytes:
    return certificate.public_bytes(serialization.Encoding.PEM)


def private_key_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _refuse_existing(paths: tuple[Path, ...]) -> None:
    for path in paths:
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"refusing to overwrite existing output: {path}")


def _write_new(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ca-cert", type=Path, default=Path("ca.crt"), help="CA certificate output (PEM)"
    )
    parser.add_argument(
        "--ca-key",
        type=Path,
        default=Path("ca.key"),
        help="CA private key output (PEM); keep on this PC, never copy to the host",
    )
    parser.add_argument(
        "--server-cert",
        type=Path,
        default=Path("server.crt"),
        help="server certificate output (PEM)",
    )
    parser.add_argument(
        "--server-key",
        type=Path,
        default=Path("server.key"),
        help="server private key output (PEM)",
    )
    parser.add_argument(
        "--ip-address",
        action="append",
        default=[],
        metavar="IP",
        help="IP subject alternative name (repeatable)",
    )
    parser.add_argument(
        "--server-name",
        action="append",
        default=[],
        metavar="DNS",
        help="DNS subject alternative name (repeatable)",
    )
    parser.add_argument(
        "--no-ca-key",
        action="store_true",
        help="generate the CA in memory and never write its private key (host-side use)",
    )
    args = parser.parse_args(argv)
    if not args.ip_address and not args.server_name:
        parser.error("at least one --ip-address or --server-name is required")
    for value in args.ip_address:
        try:
            ipaddress.ip_address(value)
        except ValueError as error:
            parser.error(f"invalid --ip-address {value!r}: {error}")
    for value in args.server_name:
        if not value or " " in value or any(ord(char) < 32 for char in value):
            parser.error(f"invalid --server-name {value!r}")
        try:
            ipaddress.ip_address(value)
        except ValueError:
            continue
        parser.error(f"--server-name {value!r} is an IP literal; use --ip-address instead")
    outputs = [args.ca_cert, args.server_cert, args.server_key]
    if not args.no_ca_key:
        outputs.append(args.ca_key)
    try:
        _refuse_existing(tuple(outputs))
        ca_cert, ca_key = generate_ca()
        server_cert, server_key = generate_server_cert(
            ca_cert, ca_key, args.ip_address, args.server_name
        )
        _write_new(args.ca_cert, certificate_pem(ca_cert), 0o644)
        _write_new(args.server_cert, certificate_pem(server_cert), 0o644)
        _write_new(args.server_key, private_key_pem(server_key), 0o600)
        if not args.no_ca_key:
            _write_new(args.ca_key, private_key_pem(ca_key), 0o600)
    except (OSError, ValueError) as error:
        print(f"Certificate generation failed: {error}", file=sys.stderr)
        return 1
    print(f"CA certificate:     {args.ca_cert}")
    if args.no_ca_key:
        print("CA private key:     not written (generated in memory and discarded)")
    else:
        print(f"CA private key:     {args.ca_key}  (keep on this PC; never copy to the host)")
    print(f"Server certificate: {args.server_cert}")
    print(f"Server private key: {args.server_key}")
    if args.no_ca_key:
        print("Install server.crt, server.key and ca.crt with provision_tls.py.")
    else:
        print("Copy server.crt, server.key and ca.crt to the host; keep ca.key on this PC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
