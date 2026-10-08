"""
Generates the self-signed certificate and private key for the TLS links, and
writes the certificate into the ESP32 firmware (ESP32_comms.ino).

Why not just `openssl req -x509`?
  The ESP32 has no real-time clock. At boot its clock reads January 1970, and
  certificate checking includes the validity dates: a normal certificate ("valid
  from today") is rejected as "not yet valid". This one is valid 1960-2049, so
  it passes whatever the ESP32's clock says. (Section 4.4 of the report says all
  devices are provisioned by us ahead of time, so a long-lived pinned
  certificate is consistent with the design.)

The certificate names the address the ESP32 connects to (the laptop's hotspot
IP, which the SSH tunnel forwards to the Ultra96). The name is written in BOTH
forms: mbedTLS on the ESP32 matches DNS-type names as text, while OpenSSL/Python
match IP-type names for IP addresses.

Usage:
    python3 make_cert.py [--host 192.168.137.1] [--ino ESP32_comms.ino]

Outputs: server.crt (public, goes on every client) and server.key (PRIVATE:
only on the Ultra96, never commit it to Git or send it anywhere).
Then copy server.crt and server.key next to comms_server.py on the Ultra96.
"""
import argparse
import datetime
import ipaddress
import re

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

BEGIN = "// BEGIN SERVER_CERT"
END = "// END SERVER_CERT"


def make(host):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CG4002-B13"),
        x509.NameAttribute(NameOID.COMMON_NAME, host),
    ])
    names = [x509.DNSName(host)]
    try:
        names.append(x509.IPAddress(ipaddress.ip_address(host)))
    except ValueError:
        pass                                            # host is a name, not an IP

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)                              # self-signed
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime(1960, 1, 1))
        .not_valid_after(datetime.datetime(2049, 12, 31, 23, 59, 59))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, key_cert_sign=True,
                                     content_commitment=False, data_encipherment=False, key_agreement=False,
                                     crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def embed(ino_path, cert_pem):
    src = open(ino_path).read()
    i0, i1 = src.find(BEGIN), src.find(END)
    if i0 == -1 or i1 == -1:
        raise SystemExit(f"{ino_path}: could not find the {BEGIN} / {END} markers")
    block = (f'{BEGIN} (written by make_cert.py, do not edit by hand)\n'
             f'const char* SERVER_CERT = R"EOF(\n{cert_pem.strip()}\n)EOF";\n')
    open(ino_path, 'w').write(src[:i0] + block + src[i1:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='192.168.137.1')
    ap.add_argument('--ino', default='ESP32_comms.ino')
    ap.add_argument('--out', default='.')
    a = ap.parse_args()

    key, cert = make(a.host)
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    open(f"{a.out}/server.crt", 'w').write(cert_pem)
    open(f"{a.out}/server.key", 'w').write(key_pem)
    print(f"wrote server.crt and server.key for {a.host}")
    print(f"valid {cert.not_valid_before_utc:%Y-%m-%d} to {cert.not_valid_after_utc:%Y-%m-%d}")
    try:
        embed(a.ino, cert_pem)
        print(f"embedded the certificate in {a.ino}")
    except FileNotFoundError:
        print(f"({a.ino} not found here, certificate not embedded)")
    print("keep server.key private: only the Ultra96 needs it")


if __name__ == "__main__":
    main()
