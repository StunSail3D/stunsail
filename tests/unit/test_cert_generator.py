import importlib.util
import ipaddress
import os
import ssl
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

MODULE = (
    Path(__file__).resolve().parents[2] / "deployment" / "installer" / "generate_ca_and_cert.py"
)
spec = importlib.util.spec_from_file_location("generate_ca_and_cert", MODULE)
assert spec and spec.loader
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


@pytest.fixture(scope="module")
def material():
    ca_cert, ca_key = generator.generate_ca()
    server_cert, server_key = generator.generate_server_cert(
        ca_cert, ca_key, ["192.0.2.10"], ["printer.example"]
    )
    return ca_cert, ca_key, server_cert, server_key


def write_pems(tmp_path, material):
    ca_cert, ca_key, server_cert, server_key = material
    payloads = {
        "ca.crt": generator.certificate_pem(ca_cert),
        "ca.key": generator.private_key_pem(ca_key),
        "server.crt": generator.certificate_pem(server_cert),
        "server.key": generator.private_key_pem(server_key),
    }
    for name, data in payloads.items():
        (tmp_path / name).write_bytes(data)
    return {name: tmp_path / name for name in payloads}


def cli_args(tmp_path, *extra):
    return [
        "--ca-cert",
        str(tmp_path / "ca.crt"),
        "--ca-key",
        str(tmp_path / "ca.key"),
        "--server-cert",
        str(tmp_path / "server.crt"),
        "--server-key",
        str(tmp_path / "server.key"),
        *extra,
    ]


def test_server_certificate_uses_its_own_key(material):
    ca_cert, ca_key, server_cert, server_key = material
    assert server_cert.public_key().public_numbers() == server_key.public_key().public_numbers()
    assert server_cert.public_key().public_numbers() != ca_key.public_key().public_numbers()
    assert server_cert.public_key().public_numbers() != ca_cert.public_key().public_numbers()


def test_server_certificate_is_issued_by_the_ca(material):
    ca_cert, _, server_cert, _ = material
    assert server_cert.issuer == ca_cert.subject
    assert server_cert.subject != ca_cert.subject
    server_cert.verify_directly_issued_by(ca_cert)


def test_tls_server_can_load_the_generated_chain(tmp_path, material):
    paths = write_pems(tmp_path, material)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(paths["server.crt"]), str(paths["server.key"]))


def test_client_context_trusts_the_generated_ca(tmp_path, material):
    paths = write_pems(tmp_path, material)
    context = ssl.create_default_context(cafile=str(paths["ca.crt"]))
    assert context.cert_store_stats()["x509_ca"] == 1
    assert context.get_ca_certs()


def test_ip_and_dns_sans_are_present(material):
    _, _, server_cert, _ = material
    san = server_cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.IPAddress) == [ipaddress.ip_address("192.0.2.10")]
    assert san.get_values_for_type(x509.DNSName) == ["printer.example"]


def test_multiple_ip_and_dns_sans(material):
    ca_cert, ca_key, _, _ = material
    cert, _ = generator.generate_server_cert(
        ca_cert,
        ca_key,
        ["192.168.101.50", "192.0.2.20"],
        ["printer.local", "extrulith1"],
    )
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.IPAddress) == [
        ipaddress.ip_address("192.168.101.50"),
        ipaddress.ip_address("192.0.2.20"),
    ]
    assert san.get_values_for_type(x509.DNSName) == ["printer.local", "extrulith1"]


def test_common_name_prefers_dns_then_ip(material):
    _, _, server_cert, _ = material
    assert server_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == (
        "printer.example"
    )
    ca_cert, ca_key, _, _ = material
    ip_only, _ = generator.generate_server_cert(ca_cert, ca_key, ["192.0.2.40"], [])
    assert ip_only.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "192.0.2.40"


def test_server_certificate_extensions(material):
    _, _, server_cert, _ = material
    basic = server_cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert basic.ca is False
    usage = server_cert.extensions.get_extension_for_class(x509.KeyUsage).value
    assert usage.digital_signature
    assert usage.key_encipherment
    assert not usage.key_cert_sign
    eku = server_cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku


def test_ca_certificate_extensions(material):
    ca_cert, _, _, _ = material
    assert ca_cert.issuer == ca_cert.subject
    basic = ca_cert.extensions.get_extension_for_class(x509.BasicConstraints).value
    assert basic.ca is True
    assert basic.path_length == 0
    usage = ca_cert.extensions.get_extension_for_class(x509.KeyUsage).value
    assert usage.key_cert_sign
    assert usage.crl_sign


def test_authority_key_identifier_matches_ca_subject_key_identifier(material):
    ca_cert, _, server_cert, _ = material
    ca_ski = ca_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
    aki = server_cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier).value
    assert aki.key_identifier == ca_ski.digest
    server_ski = server_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
    assert server_ski.digest != ca_ski.digest


def test_certificates_are_currently_valid(material):
    now = datetime.now(UTC)
    for cert in (material[0], material[2]):
        assert cert.not_valid_before_utc <= now <= cert.not_valid_after_utc


def test_generate_server_cert_requires_a_san(material):
    ca_cert, ca_key, _, _ = material
    with pytest.raises(ValueError, match="at least one"):
        generator.generate_server_cert(ca_cert, ca_key, [], [])


def test_pem_encodings(material):
    ca_cert, ca_key, server_cert, server_key = material
    assert generator.certificate_pem(ca_cert).startswith(b"-----BEGIN CERTIFICATE-----")
    assert generator.certificate_pem(server_cert).startswith(b"-----BEGIN CERTIFICATE-----")
    assert generator.private_key_pem(ca_key).startswith(b"-----BEGIN PRIVATE KEY-----")
    assert generator.private_key_pem(server_key).startswith(b"-----BEGIN PRIVATE KEY-----")


def test_cli_generates_a_usable_bundle(tmp_path):
    assert generator.main(cli_args(tmp_path, "--ip-address", "192.0.2.30")) == 0
    for name in ("ca.crt", "ca.key", "server.crt", "server.key"):
        assert (tmp_path / name).is_file()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(tmp_path / "server.crt"), str(tmp_path / "server.key"))
    cert = x509.load_pem_x509_certificate((tmp_path / "server.crt").read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.IPAddress) == [ipaddress.ip_address("192.0.2.30")]
    ca_cert = x509.load_pem_x509_certificate((tmp_path / "ca.crt").read_bytes())
    cert.verify_directly_issued_by(ca_cert)


def test_cli_refuses_to_overwrite_existing_outputs(tmp_path, capsys):
    (tmp_path / "server.key").write_bytes(b"existing")
    assert generator.main(cli_args(tmp_path, "--ip-address", "192.0.2.30")) == 1
    assert (tmp_path / "server.key").read_bytes() == b"existing"
    assert not (tmp_path / "ca.crt").exists()
    assert not (tmp_path / "ca.key").exists()
    assert not (tmp_path / "server.crt").exists()
    assert "refusing to overwrite" in capsys.readouterr().err


def test_cli_requires_at_least_one_san(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        generator.main(cli_args(tmp_path))
    assert excinfo.value.code == 2


def test_cli_rejects_invalid_ip_address(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        generator.main(cli_args(tmp_path, "--ip-address", "999.1.1.1"))
    assert excinfo.value.code == 2


def test_cli_rejects_ip_literal_as_server_name(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        generator.main(cli_args(tmp_path, "--server-name", "192.0.2.10"))
    assert excinfo.value.code == 2


def test_write_new_refuses_existing_file(tmp_path):
    target = tmp_path / "out.pem"
    target.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        generator._write_new(target, b"new", 0o600)
    assert target.read_bytes() == b"existing"


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes only")
def test_private_key_files_are_owner_only(tmp_path, material):
    _, ca_key, _, server_key = material
    generator._write_new(tmp_path / "ca.key", generator.private_key_pem(ca_key), 0o600)
    generator._write_new(tmp_path / "server.key", generator.private_key_pem(server_key), 0o600)
    assert (tmp_path / "ca.key").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "server.key").stat().st_mode & 0o777 == 0o600
