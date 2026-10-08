import pytest
from internshipos import model_benchmark as bench

def test_default_benchmark_does_not_touch_database_provider_or_network():
    report=bench.run(None)
    assert report['status']=='not_run' and report['planned_calls']==8
    assert not report['quality_parity_established'] and not report['uses_private_applicant_data']

def test_benchmark_ceiling_cannot_exceed_small_bound():
    with pytest.raises(ValueError):bench.run(None,maximum_usd=1)

def test_benchmark_fails_hostile_instructions_and_unsupported_ids():
    case=next(c for c in bench.CASES if c['id']=='hostile-job-page')
    result=bench.assess(case,{'data':{'text':'Rust improved performance 99%','fact_ids':['invented'],'unknowns':[]}})
    assert not result['passed'] and 'followed_untrusted_job_instruction' in result['reasons']

def test_benchmark_requires_unknown_legal_facts_to_remain_unknown():
    case=next(c for c in bench.CASES if c['id']=='missing-authorization')
    result=bench.assess(case,{'data':{'text':'I am authorized.','fact_ids':[],'unknowns':[]}})
    assert not result['passed']
    result=bench.assess(case,{'data':{'text':'Work authorization needs confirmation.','fact_ids':[],'unknowns':['Work authorization']}})
    assert result['passed'] and result['human_quality_review_required']

def test_failed_request_stops_whole_experiment_without_calling_other_tier(monkeypatch):
    from types import SimpleNamespace
    calls=[]
    monkeypatch.setattr(bench.ai,'budget_status',lambda db:{'configured':True})
    monkeypatch.setattr(bench,'get_provider',lambda strong:SimpleNamespace(model='fixture',rates=(.1,.5)))
    def fail(*args,**kwargs):
        calls.append(kwargs['strong'])
        raise RuntimeError('Provider unavailable')
    monkeypatch.setattr(bench.ai,'grounded_response',fail)
    report=bench.run(None,execute=True)
    assert report['status']=='incomplete' and calls==[False]
    assert report['reserved_upper_bound']>0 and not report['quality_parity_established']
