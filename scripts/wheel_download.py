"""Fetch exact wheels from official PyPI metadata; verify bytes before installation."""
import hashlib
import json
import subprocess
from urllib.parse import urlparse
from packaging.tags import cpython_tags, compatible_tags
from packaging.utils import parse_wheel_filename
from packaging.specifiers import SpecifierSet


def download(requirements, destination, arch):
    platforms=['manylinux_2_28_'+arch,'manylinux_2_17_'+arch,'manylinux2014_'+arch,'manylinux_2_34_'+arch]
    tags=list(cpython_tags((3,12),abis=['cp312','abi3','none'],platforms=platforms))+list(compatible_tags((3,12),interpreter='cp312',platforms=platforms))
    ranks={tag:index for index,tag in reversed(list(enumerate(tags)))}
    for req in requirements:
        from packaging.requirements import Requirement
        parsed=Requirement(req);specs=list(parsed.specifier)
        assert len(specs)==1 and specs[0].operator=='=='
        url='https://pypi.org/pypi/'+parsed.name+'/'+specs[0].version+'/json'
        metadata=json.loads(subprocess.check_output(['curl','--fail','--silent','--show-error','--location','--retry','2',url]))
        candidates=[]
        for item in metadata['urls']:
            if item['packagetype']!='bdist_wheel' or item.get('yanked'):continue
            if item.get('requires_python') and '3.12.14' not in SpecifierSet(item['requires_python']):continue
            _,_,_,wheel_tags=parse_wheel_filename(item['filename'])
            supported=[ranks[tag] for tag in wheel_tags if tag in ranks]
            if supported:candidates.append((min(supported),item))
        if not candidates:raise RuntimeError('NO_COMPATIBLE_LOCKED_WHEEL: '+parsed.name)
        item=min(candidates,key=lambda c:c[0])[1];url=item['url'];parts=urlparse(url)
        assert parts.scheme=='https' and parts.hostname=='files.pythonhosted.org'
        path=destination/item['filename'];assert path.parent==destination
        for attempt in range(3):
            subprocess.run(['curl','--fail','--silent','--show-error','--location','--retry','2',url,'-o',str(path)],check=True)
            if hashlib.sha256(path.read_bytes()).hexdigest()==item['digests']['sha256']:break
            print('HASH_MISMATCH rejected; retrying exact official asset: '+item['filename'],flush=True)
        else:raise RuntimeError('WHEEL_HASH_MISMATCH: '+item['filename'])
        print('Verified '+item['filename'],flush=True)
