"""Generate a separate local phone CA and server leaf; never edit ESP firmware."""
import argparse
import ipaddress
from pathlib import Path
import subprocess


def generate(output, hosts):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose an empty output directory; existing credentials are never overwritten")
    names = []
    for host in hosts:
        try:
            names.append("IP:" + str(ipaddress.ip_address(host)))
        except ValueError:
            if not host or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for c in host):
                raise ValueError("Invalid certificate hostname")
            names.append("DNS:" + host)
    if not names:
        raise ValueError("Supply at least one --host matching the phone-facing URL")
    output.mkdir(parents=True, exist_ok=True)
    def openssl(*args):
        subprocess.run(["openssl", *args], cwd=output, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365",
        "-keyout", "ca.key", "-out", "ca.crt", "-subj", "/CN=CG4002 Phone Development CA",
        "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", "server.key",
        "-out", "server.csr", "-subj", "/CN="+hosts[0])
    (output / "server.ext").write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName="+",".join(names)+"\n")
    openssl("x509", "-req", "-in", "server.csr", "-CA", "ca.crt", "-CAkey", "ca.key",
        "-CAcreateserial", "-out", "server.crt", "-days", "90", "-sha256", "-extfile", "server.ext")
    openssl("verify", "-CAfile", "ca.crt", "server.crt")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host", action="append", required=True)
    args = parser.parse_args()
    generate(args.output, args.host)
    print("Created CA and matching leaf in", args.output)
    print("Install only ca.crt on phones and explicitly trust it. Keep both private keys local.")
