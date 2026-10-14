"""Create the local HTTPS certificate for the shop PC.

Phones only allow the live camera and installing the app on HTTPS pages. This
script makes a small certificate authority for the shop (once) and a server
certificate for this PC's addresses, signed by it. Each shop phone installs the
authority once (see README: "HTTPS on the shop network").

Usage:
    python scripts/make_cert.py                     # localhost, this hostname, this PC's LAN IP
    python scripts/make_cert.py --host 192.168.1.50 --host tienda.local

Writes data/certs/ca.pem (install on phones), ca.key (keep private),
server.pem and server.key (used by uvicorn). Re-run when the PC's IP changes;
the authority is reused, so phones don't need to install anything again.
"""

from __future__ import annotations

import argparse
import ipaddress
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parent.parent
CA_DAYS = 3650
# iOS rejects server certificates valid for more than 825 days.
SERVER_DAYS = 825


def lan_ip() -> str | None:
    """This PC's address on the local network (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _write_key(key, path: Path) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    path.chmod(0o600)


def load_or_create_ca(out: Path, now: datetime):
    cert_path, key_path = out / "ca.pem", out / "ca.key"
    if cert_path.exists() and key_path.exists():
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        return x509.load_pem_x509_certificate(cert_path.read_bytes()), key, False
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TCG Buylist Scanner - tienda local"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TCG Buylist Scanner")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                     content_commitment=False, key_encipherment=False, data_encipherment=False,
                                     key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    out.mkdir(parents=True, exist_ok=True)
    _write_key(key, key_path)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert, key, True


def make_server_cert(out: Path, hosts: list[str], now: datetime | None = None) -> tuple[Path, Path, bool]:
    """Returns (server.pem, server.key, created_new_ca)."""
    now = now or datetime.now(timezone.utc)
    ca_cert, ca_key, new_ca = load_or_create_ca(out, now)
    key = ec.generate_private_key(ec.SECP256R1())
    sans: list[x509.GeneralName] = []
    for h in dict.fromkeys(hosts):  # keep order, drop repeats
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(h)))
        except ValueError:
            sans.append(x509.DNSName(h))
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hosts[0])]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=SERVER_DAYS))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    pem, key_path = out / "server.pem", out / "server.key"
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _write_key(key, key_path)
    return pem, key_path, new_ca


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", action="append", default=[], help="extra hostname or IP (repeatable)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "certs")
    args = ap.parse_args(argv)
    hosts = ["localhost", "127.0.0.1", socket.gethostname()]
    if ip := lan_ip():
        hosts.append(ip)
    hosts += args.host
    pem, key, new_ca = make_server_cert(args.out, hosts)
    print(f"server certificate for: {', '.join(dict.fromkeys(hosts))}")
    print(f"  {pem}\n  {key}")
    print(("new" if new_ca else "existing") + f" shop authority: {args.out / 'ca.pem'}  (install on each phone)")
    print("start the server with:\n  uvicorn scanner.api:app --host 0.0.0.0 --port 8443 "
          f"--ssl-certfile {pem} --ssl-keyfile {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
