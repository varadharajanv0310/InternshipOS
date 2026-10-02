"""Public ingestion contract. No network or database work at import time."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass
class Source:
    provider: str
    url: str
    config: dict = field(default_factory=dict)
    company_name: str = ""
    company_domain: str = ""
    id: str | None = None

    @classmethod
    def from_value(cls, value: Any) -> "Source":
        if isinstance(value, cls):
            return value
        def get(obj, key, default=None):
            return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
        company = get(value, "company", {}) or {}
        config = dict(get(value, "config", {}) or {})
        for key in ("tenant", "board"):
            if get(value, key):
                config.setdefault(key, get(value, key))
        return cls(
            provider=str(get(value, "provider", "generic")).lower(),
            url=str(get(value, "url", get(value, "board_url", ""))),
            config=config,
            company_name=get(value, "company_name", get(company, "name", "")) or "",
            company_domain=get(value, "company_domain", get(company, "domain", "")) or "",
            id=get(value, "id"),
        )

    @property
    def origin(self):
        u = urlsplit(self.url)
        return f"{u.scheme}://{u.netloc}"


@dataclass
class CollectionResult:
    jobs: list[dict] = field(default_factory=list)
    complete: bool = False
    error: str | None = None
    coverage_scope: str = "full"
    observed_count: int = 0
    metadata: dict = field(default_factory=dict)

    def as_dict(self):
        from dataclasses import asdict
        return asdict(self)


class SourceError(Exception):
    """An actionable source failure, never a successful empty inventory."""


class SchemaError(SourceError):
    pass
