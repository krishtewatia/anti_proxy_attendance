"""The address a request really came from.

Behind a reverse proxy every request reaches the backend from the proxy's
address, so the client's own address has to be read from X-Forwarded-For.
That header is just text the sender wrote: it is believed only when the
request arrived directly from a proxy listed in TRUSTED_PROXY_IPS. From any
other peer the header is ignored and the peer's own address is used, so
nobody outside can choose the address that rate limits and audit entries see.
"""

from ipaddress import ip_address, ip_network

from fastapi import Request

from app.core.config import settings


def _is_trusted_proxy(peer: str) -> bool:
    try:
        address = ip_address(peer)
    except ValueError:
        return False
    for entry in settings.TRUSTED_PROXY_IPS:
        try:
            if address in ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(request: Request) -> str:
    """Address of the client, for rate limiting and audit entries."""
    peer = request.client.host if request.client else "unknown"
    if not _is_trusted_proxy(peer):
        return peer

    # The trusted proxy writes the address it saw as the last entry. Anything
    # before it was supplied by the client and is not believed.
    forwarded = request.headers.get("x-forwarded-for", "")
    last = forwarded.split(",")[-1].strip()
    try:
        return str(ip_address(last))
    except ValueError:
        return peer
