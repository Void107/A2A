"""Fresh local acceptance stack, dependency acquisition, restart and resource evidence."""
import argparse
import atexit
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
LOG=ROOT/'docs/verification'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--reuse-wheels',action='store_true');parser.add_argument('--downloader',choices=['pip','curl'],default='pip');args=parser.parse_args()
    run_id='accept-'+uuid.uuid4().hex[:10];project='a2a-'+run_id
    evidence=LOG/run_id;evidence.mkdir()
    report={'project':project,'host':{'platform':platform.platform(),'architecture':platform.machine(),'logical_cpus':os.cpu_count()},'steps':[],'external_deployment':False}
    def save(): (evidence/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    def run(name,command,check=True):
        started=time.time()
        with (evidence/(name+'.log')).open('w') as output:
            result=subprocess.run(command,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
        row={'name':name,'command':command,'started_unix':started,'seconds':time.time()-started,'exit_code':result.returncode}
        report['steps'].append(row);save();print(name, result.returncode,flush=True)
        if check and result.returncode:raise RuntimeError(name+' failed; inspect '+str(evidence))
        return result
    with tempfile.TemporaryDirectory(prefix='a2a-install-') as temp:
        temp=Path(temp)
        if args.reuse_wheels:
            wheelhouse=ROOT/'.local-wheelhouse';report['dependency_acquisition']='existing wheel cache; no fresh download claim'
        else:
            wheelhouse=temp/'wheels'
            run('fresh-dependencies',[sys.executable,'scripts/prepare_wheels.py','--destination',str(wheelhouse),'--no-cache','--downloader',args.downloader])
            report['dependency_bytes']=sum(p.stat().st_size for p in wheelhouse.glob('*/*.whl'))
            (evidence/'wheel-sha256.json').write_text((wheelhouse/'sha256.json').read_text())
        override=temp/'wheels.json'
        override.write_text(json.dumps({'services':{name:{'build':{'additional_contexts':{'wheels':str(wheelhouse/('presidio' if name=='presidio' else 'hub'))}}} for name in ['init','hub','provider','presidio','demo','measure']}}))
        base=['docker','compose','-p',project,'-f','compose.yaml','-f','compose.offline.yaml','-f','compose.acceptance.yaml','-f',str(override)]
        # Register bounded cleanup for this invocation; preserve volumes.
        atexit.register(lambda: subprocess.run(base[:-2]+['down'],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30))
        report['configuration']=['compose.yaml','compose.offline.yaml','compose.acceptance.yaml'];save()
        # Fresh volumes and fresh dependency install layers; never erase previous stacks.
        run('clean-build',base+['--profile','demo','--profile','measure','build','--no-cache'])
        started=time.time()
        run('startup',base+['up','-d','--wait','--wait-timeout','180'])
        run('first-consumers',base+['--profile','demo','run','--rm','demo'])
        report['cold_start_to_first_consumers_seconds']=time.time()-started;save()
        inspect=['exec','-T','hub','python','scripts/local_entrypoint.py','python','scripts/inspect_local_state.py']
        run('before-restart',base+inspect)
        run('restart',base+['restart','postgres','hub','provider'])
        run('ready-after-restart',base+['up','-d','--wait','--wait-timeout','180'])
        run('after-restart',base+inspect)
        before=json.loads((evidence/'before-restart.log').read_text());after=json.loads((evidence/'after-restart.log').read_text())
        assert before['receipts']==after['receipts'] and before['receipts']>=2
        run('restart-consumers',base+['--profile','demo','run','--rm','demo'])
        ids=subprocess.check_output(base+['ps','-q'],cwd=ROOT,text=True).split()
        containers=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True))
        report['containers']=[{'image':c['Image'],'service':c['Config']['Labels']['com.docker.compose.service'],
            'memory_bytes':c['HostConfig']['Memory'],'nano_cpus':c['HostConfig']['NanoCpus']} for c in containers]
        report['docker_engine']=json.loads(subprocess.check_output(['docker','info','--format','{{json .}}'],text=True))
        # Retain only runtime capacity metadata, never dump daemon config.
        report['docker_engine']={key:report['docker_engine'].get(key) for key in ['ServerVersion','Architecture','NCPU','MemTotal','OperatingSystem']};save()
        stop=threading.Event()
        def sample():
            with (evidence/'resources.jsonl').open('w') as output:
                while not stop.is_set():
                    result=subprocess.run(['docker','stats','--no-stream','--format','{{json .}}',*ids],capture_output=True,text=True)
                    output.write(json.dumps({'time':time.time(),'exit_code':result.returncode,'containers':[json.loads(line) for line in result.stdout.splitlines()]})+'\n');output.flush()
                    stop.wait(1)
        thread=threading.Thread(target=sample,daemon=True);thread.start()
        try: run('measurement',base+['--profile','measure','run','--rm','measure'])
        finally: stop.set();thread.join(timeout=15)
        run('export-requests',base+['cp','hub:/measurements/requests.json',str(evidence/'requests.json')])
        run('export-phases',base+['cp','hub:/measurements/core.jsonl',str(evidence/'core.jsonl')])
        run('final-state',base+inspect)
        report['result']='PASS';save()
        # Remove only this invocation's containers/network; retain data volumes and evidence.
        run('cleanup-owned-stack',base+['down'])
    print('PASS AC-21/23: '+str(evidence),flush=True)

if __name__=='__main__':main()
