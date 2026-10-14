import ipaddress
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID

from scripts.make_cert import SERVER_DAYS, make_server_cert


def _load(p):
    return x509.load_pem_x509_certificate(p.read_bytes())


def test_server_cert_is_signed_by_shop_authority_and_phone_friendly(tmp_path):
    pem, key, new_ca = make_server_cert(tmp_path, ["localhost", "192.168.1.50", "tienda.local"])
    assert new_ca and key.stat().st_mode & 0o777 == 0o600
    ca, cert = _load(tmp_path / "ca.pem"), _load(pem)
    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is True
    assert cert.issuer == ca.subject
    cert.verify_directly_issued_by(ca)
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.DNSName) == ["localhost", "tienda.local"]
    assert san.get_values_for_type(x509.IPAddress) == [ipaddress.ip_address("192.168.1.50")]
    assert ExtendedKeyUsageOID.SERVER_AUTH in cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    life = cert.not_valid_after_utc - cert.not_valid_before_utc
    assert life <= timedelta(days=SERVER_DAYS, minutes=5)  # iOS limit: 825 days


def test_authority_is_reused_so_phones_keep_trusting(tmp_path):
    make_server_cert(tmp_path, ["localhost"])
    first_ca = (tmp_path / "ca.pem").read_bytes()
    pem, _, new_ca = make_server_cert(tmp_path, ["localhost", "10.0.0.7"], now=datetime.now(timezone.utc))
    assert not new_ca and (tmp_path / "ca.pem").read_bytes() == first_ca
    _load(pem).verify_directly_issued_by(_load(tmp_path / "ca.pem"))
