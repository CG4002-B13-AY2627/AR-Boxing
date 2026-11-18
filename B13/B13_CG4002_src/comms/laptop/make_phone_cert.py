"""
Makes the TLS certificates the iPhones use for wss://<hotspot>:8889.

Why not reuse make_cert.py's certificate? That one is valid 1960-2049 so the
clock-less ESP32 accepts it, and iOS rejects any TLS server certificate valid
for more than 825 days. Phones get their own small CA instead:

  ca.crt      install on each iPhone and turn on full trust (public)
  ca.key      PRIVATE: stays on this laptop, only to make the next server.crt
  server.crt  goes on the Ultra96 with server.key (valid 397 days)
  server.key  PRIVATE: only on the Ultra96

The server certificate names every address the phones may use: by default
the laptop hotspot (192.168.137.1, which the SSH tunnel forwards to the
board) and 127.0.0.1 (laptop-local tests). Never put a .key file on a phone,
in Git, or in a chat.

Usage (needs: pip install cryptography):
    python make_phone_cert.py [--host 192.168.137.1 --host 127.0.0.1] [--out DIR]

Default DIR is comms/.local-certs/phone-wss (ignored by Git). The script
refuses to overwrite an existing set; pass a new --out to make another.
"""
import argparse
import datetime
import ipaddress
import os
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CA_DAYS = 3650
SERVER_DAYS = 397          # well inside iOS's 825-day limit for server certificates
DEFAULT_OUT = Path(__file__).resolve().parents[1] / ".local-certs" / "phone-wss"
FILES = ("ca.crt", "ca.key", "server.crt", "server.key")


def key_usage(**on):
    flags = dict(digital_signature=False, content_commitment=False, key_encipherment=False,
                 data_encipherment=False, key_agreement=False, key_cert_sign=False,
                 crl_sign=False, encipher_only=False, decipher_only=False)
    flags.update(on)
    return x509.KeyUsage(**flags)


def make_ca(now):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CG4002-B13"),
        x509.NameAttribute(NameOID.COMMON_NAME, "CG4002-B13 phone WSS CA"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(hours=1))
        .not_valid_after(now + datetime.timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(key_usage(key_cert_sign=True, crl_sign=True), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def make_server(now, hosts, ca_key, ca_cert):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    names = []
    for host in hosts:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            names.append(x509.DNSName(host))
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CG4002-B13"),
            x509.NameAttribute(NameOID.COMMON_NAME, hosts[0]),
        ]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(hours=1))
        .not_valid_after(now + datetime.timedelta(days=SERVER_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(key_usage(digital_signature=True, key_encipherment=True), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                       critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def write(path, data, private):
    path.write_bytes(data)
    if private and os.name == "posix":
        path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", action="append",
                        help="address the phones use; repeat for more (default: 192.168.137.1 and 127.0.0.1)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    hosts = args.host or ["192.168.137.1", "127.0.0.1"]

    args.out.mkdir(parents=True, exist_ok=True)
    existing = [name for name in FILES if (args.out / name).exists()]
    if existing:
        raise SystemExit(f"{args.out} already has {', '.join(existing)}; "
                         "pick a new --out instead of overwriting a CA phones may trust")

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key, ca_cert = make_ca(now)
    server_key, server_cert = make_server(now, hosts, ca_key, ca_cert)

    pem = serialization.Encoding.PEM
    private = dict(encoding=pem, format=serialization.PrivateFormat.PKCS8,
                   encryption_algorithm=serialization.NoEncryption())
    write(args.out / "ca.crt", ca_cert.public_bytes(pem), private=False)
    write(args.out / "ca.key", ca_key.private_bytes(**private), private=True)
    write(args.out / "server.crt", server_cert.public_bytes(pem), private=False)
    write(args.out / "server.key", server_key.private_bytes(**private), private=True)

    print(f"Wrote {', '.join(FILES)} to {args.out}")
    print(f"server.crt covers {', '.join(hosts)}; valid until "
          f"{server_cert.not_valid_after_utc:%Y-%m-%d}")
    print("Next: copy server.crt and server.key to the Ultra96 (scp), and install")
    print("ca.crt on each iPhone (AirDrop or mail it), then Settings > General > About >")
    print("Certificate Trust Settings > turn on full trust. ca.key and server.key stay private.")


if __name__ == "__main__":
    main()
