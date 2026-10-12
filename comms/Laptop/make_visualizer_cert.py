"""Create a separate iPhone-trusted demo CA and Ultra96 WSS server certificate.

Run on a trusted development machine with OpenSSL. The output directory must
not already exist. Never copy ca.key to Ultra96 or commit any .key file.

Example:
    python make_visualizer_cert.py --host 192.168.137.1 \
        --out ../Ultra96/wss-certs
"""

import argparse
import ipaddress
import subprocess
from pathlib import Path


def run(*args, cwd):
    subprocess.run(
        ["openssl", *args], cwd=cwd, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.137.1",
                        help="exact IP address or DNS name used by the iPhone")
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parents[1] / "Ultra96" / "wss-certs")
    args = parser.parse_args()
    try:
        address = ipaddress.ip_address(args.host)
        san = "IP:" + str(address)
        verify_flag = "-verify_ip"
    except ValueError:
        if not args.host or any(char.isspace() for char in args.host):
            parser.error("host must be an IP address or DNS name")
        san = "DNS:" + args.host
        verify_flag = "-verify_hostname"

    output = args.out.resolve()
    if output.exists():
        parser.error(f"output already exists; refusing to overwrite certificates: {output}")
    output.mkdir(parents=True)

    extensions = output / "server.ext"
    extensions.write_text(
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
        "subjectAltName=" + san + "\n",
        encoding="ascii",
    )
    try:
        run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256",
            "-days", "365", "-keyout", "ca.key", "-out", "ca.crt",
            "-subj", "/CN=CG4002-B13 Visualizer Demo CA",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign", cwd=output)
        run("req", "-new", "-newkey", "rsa:2048", "-nodes",
            "-keyout", "server.key", "-out", "server.csr",
            "-subj", "/CN=" + args.host, cwd=output)
        run("x509", "-req", "-in", "server.csr", "-CA", "ca.crt",
            "-CAkey", "ca.key", "-CAcreateserial", "-out", "server.crt",
            "-days", "90", "-sha256", "-extfile", "server.ext", cwd=output)
        run("verify", "-CAfile", "ca.crt", verify_flag, args.host,
            "server.crt", cwd=output)
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"certificate generation failed in {output}: {error}")

    for name in ("ca.key", "server.key"):
        (output / name).chmod(0o600)
    print(f"WSS certificate for {args.host}: {output}")
    print("Install ca.crt on each test iPhone and enable full SSL trust.")
    print("Copy only server.crt and server.key to Ultra96; keep ca.key offline.")
    print("Private keys and the entire wss-certs folder are ignored by Git.")


if __name__ == "__main__":
    main()
