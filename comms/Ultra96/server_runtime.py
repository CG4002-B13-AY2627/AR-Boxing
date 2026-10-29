"""Common phone listener for deterministic and live sensor entry points."""
from contextlib import asynccontextmanager
import ssl
import websockets
from visualizer_protocol import MAX_MESSAGE_BYTES


@asynccontextmanager
async def serve_phones(hub, args, handler=None):
    tls = None
    if not getattr(args, "insecure_ws", False):
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(getattr(args, "phone_cert", None) or args.cert,
                            getattr(args, "phone_key", None) or args.key)
    async with websockets.serve(handler or hub.handle, args.host, getattr(args, "port", 8889), ssl=tls,
            max_size=MAX_MESSAGE_BYTES, close_timeout=2, ping_interval=5, ping_timeout=5) as server:
        yield server
