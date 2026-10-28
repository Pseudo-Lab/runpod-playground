"""Prepare the pinned official ACE-Step checkout and both model repositories."""
import hashlib
import json
import subprocess
import time
from pathlib import Path

BASE=Path('/workspace/ace')

def run(argv,cwd=None,timeout=1500):
    subprocess.run(argv,cwd=cwd,check=True,timeout=timeout)

def main():
    started=time.monotonic();result={};source=BASE/'source'
    before=time.monotonic()
    run(['python','-m','pip','install','uv==0.13.5','--quiet'])
    run(['uv','sync','--frozen','--no-install-package','flash-attn'],cwd=source)
    result['install_seconds']=time.monotonic()-before
    before=time.monotonic()
    python=source/'.venv/bin/python'
    code='''import json,time;from huggingface_hub import snapshot_download
from pathlib import Path
b=Path('/workspace/ace/source/checkpoints'); b.mkdir(exist_ok=True)
for repo,revision,target in [('ACE-Step/Ace-Step1.5','19671f406d603126926c1b7e2adc169acbcade22',b),('ACE-Step/acestep-5Hz-lm-4B','0a3ec94b557aea7d508da38b31cfe7341f6ff737',b/'acestep-5Hz-lm-4B')]:
 t=time.monotonic();snapshot_download(repo_id=repo,revision=revision,local_dir=str(target),max_workers=4); print(json.dumps({'repo':repo,'seconds':time.monotonic()-t}),flush=True)
'''
    run([str(python),'-c',code]);result['download_seconds']=time.monotonic()-before
    run([str(python),'-m','pip','--version'],timeout=30) if False else None
    with (BASE/'environment.txt').open('w') as f:
        subprocess.run(['uv','pip','freeze','--python',str(python)],stdout=f,check=True)
    result['total_bootstrap_seconds']=time.monotonic()-started
    result['checkpoint_bytes']=sum(f.stat().st_size for f in (source/'checkpoints').rglob('*') if f.is_file() and '.cache' not in f.parts)
    (BASE/'bootstrap.json').write_text(json.dumps(result,indent=2))

if __name__=='__main__':main()
