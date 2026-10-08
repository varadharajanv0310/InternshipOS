from sqlalchemy import select,func
from internshipos import models as m,service
from test_domain import db,source,ingest,only_op,job

def legacy(db):
    board=source(db,provider='workday',url='https://acme.wd5.myworkdayjobs.com/External')
    path='/job/Bengaluru/Software-Engineering-Intern_R123-1'
    url='https://acme.wd5.myworkdayjobs.com/External'+path
    raw={'listing':{'title':'Software Engineering Intern','externalPath':path,'bulletFields':['R123']},
         'detail':{'jobPostingInfo':{'title':'Software Engineering Intern','jobReqId':'R123',
                    'jobPostingId':'Software-Engineering-Intern_R123-1','externalUrl':url}}}
    ingest(db,board,[job('R123',requisition_id='R123',canonical_url=url,raw=raw)])
    appearance=db.scalar(select(m.JobSource));op=only_op(db)
    return board,op,appearance,path

def test_legacy_repair_uses_primary_native_snapshot_preserves_history_and_clocks(db):
    board,op,appearance,path=legacy(db)
    before=(appearance.last_seen,appearance.last_detail_checked,op.data.get('description_checked_at'))
    history=db.scalar(select(func.count()).select_from(m.Snapshot))
    result=service.repair_workday_identity(db,appearance.id,apply=True)
    assert result['applied'] and appearance.external_id==path and appearance.requisition_id=='R123'
    assert (appearance.last_seen,appearance.last_detail_checked,op.data.get('description_checked_at'))==before
    assert db.scalar(select(func.count()).select_from(m.Snapshot))==history

def test_wrong_requisition_or_title_leaves_legacy_identity_for_review(db):
    board,op,appearance,path=legacy(db)
    op.title='Other Job'
    assert not service.repair_workday_identity(db,appearance.id,apply=True)['applied']
    assert appearance.external_id=='R123'

def test_same_posting_collision_becomes_history_alias_not_new_liveness(db):
    board,op,appearance,path=legacy(db)
    canonical=m.JobSource(company_source_id=board.id,opportunity_id=op.id,external_id=path,
                          requisition_id='R123',url=appearance.url,status='active')
    db.add(canonical);db.flush()
    assert service.repair_workday_identity(db,appearance.id,apply=True)['alias']
    assert appearance.status=='historical_alias'
    for _ in range(3):ingest(db,board,[job(path,requisition_id='R123',canonical_url=appearance.url)])
    assert appearance.status=='historical_alias'
    assert db.scalar(select(func.count()).select_from(m.JobSource))==2
