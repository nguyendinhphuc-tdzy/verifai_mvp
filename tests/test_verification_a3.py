"""A3 evidence reconciliation: ground truth not inferred from multiple votes."""
from dataclasses import dataclass
import json
from verifai_core.verification import build_verification_report, attach_evidence_ids, VERIFICATION_VERSION


@dataclass
class Ev:
    kind: str
    timestamp: float
    metadata: dict


def price(status, amount=None, kind='ocr', timestamp=0., reason='test'):
    return Ev(kind,timestamp,{'price_v3':{'status':status, 'compared_vnd':amount,
                'reason':reason,'mentions':[{'amount_vnd':amount}]}})


def claim(state, text='chữa khỏi hoàn toàn', kind='ocr', timestamp=0.):
    return Ev(kind,timestamp,{'claim_v3':{'mentions':[{'phrase':text,'state':state}]}})


FULL={'ocr':'ok','asr':'ok','vlm':'ok'}
TRUTH={'reference_status':'reviewed','revision':3}


def report(evs=(), findings=(), coverage=FULL, truth=TRUTH, raw_map=None):
    return build_verification_report(evs,findings,coverage,truth,raw_map)


def test_empty_but_full_coverage_does_not_pass():
    r=report()
    assert r['status']=='NO_ISSUES_OBSERVED'
    assert r['requires_human_review'] is True
    assert r['is_final_decision'] is False
    assert r['version']==VERIFICATION_VERSION


def test_missing_vlm_refusal_is_inconclusive_even_with_price_match():
    r=report([price('MATCH',149000)],coverage={'ocr':'ok','asr':'ok','vlm':'disabled'})
    assert r['status']=='INSUFFICIENT_EVIDENCE'
    assert r['incomplete_modules']==['vlm']


def test_unreviewed_reference_is_inconclusive():
    assert report([price('MATCH',149000)],truth={'reference_status':'unverified'})['status']=='INSUFFICIENT_EVIDENCE'


def test_independent_ocr_and_asr_support_price_candidate():
    evs=[price('MISMATCH',99000),price('MISMATCH',99000,kind='asr',timestamp=1)]
    r=report(evs)
    c=r['checks'][0]
    assert r['status']=='REVIEW_REQUIRED'
    assert (c['category'],c['status'],c['reason'])==('price','CANDIDATE','independent_sources_agree_on_price_candidate')
    assert c['independent_modalities']==2 and c['evidence_indices']==[0,1]
    assert c['values']==[99000]
    assert r['conflict_count']==0


def test_repeated_ocr_same_value_does_not_pretend_independence():
    evs=[price('MISMATCH',99000),price('MISMATCH',99000,timestamp=4)]
    check=report(evs)['checks'][0]
    assert check['independent_modalities']==1
    assert check['reason']=='single_source_price_candidate'


def test_conflicting_observed_prices_no_false_consensus():
    r=report([price('MATCH',149000),price('MISMATCH',99000,'asr')])
    assert r['status']=='REVIEW_REQUIRED'
    assert r['conflict_count']==1
    assert r['checks'][0]['status']=='CONFLICT'
    assert r['checks'][0]['reason']=='multiple_observed_prices'
    assert r['checks'][0]['values']==[99000,149000]


def test_price_promotion_cannot_be_declared_clean():
    r=report([price('INSUFFICIENT_EVIDENCE',99000)])
    assert r['status']=='INSUFFICIENT_EVIDENCE'
    assert r['checks'][0]['status']=='INSUFFICIENT_EVIDENCE'


def test_claim_asserted_and_negated_is_context_conflict():
    r=report([claim('asserted'),claim('negated',kind='asr',timestamp=2)])
    assert r['status']=='REVIEW_REQUIRED'
    c=r['checks'][0]
    assert c['category']=='claim' and c['status']=='CONFLICT'
    assert c['reason']=='mixed_assertion_and_negation'
    assert c['modalities']==['asr','ocr']


def test_claim_negated_only_no_violation():
    r=report([claim('negated')])
    assert r['status']=='INSUFFICIENT_EVIDENCE'
    assert r['candidate_count']==0


def test_claim_assertion_supported_by_two_modalities():
    r=report([claim('asserted'),claim('asserted',kind='asr')])
    assert r['checks'][0]['reason']=='independent_sources_repeat_restricted_claim'
    assert r['candidate_count']==1


def test_phrases_are_not_fused():
    r=report([claim('asserted','chữa khỏi hoàn toàn'),claim('negated','chữa tất cả bệnh')])
    assert len(r['checks'])==2
    assert [c['phrase'] for c in r['checks']]==['chữa khỏi hoàn toàn','chữa tất cả bệnh']


def test_vlm_visual_only_review_candidate_with_raw_id_mapping():
    evs=[Ev('vlm_issue',4.1,{'code':'VIS-02'})]
    findings=[{'code':'VIS-02','source':'vlm','uid':'ev-7','metadata':{}}]
    r=report(evs,findings,raw_map={'ev-7':0})
    assert r['status']=='REVIEW_REQUIRED'
    assert r['checks'][0]['category']=='visual'
    assert r['checks'][0]['evidence_indices']==[0]
    assert r['checks'][0]['reason']=='vlm_visual_hypothesis'


def test_vlm_unlinked_candidate_still_requires_review():
    r=report([], [{'code':'SKU-01','source':'vlm','uid':'lost','metadata':{}}])
    assert r['status']=='REVIEW_REQUIRED'
    assert r['checks'][0]['evidence_indices']==[]


def test_visual_heuristic_no_false_vlm_confirmation():
    r=report([Ev('visual_signal',2,{})], [{'code':'VIS-SCREEN','source':'visual_heuristic',
             'uid':'sig','metadata':{}}], raw_map={'sig':0})
    assert r['checks'][0]['status']=='INSUFFICIENT_EVIDENCE'
    assert r['checks'][0]['reason']=='temporal_heuristic_only'
    assert r['status']=='INSUFFICIENT_EVIDENCE'


def test_coverage_flag_forces_inconclusive_even_if_modules_claim_ok():
    r=report([], [{'code':'EVIDENCE-LOW', 'source':'rule','metadata':{}}])
    assert r['status']=='INSUFFICIENT_EVIDENCE'


def test_unknown_high_finding_not_discarded():
    r=report([], [{'code':'NEW-ALERT','severity':'high','source':'rule','metadata':{}}])
    assert r['status']=='REVIEW_REQUIRED'
    assert r['checks'][0]['category']=='other'


def test_id_binding_only_from_inserted_canonical_evidence():
    evs=[price('MISMATCH',99000),price('MISMATCH',99000,'asr',1)]
    r=report(evs)
    bound=attach_evidence_ids(r,[41,43])
    assert bound['checks'][0]['evidence_ids']==[41,43]
    assert r['checks'][0]['evidence_ids']==[]
    assert bound['checks'][0]['evidence_indices']==[0,1]
    json.dumps(bound,ensure_ascii=False)


def test_no_bad_indices_in_id_linking():
    r=report([price('MISMATCH',99000)])
    assert attach_evidence_ids(r,[])['checks'][0]['evidence_ids']==[]
