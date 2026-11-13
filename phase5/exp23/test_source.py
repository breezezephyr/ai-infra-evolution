import pytest
import source_probes


def test_source_boundary_uses_nextn_plus_one():
    r=source_probes.probe_config({'DEEPINFER_YOCO_PREFILL_TRUNCATION_MODE':'compact','DEEPINFER_YOCO_PREFILL_KEEP_TOKENS':'133'},128)
    assert r['backtracking']==6 and r['status']=='guard_rejected'
    r=source_probes.probe_config({'DEEPINFER_YOCO_PREFILL_TRUNCATION_MODE':'compact','DEEPINFER_YOCO_PREFILL_KEEP_TOKENS':'134'},128)
    assert r['status']=='guard_passed'


def test_zero_draft_still_has_one_backtracking_budget():
    r=source_probes.probe_config({'DEEPINFER_USE_NEXTN_DECODE':'0','DEEPINFER_YOCO_PREFILL_TRUNCATION_MODE':'mask','DEEPINFER_YOCO_PREFILL_KEEP_TOKENS':'128'},128)
    assert r['backtracking']==1 and r['status']=='guard_rejected'


def test_environment_probe_is_fresh_and_controlled():
    first=source_probes.probe_config({'DEEPINFER_MAX_BACKTRACKING_TOKENS':'20'},128)
    second=source_probes.probe_config({},128)
    assert first['backtracking']==20 and second['backtracking']==6


def test_invalid_mode_is_not_silently_turned_off():
    assert source_probes.probe_config({'DEEPINFER_YOCO_PREFILL_TRUNCATION_MODE':'invalid'},128)['status']=='parse_rejected'
