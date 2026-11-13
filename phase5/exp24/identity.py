"""Bounded exp24 teaching contract for exact caller-side cache identity.

All revisions and identities are caller-generated metadata. ``tenant_id`` names
the caller's tenant/isolation domain; it is not authenticated here. The position/
attention namespace must identify positions, RoPE settings, and attention masks.
Modality identities describe the exact ordered non-text inputs; an explicit
empty list/tuple means text-only. Nothing is inferred from prompt text.

Equality covers the entire token prefix and every metadata field. Different
layout labels always differ, even if a caller believes them compatible; there
is no partial-prefix reuse. This module does not inspect actual model KV,
verify payload bytes, implement an importer, or enforce Store ACLs. Reuse
eligibility additionally requires two explicit caller attestations: verified
payload hash and compatible importer. Those flags are not proofs made here.
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields
import hashlib
import json


# Version of this canonicalization/key format. The caller's schema_version is
# independently included in the hashed record and must also match exactly.
KEY_PREFIX = "exp24:cache-identity:v1:sha256:"


def _require_string(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} must be valid UTF-8") from exc


@dataclass(frozen=True)
class CacheIdentity:
    """Validated immutable metadata, with sequence inputs snapshotted as tuples.

    Required strings are opaque and preserved exactly, without trimming or
    Unicode normalization. Token IDs accept only list/tuple containers of exact
    Python integers >= 0 (never booleans). Empty token sequences are explicit
    zero-length prefixes and cannot match nonempty prefixes.
    """

    schema_version: str
    tenant_id: str
    model_revision: str
    tokenizer_revision: str
    template_revision: str
    token_ids: tuple[int, ...]
    kv_layout_revision: str
    dtype: str
    tensor_parallel_partition: str
    position_attention_namespace: str
    modality_identity: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in fields(self):
            if field.name not in ("token_ids", "modality_identity"):
                _require_string(getattr(self, field.name), field.name)

        if not isinstance(self.token_ids, (list, tuple)):
            raise ValueError("token_ids must be a list or tuple of integers >= 0")
        tokens = tuple(self.token_ids)
        if any(type(token) is not int or token < 0 for token in tokens):
            raise ValueError("token_ids must contain integers >= 0, never booleans")

        if not isinstance(self.modality_identity, (list, tuple)):
            raise ValueError("modality_identity must be an explicit list or tuple")
        modalities = tuple(self.modality_identity)
        for identity in modalities:
            _require_string(identity, "modality_identity item")

        object.__setattr__(self, "token_ids", tokens)
        object.__setattr__(self, "modality_identity", modalities)

    @classmethod
    def from_mapping(cls, record: Mapping[str, object]) -> "CacheIdentity":
        """Reject missing/unknown keys and malformed values; supply no defaults."""
        if not isinstance(record, Mapping):
            raise ValueError("identity must be a mapping")
        snapshot = dict(record)
        required = {field.name for field in fields(cls)}
        missing = required - snapshot.keys()
        unknown = snapshot.keys() - required
        if missing or unknown:
            raise ValueError(
                f"identity keys: missing={sorted(missing)!r}, "
                f"unknown={sorted(unknown, key=repr)!r}"
            )
        return cls(**snapshot)

    def canonical_json(self) -> bytes:
        """UTF-8 JSON: sorted keys, compact separators, arrays in exact order."""
        record = {field.name: getattr(self, field.name) for field in fields(self)}
        return json.dumps(
            record, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")

    def cache_key(self) -> str:
        """Versioned SHA-256 identity key; this is not a payload integrity hash."""
        return KEY_PREFIX + hashlib.sha256(self.canonical_json()).hexdigest()


def reuse_eligible(
    cached: CacheIdentity,
    requested: CacheIdentity,
    *,
    payload_hash_verified: bool = False,
    importer_compatible: bool = False,
) -> bool:
    """Require full metadata equality AND both literal boolean attestations.

    Omitted/false flags deny eligibility. Malformed flags or identity objects
    raise ValueError, so truthy strings/integers cannot silently authorize reuse.
    """
    if not isinstance(cached, CacheIdentity) or not isinstance(requested, CacheIdentity):
        raise ValueError("cached and requested must be validated CacheIdentity objects")
    for name, flag in (("payload_hash_verified", payload_hash_verified),
                       ("importer_compatible", importer_compatible)):
        if type(flag) is not bool:
            raise ValueError(f"{name} must be an explicit boolean")
    return cached == requested and payload_hash_verified and importer_compatible
