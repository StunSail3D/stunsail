#!/usr/bin/env python3
"""
Generate CA and server certificates with IP Subject Alternative Name support.
"""

import argparse
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import datetime


def generate_private_key(key_size: int = 2048) -> rsa.RSAPrivateKey:
    """Generate a private key."""
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
    )


def generate_ca_certificate(
    private_key, 
    subject_name: str,
    validity_days: int = 3650
) -> x509.Certificate:
    """Generate a CA certificate."""
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "StunSail CA"),
        x509.NameAttribute(NameOID.COMMON_NAME, subject_name),
    ])

    builder = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=validity_days)
    ).add_extension(
        x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()),
        critical=False,
    ).add_extension(
        x509.BasicConstraints(ca=True, path_length=None),
        critical=True,
    ).add_extension(
        x509.KeyUsage(
            digital_signature=True,
            content_commitment=False,
            key_encipherment=False,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=True,
            crl_sign=True,
            encipher_only=False,
            decipher_only=False
        ),
        critical=True,
    )

    return builder.sign(private_key, hashes.SHA256())


def generate_server_certificate(
    ca_private_key,
    ca_cert,
    server_name: str,
    ip_addresses: list = None,
    validity_days: int = 3650
) -> x509.Certificate:
    """Generate a server certificate."""
    
    # Validate IP addresses if provided 
    if ip_addresses:
        for ip in ip_addresses:
            try:
                ipaddress.ip_address(ip)
            except ValueError as e:
                raise ValueError(f"Invalid IP address: {ip}") from e
    
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "StunSail Server"),
        x509.NameAttribute(NameOID.COMMON_NAME, server_name),
    ])

    builder = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        ca_cert.subject
    ).public_key(
        ca_private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=validity_days)
    ).add_extension(
        x509.SubjectKeyIdentifier.from_public_key(ca_private_key.public_key()),
        critical=False,
    ).add_extension(
        x509.BasicConstraints(ca=False, path_length=None),
        critical=True,
    ).add_extension(
        x509.KeyUsage(
            digital_signature=True,
            content_commitment=False,
            key_encipherment=True,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=False,
            crl_sign=False,
            encipher_only=False,
            decipher_only=False
        ),
        critical=True,
    ).add_extension(
        x509.ExtendedKeyUsage([
            x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
        ]),
        critical=False,
    )

    # Add IP SAN if provided
    if ip_addresses:
        san = x509.SubjectAlternativeName([
            x509.IPAddress(ipaddress.ip_address(ip)) for ip in ip_addresses
        ])
        builder = builder.add_extension(san, critical=False)

    return builder.sign(ca_private_key, hashes.SHA256())


def write_certificates(
    ca_private_key,
    ca_cert,
    server_private_key,
    server_cert,
    ca_cert_path: str,
    ca_key_path: str,
    server_cert_path: str,
    server_key_path: str
):
    """Write certificates and keys to files."""
    
    # Write CA certificate
    with open(ca_cert_path, "wb") as f:
        f.write(ca_cert.public_bytes(serialization.Encoding.PEM))
        
    # Write CA private key (keep it secure)
    with open(ca_key_path, "wb") as f:
        f.write(ca_private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    # Write server certificate
    with open(server_cert_path, "wb") as f:
        f.write(server_cert.public_bytes(serialization.Encoding.PEM))
        
    # Write server private key (keep it secure)
    with open(server_key_path, "wb") as f:
        f.write(server_private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))


def main():
    parser = argparse.ArgumentParser(description="Generate CA and server certificates with IP SAN support")
    parser.add_argument("--ca-cert", required=True, help="Path to write the CA certificate")
    parser.add_argument("--ca-key", required=True, help="Path to write the CA private key")
    parser.add_argument("--server-cert", required=True, help="Path to write the server certificate")
    parser.add_argument("--server-key", required=True, help="Path to write the server private key")
    parser.add_argument("--ip-address", action='append', required=False, 
                       help="IP address for Subject Alternative Name (can be specified multiple times)")
    parser.add_argument("--server-name", default="stunsail-server", 
                       help="Server certificate Common Name")

    args = parser.parse_args()
    
    # Generate CA private key
    ca_private_key = generate_private_key(2048)
    
    # Generate CA certificate  
    ca_cert = generate_ca_certificate(ca_private_key, "StunSail Root CA")
    
    # Generate server private key
    server_private_key = generate_private_key(2048) 
    
    # Generate server certificate with IP SANs if provided
    server_cert = generate_server_certificate(
        ca_private_key,
        ca_cert,
        args.server_name,
        ip_addresses=args.ip_address or []
    )
    
    # Write all files to disk 
    write_certificates(
        ca_private_key, 
        ca_cert,
        server_private_key,
        server_cert,
        args.ca_cert,
        args.ca_key,
        args.server_cert,
        args.server_key
    )

    print(f"Generated certificates:")
    print(f"  CA certificate: {args.ca_cert}")
    print(f"  CA private key: {args.ca_key}")
    print(f"  Server certificate: {args.server_cert}")
    print(f"  Server private key: {args.server_key}")
    
    if args.ip_address:
        print(f"  IP SANs included: {', '.join(args.ip_address)}")


if __name__ == "__main__":
    main()