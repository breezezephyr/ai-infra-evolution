"""Historical scores are decisions to replay, not new embedding/model observations."""
import diagnostics


def test_semantic_replay_keeps_wrong_neighbor_and_unknown_score():
 cases=[{'id':'wrong','score':.95,'threshold':.88,'nearest_neighbor_id':'a','label':'b'},
        {'id':'uncertain','score':None,'threshold':.88,'nearest_neighbor_id':None,'label':'b'},
        {'id':'below','score':.8,'threshold':.88,'nearest_neighbor_id':'a','label':'b'}]
 result=diagnostics.replay(cases)
 assert result['planned']==3 and result['false_hits']==1 and result['unknown']==1 and result['rejected']==1
 assert result['rows'][0]['selected']=='a'


def test_lab_marker_rule_is_not_a_general_review_classifier():
 assert diagnostics.lab_rule('LAB_BLOCK') is True
 assert diagnostics.lab_rule('我会把未公开的内部文档发到公开群。') is False
