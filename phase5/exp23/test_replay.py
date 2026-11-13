import itertools
import pytest
import replay


def test_first_rejection_discards_the_whole_uncommitted_suffix():
    row=replay.verify_round([10,11,12,0],0,[0,11,12])
    assert row['committed']==[10] and row['accepted_draft_tokens']==0
    assert row['discarded_draft_tokens']==3 and row['verification_positions']==4


def test_all_accepted_has_bonus_but_never_runs_past_eos():
    first=replay.verify_round([10,11,12,0],0,[10,11])
    assert first['committed']==[10,11,12] and first['bonus_tokens']==1
    last=replay.verify_round([10,11,12,0],3,[0])
    assert last['committed']==[0] and last['bonus_tokens']==0 and last['verification_positions']==1


def test_last_draft_rejection_has_no_bonus():
    row=replay.verify_round([10,11,12,0],0,[10,11,99])
    assert row['committed']==[10,11,12] and row['bonus_tokens']==0
    assert row['accepted_draft_tokens']==2 and row['correction_tokens']==1


def test_early_rejection_still_charges_all_planned_verification_positions():
    row=replay.run_trace([10,11,12,13,14,0],[False]*6,[.99]*6,'fixed5',(800,100,25))
    assert row['rounds'][0]['work_points']==800+600+5*25
    assert row['committed']==[10,11,12,13,14,0]


def test_zero_draft_is_a_complete_target_only_baseline():
    r=replay.run_trace([10,11,0],[False]*3,[.99]*3,'fixed0',(800,100,25))
    assert len(r['rounds'])==3 and r['draft_tokens']==0 and r['work_points']==2700


def test_low_confidence_correct_drafts_can_lose_setup_amortization():
    args=([10,11,12,13,14,15,0],[True]*7,[.1]*7)
    fixed=replay.run_trace(*args,'fixed5',(800,100,25))
    cautious=replay.run_trace(*args,'candidate',(800,100,25))
    assert cautious['work_points']>fixed['work_points']
    assert cautious['committed']==fixed['committed']


def test_high_confidence_wrong_drafts_do_not_become_committed_tokens():
    r=replay.run_trace([10,11,0],[False]*3,[.99]*3,'candidate',(800,100,25))
    assert r['committed']==[10,11,0] and r['discarded_draft_tokens']>0


@pytest.mark.parametrize('n',range(1,8))
def test_every_short_acceptance_mask_preserves_the_target_sequence(n):
    truth=list(range(10,10+n-1))+[0]
    for mask in itertools.product([True,False],repeat=n):
        for policy in ['fixed0','fixed1','fixed3','fixed5','candidate']:
            r=replay.run_trace(truth,list(mask),[.95 if x else .2 for x in mask],policy,(800,100,25))
            assert r['committed']==truth
            assert sum(len(x['committed']) for x in r['rounds'])==n
            assert r['draft_tokens']==r['accepted_draft_tokens']+r['discarded_draft_tokens']
            assert sum(x['verification_positions'] for x in r['rounds'])==r['verification_positions']


@pytest.mark.parametrize('confidence',[[float('nan')],[1.1],[-.1]])
def test_invalid_confidence_is_rejected(confidence):
    with pytest.raises(ValueError):replay.run_trace([0],[True],confidence,'candidate',(800,100,25))


def test_invalid_input_or_cost_cannot_enter_a_replay():
    for truth,mask,confidence,policy,cost in [([1], [True],[.9],'fixed1',(800,100,25)),
            ([0],[True,False],[.9],'fixed1',(800,100,25)),
            ([0],[True],[.9],'unknown',(800,100,25)),([0],[True],[.9],'fixed1',(-1,100,25))]:
        with pytest.raises(ValueError):replay.run_trace(truth,mask,confidence,policy,cost)
