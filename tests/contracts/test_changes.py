import copy
import json
from pathlib import Path
import pytest
from app.contracts.changes import compare
from app.contracts.migrate import migrate
from app.contracts.publication import PublicationInput, enforce

FIXTURE = Path(__file__).resolve().parents[2] / 'docs/implementation/examples/contract.meeting.json'


def pair():
    a = json.loads(FIXTURE.read_text()); b = copy.deepcopy(a); b['contract_version'] = '1.1.0'
    return a, b


def test_identical_and_new_independent_view():
    a,b=pair(); assert compare(a,b)['classification']=='compatible'
    v=copy.deepcopy(b['views'][0]); v['view_id']='additional-view'; b['views'].append(v)
    assert compare(a,b)['classification']=='compatible'
    assert not compare(a,b)['all_consumers_verified']


def test_deleted_owner_is_breaking():
    a,b=pair(); v=b['views'][0]
    v['projection'].remove('action_items[*].owner_email')
    item=v['output_schema']['properties']['action_items']['items']
    item['properties'].pop('owner_email'); item['required'].remove('owner_email')
    r=compare(a,b); assert r['classification']=='breaking'
    assert all(x['view_id']=='internal-project' for x in r['reasons'])


def test_unknown_in_second_view_cannot_hide_behind_first_break():
    a,b=pair(); b['views'][0]['output_schema']['required'].remove('title')
    b['views'][1]['output_schema']['properties']['title']['maxLength']=500
    r=compare(a,b); assert r['classification']=='review_required'


def test_security_changes_are_separate():
    a,b=pair(); b['policies'].pop()
    r=compare(a,b); assert r['security_changes'] and r['classification']=='compatible'


def test_publication_evidence_never_forces_unknown_or_failed_consumer():
    bundle=PublicationInput(consumers=[], migration_id='migration-one')
    with pytest.raises(ValueError, match='REVIEW_REQUIRED'):
        enforce([{'classification':'review_required'}], [], '2.0.0', bundle, 'x','x')
    with pytest.raises(ValueError, match='CONSUMER_VALIDATION_FAILED'):
        enforce([], [{'result':'FAIL'}], '2.0.0', bundle, 'x','x')
    r=[{'classification':'breaking','old_version':'1.0.0','security_changes':[]}]
    with pytest.raises(ValueError, match='NEW_MAJOR_VERSION_REQUIRED'):
        enforce(r,[{'consumer_id':'a','result':'PASS'}],'1.1.0',bundle,'x','x')
    with pytest.raises(ValueError, match='ACKNOWLEDGEMENT_REQUIRED'):
        enforce(r,[{'consumer_id':'a','result':'PASS'}],'2.0.0',bundle,None,'x')
    enforce(r,[{'consumer_id':'a','result':'PASS'}],'2.0.0',bundle,'x','x')
    with pytest.raises(ValueError, match='DEFAULT_CONSUMERS_NOT_MIGRATED'):
        enforce(r,[{'consumer_id':'a','result':'PASS'}],'2.0.0',bundle,'x','x',True,['a','b'])


def test_legacy_migration_never_drops_conditions_or_unknown_rules():
    _,template=pair()
    old={'version':'0.2.0','schemas':[{'schema_id':'s'}], 'policies':[
        {'policy_id':'one','effect':'allow','schema_ids':['s'],'principal':{'organizations':['org-acme']}}], 'transforms':[]}
    assert migrate(old,template)['status']=='draft_only'
    old['policies'][0].update(conditions={'purpose':'anything'},effect='typo',transform_ids=['missing'])
    r=migrate(old,template); assert r['draft'] is None
    assert {'UNSUPPORTED_CONDITIONS','INVALID_EFFECT','MISSING_TRANSFORM'} <= set(r['errors'])
