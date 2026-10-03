"""Bounded public HTTP transport; redirects are validated before following."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import weakref
from collections import defaultdict
from urllib.parse import urljoin, urlsplit

import httpx

from .types import SourceError

USER_AGENT = "InternshipOS/1.0 (personal public-careers reader; no account automation)"
_LOOP_HOST_LIMITS = weakref.WeakKeyDictionary()


async def validate_public_url(url: str, *, resolve_dns: bool = True) -> str:
    try:
        p = urlsplit(str(url))
        if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
            raise ValueError("HTTP(S) public URL required")
        if p.port not in {None, 80, 443}:
            raise ValueError("Nonstandard destination port is not allowed")
        host = p.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "." not in host:
            raise ValueError("Local destination is not allowed")
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            addresses = []
            if resolve_dns:
                info = await asyncio.wait_for(
                    asyncio.get_running_loop().getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM), 6
                )
                addresses = [ipaddress.ip_address(i[4][0]) for i in info]
        if any(not address.is_global for address in addresses):
            raise ValueError("Private or reserved destination is not allowed")
        return str(url)
    except (ValueError, OSError, asyncio.TimeoutError) as exc:
        raise SourceError(f"unsafe_or_unresolvable_url: {exc}") from exc


class PublicHTTP:
    def __init__(self, client: httpx.AsyncClient, *, max_requests=160, max_bytes=8_000_000,
                 resolve_dns=True, retries=2, host_concurrency=2):
        self.client = client
        self.max_requests = max_requests
        self.max_bytes = max_bytes
        self.resolve_dns = resolve_dns
        self.retries = retries
        self.requests = 0
        loop = asyncio.get_running_loop()
        self._locks = _LOOP_HOST_LIMITS.setdefault(loop, defaultdict(lambda: asyncio.Semaphore(host_concurrency)))
        self._validated = set()
        self.status_counts = defaultdict(int)

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        for redirects in range(6):
            host = urlsplit(url).netloc.lower()
            if host not in self._validated:
                await validate_public_url(url, resolve_dns=self.resolve_dns)
                self._validated.add(host)
            else:
                await validate_public_url(url, resolve_dns=False)
            for attempt in range(self.retries + 1):
                if self.requests >= self.max_requests:
                    raise SourceError("request_budget_exhausted")
                self.requests += 1
                try:
                    async with self._locks[host]:
                        request = self.client.build_request(method, url, **kwargs)
                        # Optional zstd decoders differ between runtimes. Prefer
                        # the encodings supported by Python's standard library.
                        if request.headers.get('accept-encoding') != 'identity':
                            request.headers['accept-encoding'] = 'gzip, deflate'
                        response = await self.client.send(request, stream=True, follow_redirects=False)
                        try:
                            chunks, size = [], 0
                            async for chunk in response.aiter_bytes():
                                size += len(chunk)
                                if size > self.max_bytes:
                                    raise SourceError("response_size_limit_exceeded")
                                chunks.append(chunk)
                            content = b"".join(chunks)
                        finally:
                            await response.aclose()
                        headers = {k: v for k, v in response.headers.items() if k.lower() not in {"content-encoding", "content-length", "transfer-encoding"}}
                        response = httpx.Response(response.status_code, headers=headers,
                                                  content=content, request=request)
                    self.status_counts[str(response.status_code)] += 1
                except httpx.HTTPError as exc:
                    if isinstance(exc, httpx.DecodingError):
                        kwargs['headers'] = {**kwargs.get('headers', {}), 'Accept-Encoding': 'identity'}
                    if attempt == self.retries:
                        raise SourceError(f"network_error: {type(exc).__name__}") from exc
                    await asyncio.sleep(min(2 ** attempt, 4))
                    continue
                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.retries:
                    retry = response.headers.get("retry-after", "")
                    delay = min(float(retry), 10) if retry.replace(".", "", 1).isdigit() else min(2 ** attempt, 4)
                    await asyncio.sleep(max(0, delay))
                    continue
                break
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise SourceError("redirect_without_location")
                url = urljoin(str(response.url), location)
                kwargs.pop("params", None)
                if response.status_code == 303:
                    method = "GET"
                    kwargs.pop("json", None)
                    kwargs.pop("data", None)
                continue
            if response.status_code in {401, 403, 406, 429}:
                raise SourceError(f"access_restricted_or_challenged: HTTP {response.status_code}")
            if not response.is_success:
                raise SourceError(f"http_error: HTTP {response.status_code}")
            # Only challenge-page signatures, not a JD mentioning CAPTCHA work.
            preview = response.text[:5000].lower()
            if any(x in preview for x in ('<title>just a moment', 'cf-chl-', 'recaptcha required', '<title>access denied')):
                raise SourceError("challenge_page_returned")
            return response
        raise SourceError("redirect_limit_exceeded")

    async def json(self, method, url, **kwargs):
        response = await self.request(method, url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError("invalid_json_response") from exc

    async def text(self, url, **kwargs):
        return (await self.request("GET", url, **kwargs)).text
