"""Local installation walkthrough via public APIs; emits only synthetic tasks."""
import asyncio
import json
import os
from pathlib import Path
import httpx
from sdk.client import ContractClient
from examples.meeting_views.consume import consume


async def main():
    base=os.environ.get('HUB_URL','http://hub:8000')
    fixtures=Path('docs/implementation/examples')
    async with httpx.AsyncClient(base_url=base,timeout=35,trust_env=False) as http:
        async def login(actor,key):
            r=await http.post('/api/v1/auth/token',json={'agent_id':actor,'api_key':key}); r.raise_for_status()
            return r.json()['access_token']
        token=await login('meeting-provider',Path('/state/admin-key').read_text())
        admin={'Authorization':'Bearer '+token}
        keys_path=Path('/state/caller-keys.json')
        keys=json.loads(keys_path.read_text()) if keys_path.exists() else {}
        for actor,org,role in [('project-agent','org-acme','project-agent'),('partner-agent','org-partner','collaboration-agent')]:
            if actor not in keys:
                r=await http.put('/api/v2/admin/identities/'+actor,headers=admin,json={'agent_id':actor,'organization_id':org,'roles':[role],'scopes':['query','discover','audit'],'is_active':True})
                r.raise_for_status(); keys[actor]=r.json()['api_key']
                keys_path.write_text(json.dumps(keys)); keys_path.chmod(0o600)
        contract=json.loads((fixtures/'contract.meeting.json').read_text())
        r=await http.post('/api/v2/contracts',headers=admin,json={'provider_agent_id':'meeting-provider','contract':contract})
        if r.status_code==201:
            path='/api/v2/contracts/meeting-actions/1.0.0'
            for action in ['validate','activate','default']:
                (await http.post(path+'/'+action,headers=admin)).raise_for_status()
        elif r.status_code!=409: r.raise_for_status()
        results={}
        for actor,view,expected in [('project-agent','internal-project','expected.internal.json'),('partner-agent','external-collaboration','expected.external.json')]:
            r=await http.put('/api/v2/admin/grants/'+actor,headers=admin,json={'agent_id':actor,'contract_id':'meeting-actions','view_id':view,'allowed_meeting_ids':['meeting-001'],'active':True}); r.raise_for_status()
            client=ContractClient(base,await login(actor,keys[actor]))
            try:
                assert any(v['view_id']==view for v in await client.discover())
                response=await client.query('meeting-provider','meeting-actions','1.0.0',view,'meeting-001')
                assert response['data']==json.loads((fixtures/expected).read_text())
                results[view]=consume(response['data'],view)
            finally: await client.close()
        print(json.dumps(results,indent=2))
        print('PASS: public API discovery, exact dual views, local task consumers')


if __name__=='__main__': asyncio.run(main())
