#!/usr/bin/env python3
"""Generate a private CA certificate and server certificate with IP SAN."""

import datetime
import ipaddress
import os
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def generate_ca() -> tuple[bytes, bytes]:
    """Generate a private CA certificate and key."""
    
    # Generate private key for the CA
    ca_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Create CA subject name
    ca_subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "StunSail"),
        x509.NameAttribute(NameOID.COMMON_NAME, "StunSail CA"),
    ])

    # Create the certificate
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_subject)
        .issuer_name(ca_subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3650))  # 10 years
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    return (
        ca_cert.public_bytes(serialization.Encoding.PEM),
        ca_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
    )


def generate_server_cert(ca_cert: bytes, ca_key: bytes, ip_address: str) -> tuple[bytes, bytes]:
    """Generate a server certificate signed by the CA."""
    
    # Load the CA key and cert
    loaded_ca_key = serialization.load_pem_private_key(ca_key, password=None)
    loaded_ca_cert = x509.load_pem_x509_certificate(ca_cert)

    # Generate private key for server
    server_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Create subject name for the server
    server_subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "StunSail"),
        x509.NameAttribute(NameOID.COMMON_NAME, ip_address),
    ])

    # Create IP SAN for the provided address
    ip_san = x509.IPAddress(ipaddress.ip_address(ip_address))

    # Create the certificate
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_subject)
        .issuer_name(loaded_ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))  # 1 year
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.SubjectAlternativeName([ip_san]),
            critical=False,
        )
        .sign(loaded_ca_key, hashes.SHA256())
    )

    return (
        server_cert.public_bytes(serialization.Encoding.PEM),
        server_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
    )


def main(ip_address: str = "192.168.101.50"):
    """Main function to generate CA and server certificates."""
    
    # Create directory for storing the certificates if it doesn't exist
    output_dir = Path("certs")
    output_dir.mkdir(exist_ok=True)
    
    print(f"Generating certificates in {output_dir.absolute()}")
    
    # Generate CA certificate and key
    ca_cert, ca_key = generate_ca()
    
    # Save CA files
    with open(output_dir / "ca.crt", "wb") as f:
        f.write(ca_cert)
        
    with open(output_dir / "ca.key", "wb") as f:
        f.write(ca_key)
    
    print("CA certificate and key generated successfully.")
    
    # Generate server certificate signed by CA
    server_cert, server_key = generate_server_cert(ca_cert, ca_key, ip_address)
    
    # Save server files  
    with open(output_dir / "server.crt", "wb") as f:
        f.write(server_cert)
        
    with open(output_dir / "server.key", "wb") as f:
        f.write(server_key)
        
    print("Server certificate and key generated successfully.")
    
    return 0


if __name__ == "__main__":
    ip_address = sys.argv[1] if len(sys.argv) > 1 else "192.168.101.50"
    sys.exit(main(ip_address))