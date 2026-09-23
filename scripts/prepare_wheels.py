"""Prefetch pinned Linux CPython 3.12 wheels with normal TLS verification."""
import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from packaging.requirements import Requirement
from packaging.markers import default_environment


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arch',choices=['aarch64','x86_64'],default='aarch64' if platform.machine() in {'arm64','aarch64'} else 'x86_64')
    parser.add_argument('--destination',type=Path)
    parser.add_argument('--no-cache',action='store_true')
    parser.add_argument('--downloader',choices=['pip','curl'],default='pip')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    destination=args.destination or root/'.local-wheelhouse'
    env=default_environment();env.update(python_version='3.12',python_full_version='3.12.14',sys_platform='linux',platform_system='Linux',platform_machine=args.arch)
    for component in ['hub','presidio']:
        wheelhouse=destination/component;wheelhouse.mkdir(parents=True,exist_ok=True)
        lines=[]
        for line in (root/('requirements-'+component+'.lock')).read_text().splitlines():
            if not line.strip() or line.startswith('#'):continue
            req=Requirement(line)
            if req.marker is None or req.marker.evaluate(env):
                req.marker=None;lines.append(str(req))
        selected=wheelhouse.parent/(component+'-linux.lock');selected.write_text('\n'.join(lines)+'\n')
        command=[sys.executable,'-m','pip','download','--disable-pip-version-check','--no-deps','--only-binary=:all:',
                 '--python-version','312','--implementation','cp','--abi','cp312','--abi','abi3','--abi','none']
        if args.no_cache: command.append('--no-cache-dir')
        for tag in ['manylinux_2_28_','manylinux_2_17_','manylinux2014_','manylinux_2_34_']:
            command.extend(['--platform',tag+args.arch])
        if args.downloader=='curl':
            from wheel_download import download
            download(lines,wheelhouse,args.arch)
        else:
            subprocess.run(command+['-r',str(selected),'-d',str(wheelhouse)],check=True)
    manifest={str(p.relative_to(destination)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((destination).glob('*/*.whl'))}
    (destination/'sha256.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Pinned wheelhouse ready for compose.offline.yaml; dependency resolution is rechecked inside the clean container.')


if __name__=='__main__':main()
