"""Validation helpers for user-controlled outbound HTTP destinations."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

MAX_REDIRECTS = 5


def _is_public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return bool(address.is_global)


async def validate_outbound_http_url(url: str) -> str:
    """Reject non-HTTP and non-public destinations before an outbound request."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are allowed")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("URLs with embedded credentials are not allowed")

    hostname = parsed.hostname.rstrip(".")
    try:
        if not _is_public_ip(hostname):
            raise ValueError("Outbound URL must resolve to a public IP address")
        return url
    except ValueError as exc:
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise exc

    loop = asyncio.get_running_loop()
    try:
        addresses = await loop.run_in_executor(
            None,
            lambda: socket.getaddrinfo(
                hostname,
                parsed.port,
                type=socket.SOCK_STREAM,
            ),
        )
    except socket.gaierror as exc:
        raise ValueError("Outbound URL hostname could not be resolved") from exc

    resolved_ips = {item[4][0] for item in addresses}
    if not resolved_ips or any(not _is_public_ip(value) for value in resolved_ips):
        raise ValueError("Outbound URL must resolve only to public IP addresses")
    return url


async def get_with_safe_redirects(
    client: httpx.AsyncClient,
    url: str,
) -> httpx.Response:
    """Fetch a URL while validating every redirect destination."""
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        await validate_outbound_http_url(current_url)
        response = await client.get(current_url, follow_redirects=False)
        if not response.is_redirect:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        current_url = urljoin(str(response.url), location)
    raise ValueError(f"Outbound URL exceeded {MAX_REDIRECTS} redirects")
