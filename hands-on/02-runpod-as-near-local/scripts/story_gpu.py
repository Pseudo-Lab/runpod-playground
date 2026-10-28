"""Remote archive staging and cold/cached inference, without cloud credentials."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

BASE = Path('/workspace/followup')


def write(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temp.replace(path)


def child(args):
    started = time.monotonic()
    import followup_gpu as gpu
    cfg = json.loads((BASE / 'config.json').read_text())
    download = 0.
    if args.mode == 'cold':
        before = time.monotonic()
        from huggingface_hub import snapshot_download
        snap = snapshot_download(cfg['model_id'], revision=cfg['model_revision'],
            allow_patterns=['*.json', '*.txt', '*.safetensors', '*.model'], max_workers=4)
        download = time.monotonic() - before
        weights = Path(snap) / 'model.safetensors'
        write(BASE / 'story-model.json', {'snapshot': snap,
            's3_key': str(weights.resolve().relative_to('/workspace')),
            'bytes': weights.stat().st_size,
            'first64k_sha256': hashlib.sha256(weights.open('rb').read(65536)).hexdigest()})
    else:
        snap = json.loads((BASE / 'story-model.json').read_text())['snapshot']
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
    output = BASE / 'runs' / args.run_id / 'result.json'
    gpu.storage_child(SimpleNamespace(model_path=snap, output=str(output)))
    r = json.loads(output.read_text())
    r.update(mode=args.mode, download_and_hf_lookup_seconds=download,
             child_total_seconds=time.monotonic() - started,
             persisted_marker=(BASE / 'story-marker.txt').read_text())
    write(output, r)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=['cold', 'cached'], required=True)
    p.add_argument('--run-id', required=True)
    p.add_argument('--child', action='store_true')
    args = p.parse_args()
    if args.child:
        child(args)
        return
    started = time.monotonic()
    target = Path('/tmp') / ('story-deps-' + args.run_id)
    assert not target.exists()
    target.mkdir()
    with tarfile.open(BASE / 'deps.tar', 'r') as archive:
        archive.extractall(target, filter='data')
    extract = time.monotonic() - started
    env = dict(os.environ, PYTHONPATH=str(target / 'deps') + ':' + str(BASE))
    run = subprocess.run([sys.executable, __file__, '--mode', args.mode, '--run-id', args.run_id,
                          '--child'], env=env, timeout=450)
    assert run.returncode == 0
    out = BASE / 'runs' / args.run_id / 'result.json'
    r = json.loads(out.read_text())
    r.update(archive_read_and_extract_seconds=extract,
             archive_bytes=(BASE / 'deps.tar').stat().st_size,
             remote_total_seconds=time.monotonic() - started)
    write(out, r)


if __name__ == '__main__':
    main()
