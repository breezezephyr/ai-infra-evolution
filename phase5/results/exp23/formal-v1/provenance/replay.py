"""Synthetic teaching replay; not a DSpark implementation or model inference."""
import math

POLICIES = ('fixed0','fixed1','fixed3','fixed5','candidate')


def verify_round(truth, cursor, drafts):
    """Compare one proposed prefix with a supplied oracle; no stochastic sampler."""
    if not 0 <= cursor < len(truth) or len(drafts)>len(truth)-cursor:
        raise ValueError('invalid cursor or draft span')
    accepted=0
    while accepted<len(drafts) and drafts[accepted]==truth[cursor+accepted]:
        accepted+=1
    correction=bonus=direct=0
    if accepted<len(drafts):
        committed=truth[cursor:cursor+accepted+1]
        correction=1
    else:
        end=min(cursor+accepted+1,len(truth))
        committed=truth[cursor:end]
        if not drafts:direct=1
        else:bonus=int(end>cursor+accepted)
    return {'cursor':cursor,'next_cursor':cursor+len(committed),'drafts':list(drafts),
            'committed':committed,'accepted_draft_tokens':accepted,
            'discarded_draft_tokens':len(drafts)-accepted,'correction_tokens':correction,
            'bonus_tokens':bonus,'target_direct_tokens':direct,
            'verification_positions':min(len(drafts)+1,len(truth)-cursor)}


def select_length(confidence, cursor, policy):
    if policy!='candidate':return min(int(policy[-1]),len(confidence)-cursor)
    cumulative=1.0;length=0
    for probability in confidence[cursor:cursor+5]:
        cumulative*=probability
        if cumulative < .8:break
        length+=1
    return length


def run_trace(truth, correct, confidence, policy, cost):
    if (not truth or truth[-1]!=0 or any(type(i)is not int or i<=0 for i in truth[:-1])
        or len(truth)!=len(correct) or len(truth)!=len(confidence)
        or any(type(x)is not bool for x in correct)
        or any(not isinstance(p,(float,int)) or not math.isfinite(p) or p<0 or p>1 for p in confidence)
        or policy not in POLICIES or len(cost)!=3 or any(type(x)is not int or x<0 for x in cost)):
        raise ValueError('invalid frozen trace, policy or cost model')
    base,per_position,per_draft=cost
    cursor=0;committed=[];rounds=[]
    while cursor<len(truth):
        length=select_length(confidence,cursor,policy)
        drafts=[truth[i] if correct[i] else truth[i]+100000 for i in range(cursor,cursor+length)]
        row=verify_round(truth,cursor,drafts)
        row['work_points']=base+per_position*row['verification_positions']+per_draft*length
        row['synthetic_confidence']=confidence[cursor:cursor+length]
        committed.extend(row['committed']);cursor=row['next_cursor']
        assert committed==truth[:cursor] and row['committed']
        assert len(row['committed'])==row['accepted_draft_tokens']+row['correction_tokens']+row['bonus_tokens']+row['target_direct_tokens']
        rounds.append(row)
    result={'policy':policy,'committed':committed,'rounds':rounds}
    for name in ['accepted_draft_tokens','discarded_draft_tokens','verification_positions','work_points']:
        result[name]=sum(row[name] for row in rounds)
    result['draft_tokens']=sum(len(row['drafts']) for row in rounds)
    result['rejected_rounds']=sum(row['correction_tokens'] for row in rounds)
    return result
