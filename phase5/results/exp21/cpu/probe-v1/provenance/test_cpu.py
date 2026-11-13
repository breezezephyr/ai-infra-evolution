"""Recorder regressions: omissions and observation failures must never pass."""
import copy
import json
import pytest
import deepseek_recipe as recipe
import cpu


def case(expect=None):
    return {'id': 'chat-basic', 'protocol': 'chat', 'family': 'baseline',
            'input': {'model': 'DeepSeek-V4.1-Flash', 'thinking': {'type': 'disabled'},
                      'messages': [{'role': 'user', 'content': 'Return JSON.'}]},
            'expect': expect or {'outcome': 'accepted', 'constraint_kind': None}}


def test_missing_row_keeps_configured_denominator_and_fails():
    summary = cpu.summarize([case()], [])
    assert summary['configured'] == 1
    assert summary['passed'] == 0
    assert summary['missing_ids'] == ['chat-basic']
    assert not summary['ok']


def test_duplicate_row_cannot_inflate_pass_count():
    c = case(); row = cpu.run_case(c)
    summary = cpu.summarize([c], [row, row])
    assert summary['duplicate_ids'] == ['chat-basic']
    assert summary['passed'] == 0
    assert not summary['ok']


def test_unconfigured_row_is_an_integrity_error():
    row = cpu.run_case(case())
    assert cpu.summarize([], [row])['extra_ids'] == ['chat-basic']
    assert not cpu.summarize([], [row])['ok']


def test_accepted_request_records_constraint_and_unmeasured_execution():
    c = case(); c['input']['response_format'] = {'type': 'json_object'}
    c['expect']['constraint_kind'] = 'json'
    row = cpu.run_case(c)
    assert row['outcome'] == 'accepted'
    assert row['snapshot']['output_constraint'] == {'kind': 'json', 'schema': ''}
    assert row['execution']['sampling_executed'] is False
    assert row['execution']['schema_instance_validated'] is False
    assert row['verdict'] == 'pass'


def test_expected_native_rejection_has_error_stage_and_is_not_acceptance():
    c = case({'outcome': 'rejected', 'stage': 'convert', 'error_type': 'ConversionError',
              'status_code': 400, 'message_contains': "word 'json'"})
    c['input']['messages'][0]['content'] = 'Hello'
    c['input']['response_format'] = {'type': 'json_object'}
    row = cpu.run_case(c)
    assert row['outcome'] == 'rejected' and row['verdict'] == 'pass'
    assert row['error']['stage'] == 'convert'
    summary = cpu.summarize([c], [row])
    assert summary['accepted'] == 0
    assert summary['expected_rejections'] == 1


def test_wrong_rejection_type_message_or_stage_does_not_pass():
    c = case({'outcome': 'rejected', 'stage': 'parse', 'error_type': 'ValueError',
              'message_contains': 'deliberate other error'})
    c['input']['model'] = 'unregistered'
    assert cpu.run_case(c)['verdict'] == 'fail'


def test_observer_exception_never_counts_as_expected_rejection():
    c = case({'outcome': 'rejected', 'stage': 'convert', 'error_type': 'ConversionError',
              'message_contains': "word 'json'"})
    def observe(_):
        invalid = copy.deepcopy(case()['input'])
        invalid['messages'][0]['content'] = 'Hello'
        invalid['response_format'] = {'type': 'json_object'}
        recipe.ChatCompletionRequest(invalid).convert(recipe.ConversionOptions())
    row = cpu.run_case(c, observer=observe)
    assert row['outcome'] == 'unexpected_error'
    assert row['error']['stage'] == 'observe'
    assert row['verdict'] == 'fail'
    assert cpu.summarize([c], [row])['expected_rejections'] == 0


def test_tampered_case_or_record_is_not_silently_reused():
    c = case(); row = cpu.run_case(c)
    c['input']['messages'][0]['content'] = 'Changed input'
    summary = cpu.summarize([c], [row])
    assert summary['identity_mismatch_ids'] == ['chat-basic']
    assert summary['passed'] == 0


def test_missing_expectation_is_unknown_not_pass():
    c = case(); c.pop('expect')
    assert cpu.run_case(c)['verdict'] == 'unknown'


@pytest.mark.parametrize('kind', ['tool_call', 'tool_call_required', 'ebnf', 'other'])
def test_unmapped_kinds_are_explicitly_rejected(kind):
    mapping = cpu.backend_mapping({'kind': kind, 'schema': '[]'})
    assert mapping['decision'] == 'reject'
    assert mapping['so_args'] is None
    assert mapping['executed'] is False


def test_empty_any_json_constraint_is_not_forwarded_as_empty_json_schema():
    mapping = cpu.backend_mapping({'kind': 'json', 'schema': ''})
    assert mapping['decision'] == 'reject'
    assert mapping['so_args'] is None


@pytest.mark.parametrize('kind,schema', [('json', '{"type":"object"}'), ('regex', '[A-Z]+')])
def test_schema_and_regex_mappings_are_only_unexecuted_candidates(kind, schema):
    mapping = cpu.backend_mapping({'kind': kind, 'schema': schema})
    assert mapping['decision'] == 'candidate'
    assert mapping['so_args'] == {'schema_type': kind, 'schema': schema}
    assert mapping['executed'] is False


def test_constraint_none_maps_to_no_backend_constraint():
    mapping = cpu.backend_mapping(None)
    assert mapping['decision'] == 'none'
    assert mapping['so_args'] is None


def test_bad_protocol_is_recorder_error_not_a_native_rejection():
    c = case(); c['protocol'] = 'bad'
    row = cpu.run_case(c)
    assert row['outcome'] == 'unexpected_error'
    assert row['verdict'] == 'fail'


def test_strict_schema_records_original_and_normalized_constraint_separately():
    c = case(); c['input']['response_format'] = {'type': 'json_schema', 'json_schema': {
        'schema': {'type': 'object', 'properties': {'city': {'type': 'string'}}}, 'strict': True}}
    c['expect'] = {'outcome': 'accepted', 'constraint_kind': 'json', 'facts': {
        'constraint_schema_json': {'type': 'object', 'properties': {'city': {'type': 'string'}},
                                   'required': ['city'], 'additionalProperties': False}}}
    row = cpu.run_case(c)
    assert row['verdict'] == 'pass'
    assert 'required' not in row['snapshot']['response_schema']
    assert row['snapshot']['constraint_schema_json']['required'] == ['city']


def test_corrupt_record_with_missing_snapshot_cannot_crash_or_pass_audit():
    c = case(); row = cpu.run_case(c); row.pop('snapshot')
    summary = cpu.summarize([c], [row])
    assert not summary['ok']
    assert summary['unknown'] == 1


def test_parse_fixture_does_not_validate_instance_against_declared_schema():
    c = case(); c['input']['response_format'] = {'type': 'json_schema', 'json_schema': {
        'schema': {'type': 'object', 'properties': {'city': {'type': 'string'}}, 'required': ['city']}}}
    row = cpu.parse_probe(c, '{"city":4}')
    assert row['text'] == '{"city":4}'
    assert row['json_value'] == {'city': 4}
    assert row['error'] is None
    assert row['sampling_executed'] is False
    assert row['schema_instance_validated'] is False
