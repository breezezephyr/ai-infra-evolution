"""Frozen caller-side examples; no model, KV importer, ACL, or Store is run."""

from dataclasses import FrozenInstanceError
from itertools import product
from types import MappingProxyType
import hashlib

import pytest


# Immutable inputs: the empty modality tuple explicitly means text-only here.
BASE = MappingProxyType({
    "schema_version": "1",
    "tenant_id": "租户/甲",
    "model_revision": "model@001",
    "tokenizer_revision": "tokenizer@001",
    "template_revision": "template@001",
    "token_ids": (1, 42, 0, 2048),
    "kv_layout_revision": "kv@001",
    "dtype": "float16",
    "tensor_parallel_partition": "tp=2/rank=0",
    "position_attention_namespace": "rope=base10000/positions=0..3/mask=causal",
    "modality_identity": (),
})

FROZEN_CASES = (
    ("unchanged", None, None, True),
    ("schema", "schema_version", "2", False),
    ("tenant", "tenant_id", "租户/乙", False),
    ("model", "model_revision", "model@002", False),
    ("tokenizer", "tokenizer_revision", "tokenizer@002", False),
    ("template", "template_revision", "template@002", False),
    ("tokens", "token_ids", (1, 43, 0, 2048), False),
    ("layout", "kv_layout_revision", "kv@002", False),
    ("dtype", "dtype", "bfloat16", False),
    ("partition", "tensor_parallel_partition", "tp=2/rank=1", False),
    ("position_attention", "position_attention_namespace", "rope=base20000/positions=0..3/mask=causal", False),
    ("modality", "modality_identity", ("image:sha256:example-a",), False),
)

CANONICAL_UTF8 = (
    '{"dtype":"float16","kv_layout_revision":"kv@001","modality_identity":[],'
    '"model_revision":"model@001","position_attention_namespace":'
    '"rope=base10000/positions=0..3/mask=causal","schema_version":"1",'
    '"template_revision":"template@001","tenant_id":"租户/甲",'
    '"tensor_parallel_partition":"tp=2/rank=0","token_ids":[1,42,0,2048],'
    '"tokenizer_revision":"tokenizer@001"}'
).encode("utf-8")


def make_identity(**changes):
    from identity import CacheIdentity

    return CacheIdentity.from_mapping(dict(BASE, **changes))


@pytest.mark.parametrize("name,field,value,expected", FROZEN_CASES,
                         ids=[case[0] for case in FROZEN_CASES])
def test_twelve_frozen_full_identity_cases(name, field, value, expected):
    from identity import reuse_eligible

    cached = make_identity()
    requested = make_identity(**({field: value} if field else {}))
    assert (cached == requested) is expected
    assert (cached.cache_key() == requested.cache_key()) is expected
    assert reuse_eligible(cached, requested, payload_hash_verified=True,
                          importer_compatible=True) is expected


def test_canonical_utf8_json_and_versioned_sha256_key():
    identity = make_identity()
    assert identity.canonical_json() == CANONICAL_UTF8
    assert identity.cache_key() == (
        "exp24:cache-identity:v1:sha256:" + hashlib.sha256(CANONICAL_UTF8).hexdigest()
    )


def test_mapping_order_does_not_change_identity():
    from identity import CacheIdentity

    pairs = list(BASE.items())
    for offset in range(len(pairs)):
        reordered = dict(reversed(pairs[offset:] + pairs[:offset]))
        identity = CacheIdentity.from_mapping(reordered)
        assert identity.canonical_json() == CANONICAL_UTF8
        assert identity.cache_key() == make_identity().cache_key()


def test_same_text_with_different_tokens_is_not_reusable():
    from identity import reuse_eligible

    # Caller-supplied tokenizations of the same text; no tokenizer is executed.
    text_and_tokens = (("hello", (10, 20)), ("hello", (30,)))
    assert text_and_tokens[0][0] == text_and_tokens[1][0]
    cached = make_identity(token_ids=text_and_tokens[0][1])
    requested = make_identity(token_ids=text_and_tokens[1][1])
    assert cached.cache_key() != requested.cache_key()
    assert not reuse_eligible(cached, requested, payload_hash_verified=True,
                              importer_compatible=True)


@pytest.mark.parametrize("tokens", [(1, 42), (1, 42, 0, 2048, 5),
                                  (2048, 0, 42, 1), (1, 42, 42, 2048), ()])
def test_partial_extended_reordered_and_empty_prefixes_do_not_match(tokens):
    from identity import reuse_eligible

    cached, requested = make_identity(), make_identity(token_ids=tokens)
    assert cached.cache_key() != requested.cache_key()
    assert not reuse_eligible(cached, requested, payload_hash_verified=True,
                              importer_compatible=True)


@pytest.mark.parametrize("namespace", [
    "rope=base10000/positions=1..4/mask=causal",
    "rope=base10000/positions=0..3/mask=bidirectional",
])
def test_position_offsets_and_attention_masks_are_part_of_identity(namespace):
    assert make_identity(position_attention_namespace=namespace).cache_key() != make_identity().cache_key()


STRING_FIELDS = tuple(key for key in BASE if key not in ("token_ids", "modality_identity"))


@pytest.mark.parametrize("field", STRING_FIELDS)
@pytest.mark.parametrize("bad", ["", " \t\n", None, 1, True, [], {}, "\ud800"])
def test_required_strings_are_validated_without_coercion(field, bad):
    with pytest.raises(ValueError, match=field):
        make_identity(**{field: bad})


@pytest.mark.parametrize("bad", [None, "1,2", b"12", 1, True, {1, 2}, {"a": 1},
                                [-1], [True], [False], [1, True], [1.0], ["1"], [None], [[1]]])
def test_token_ids_require_an_ordered_list_or_tuple_of_nonnegative_integers(bad):
    with pytest.raises(ValueError, match="token_ids"):
        make_identity(token_ids=bad)


def test_zero_tokens_are_valid_and_list_tuple_inputs_are_equivalent():
    assert make_identity(token_ids=[0, 1]) == make_identity(token_ids=(0, 1))
    assert make_identity(token_ids=[]).canonical_json() == make_identity(token_ids=()).canonical_json()


@pytest.mark.parametrize("bad", [None, "", "image:a", 0, False, {}, {"image:a"},
                                [""], ["  "], [None], [1], [True], ["\ud800"], [["image:a"]]])
def test_modality_requires_explicit_ordered_identities_even_when_empty(bad):
    with pytest.raises(ValueError, match="modality_identity"):
        make_identity(modality_identity=bad)


def test_modality_content_and_order_are_exact():
    a = make_identity(modality_identity=["image:a", "audio:b"])
    assert a == make_identity(modality_identity=("image:a", "audio:b"))
    assert a.cache_key() != make_identity(modality_identity=("image:c", "audio:b")).cache_key()
    assert a.cache_key() != make_identity(modality_identity=("audio:b", "image:a")).cache_key()
    assert make_identity(modality_identity=[]).canonical_json() == CANONICAL_UTF8


@pytest.mark.parametrize("field", tuple(BASE))
def test_every_key_is_required(field):
    from identity import CacheIdentity

    record = dict(BASE)
    del record[field]
    with pytest.raises(ValueError, match=field):
        CacheIdentity.from_mapping(record)


@pytest.mark.parametrize("extra", ["text", "semantic_match", "tenant", "payload_hash_verified", 1])
def test_unknown_keys_are_rejected(extra):
    from identity import CacheIdentity

    with pytest.raises(ValueError, match="unknown"):
        CacheIdentity.from_mapping({**BASE, extra: "ignored?"})


@pytest.mark.parametrize("record", [None, [], list(BASE.items()), "hello", True])
def test_top_level_must_be_a_mapping(record):
    from identity import CacheIdentity

    with pytest.raises(ValueError, match="mapping"):
        CacheIdentity.from_mapping(record)


def test_text_only_input_cannot_create_an_identity():
    from identity import CacheIdentity

    with pytest.raises(ValueError):
        CacheIdentity.from_mapping({"text": "hello"})


def test_identity_snapshots_lists_and_is_immutable():
    from identity import CacheIdentity

    tokens, modalities = [1, 42, 0, 2048], []
    source = dict(BASE, token_ids=tokens, modality_identity=modalities)
    identity = CacheIdentity.from_mapping(source)
    key = identity.cache_key()
    tokens.append(99)
    modalities.append("image:a")
    source["tenant_id"] = "other-tenant"
    assert identity.cache_key() == key
    assert identity.token_ids == (1, 42, 0, 2048)
    assert identity.modality_identity == ()
    with pytest.raises(FrozenInstanceError):
        identity.tenant_id = "other-tenant"


def test_direct_construction_cannot_bypass_validation():
    from identity import CacheIdentity

    with pytest.raises(ValueError, match="token_ids"):
        CacheIdentity(**dict(BASE, token_ids=[True]))
    with pytest.raises(ValueError, match="tenant_id"):
        CacheIdentity(**dict(BASE, tenant_id=""))


@pytest.mark.parametrize("field,changed", [("tenant_id", " 租户/甲 "),
                                         ("template_revision", "é"),
                                         ("template_revision", "e\u0301")])
def test_strings_are_not_trimmed_or_semantically_normalized(field, changed):
    baseline = make_identity(**{field: "é" if field == "template_revision" else BASE[field]})
    candidate = make_identity(**{field: changed})
    assert (baseline.cache_key() == candidate.cache_key()) is (changed == getattr(baseline, field))


@pytest.mark.parametrize("payload_ok,importer_ok", list(product((False, True), repeat=2)))
def test_reuse_requires_payload_integrity_and_explicit_importer_compatibility(payload_ok, importer_ok):
    from identity import reuse_eligible

    identity = make_identity()
    assert reuse_eligible(identity, make_identity(), payload_hash_verified=payload_ok,
                          importer_compatible=importer_ok) is (payload_ok and importer_ok)


@pytest.mark.parametrize("flags", [{}, {"payload_hash_verified": True},
                                  {"importer_compatible": True}])
def test_missing_flags_deny_reuse(flags):
    from identity import reuse_eligible

    assert not reuse_eligible(make_identity(), make_identity(), **flags)


@pytest.mark.parametrize("flag", ["payload_hash_verified", "importer_compatible"])
@pytest.mark.parametrize("bad", [1, 0, "true", "false", None, [], {}])
def test_truthy_values_cannot_impersonate_explicit_boolean_flags(flag, bad):
    from identity import reuse_eligible

    flags = {"payload_hash_verified": True, "importer_compatible": True, flag: bad}
    with pytest.raises(ValueError, match=flag):
        reuse_eligible(make_identity(), make_identity(), **flags)


@pytest.mark.parametrize("bad", [None, dict(BASE), "exp24:cache-identity:some-key"])
@pytest.mark.parametrize("side", ["cached", "requested"])
def test_reuse_requires_validated_identity_objects_on_both_sides(side, bad):
    from identity import reuse_eligible

    identities = {"cached": make_identity(), "requested": make_identity(), side: bad}
    with pytest.raises(ValueError, match="CacheIdentity"):
        reuse_eligible(**identities, payload_hash_verified=True, importer_compatible=True)
