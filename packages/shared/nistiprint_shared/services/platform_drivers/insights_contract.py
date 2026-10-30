"""Provider-neutral input to management projections and enrichment requests."""
from dataclasses import dataclass, field, asdict
import hashlib
import json


class CollectionError(Exception):
    def __init__(self, code, forbidden=False, retry_after=None):
        self.code = code
        self.forbidden = forbidden
        self.retry_after = retry_after


@dataclass(frozen=True)
class OrderInsights:
    provider: str
    account_id: int | None
    resource_id: str
    facts: dict
    missing: tuple = ()
    evidence: dict = field(default_factory=dict)
    enrichments: tuple = ()

    @property
    def version(self):
        return hashlib.sha256(json.dumps(self.facts, sort_keys=True, default=str).encode()).hexdigest()

    def to_dict(self):
        return {**asdict(self), 'version': self.version}
