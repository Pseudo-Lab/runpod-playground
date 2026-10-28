"""Credential-free remote workloads for the preregistered follow-up experiments."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path('/workspace/followup')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(path)


def environment(torch):
    return {'torch': torch.__version__, 'cuda': torch.version.cuda,
            'gpu': torch.cuda.get_device_name(0),
            'driver': subprocess.check_output(['nvidia-smi', '--query-gpu=driver_version',
                '--format=csv,noheader'], text=True).strip(),
            'filesystems': subprocess.check_output(['df', '-T', '/tmp', '/workspace'], text=True)}


def prepare():
    from huggingface_hub import snapshot_download
    cfg = json.loads((BASE / 'config.json').read_text())
    start = time.monotonic()
    snap = snapshot_download(cfg['model_id'], revision=cfg['model_revision'],
        allow_patterns=['*.json', '*.txt', '*.safetensors', '*.model'], max_workers=4)
    files = [{'path': p.name, 'bytes': p.stat().st_size, 'sha256': digest(p)}
             for p in sorted(Path(snap).iterdir()) if p.is_file()]
    write(BASE / 'prepared.json', {'snapshot': snap, 'files': files,
                                 'download_and_hash_seconds': time.monotonic() - start})


def storage_child(args):
    start = time.monotonic()
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer
    imported = time.monotonic()
    torch.set_num_threads(2)
    torch.manual_seed(42)
    torch.cuda.manual_seed_all(42)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.use_deterministic_algorithms(True)
    cfg = json.loads((BASE / 'config.json').read_text())
    model_path = Path(args.model_path)
    hstart = time.monotonic()
    hashes = {p.name: digest(p) for p in sorted(model_path.iterdir()) if p.is_file()}
    hsecs = time.monotonic() - hstart
    before = time.monotonic()
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(model_path, local_files_only=True,
        dtype=torch.bfloat16, attn_implementation='eager').to('cuda').eval()
    text = tokenizer.apply_chat_template([
        {'role': 'system', 'content': 'You are a helpful assistant.'},
        {'role': 'user', 'content': cfg['prompt']}], tokenize=False, add_generation_prompt=True)
    inputs = tokenizer([text], return_tensors='pt').to('cuda')
    torch.cuda.synchronize()
    load = time.monotonic() - before
    before = time.monotonic()
    with torch.inference_mode():
        logits = model(**inputs).logits[0, -1].float()
        assert torch.isfinite(logits).all(), 'Nonfinite logits'
        output = model.generate(**inputs, max_new_tokens=cfg['max_new_tokens'],
            do_sample=False, pad_token_id=tokenizer.eos_token_id)
    torch.cuda.synchronize()
    tokens = output[0, inputs.input_ids.shape[1]:].cpu().tolist()
    assert tokens and tokenizer.decode(tokens, skip_special_tokens=True).strip()
    write(args.output, {'status': 'complete', 'import_seconds': imported - start,
        'hash_seconds': hsecs, 'load_seconds': load,
        'inference_seconds': time.monotonic() - before, 'child_seconds': time.monotonic() - start,
        'tokens': tokens, 'hashes': hashes, 'environment': environment(torch),
        'transformers': transformers.__version__,
        'peak_cuda_memory_bytes': torch.cuda.max_memory_allocated()})


def storage(args):
    start = time.monotonic()
    prepared = json.loads((BASE / 'prepared.json').read_text())
    temp = Path('/tmp') / ('followup-' + args.run_id)
    assert not temp.exists(), 'Reusing a staging directory would hide copy cost'
    temp.mkdir()
    dep = BASE / 'deps'
    model = Path(prepared['snapshot'])
    cstart = time.monotonic()
    if args.arm in ('B', 'C'):
        shutil.copytree(dep, temp / 'deps')
        dep = temp / 'deps'
    dep_copy = time.monotonic() - cstart
    cstart = time.monotonic()
    if args.arm == 'C':
        shutil.copytree(model, temp / 'model')
        model = temp / 'model'
    model_copy = time.monotonic() - cstart
    out = BASE / 'runs' / args.run_id / 'result.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(dep), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    child = subprocess.run([sys.executable, __file__, 'storage-child', '--model-path', str(model),
        '--output', str(out)], env=env, timeout=420)
    assert child.returncode == 0, 'Storage child failed'
    result = json.loads(out.read_text())
    assert result['hashes'] == {f['path']: f['sha256'] for f in prepared['files']}
    result.update({'arm': args.arm, 'run_id': args.run_id,
        'dependency_copy_seconds': dep_copy, 'model_copy_seconds': model_copy,
        'total_seconds': time.monotonic() - start})
    write(out, result)
    shutil.rmtree(temp)


def training(args):
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    torch.set_num_threads(2)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.use_deterministic_algorithms(True)
    device = 'cuda'

    class Block(nn.Module):
        def __init__(self):
            super().__init__()
            self.norm1 = nn.LayerNorm(128)
            self.qkv = nn.Linear(128, 384)
            self.proj = nn.Linear(128, 128)
            self.norm2 = nn.LayerNorm(128)
            self.ff = nn.Sequential(nn.Linear(128, 256), nn.GELU(), nn.Dropout(.1),
                                    nn.Linear(256, 128), nn.Dropout(.1))
            self.drop = nn.Dropout(.1)

        def forward(self, x):
            b, t, _ = x.shape
            q, k, v = self.qkv(self.norm1(x)).reshape(b, t, 3, 4, 32).permute(2, 0, 3, 1, 4)
            scores = (q @ k.transpose(-1, -2)) / (32 ** .5)
            mask = torch.ones(t, t, device=x.device, dtype=torch.bool).triu(1)
            attn = self.drop(scores.masked_fill(mask, float('-inf')).softmax(-1))
            x = x + self.drop(self.proj((attn @ v).transpose(1, 2).reshape(b, t, 128)))
            return x + self.ff(self.norm2(x))

    class Model(nn.Module):
        def __init__(self):
            super().__init__()
            self.embedding = nn.Embedding(128, 128)
            self.position = nn.Parameter(torch.zeros(1, 64, 128))
            self.blocks = nn.Sequential(Block(), Block())
            self.head = nn.Linear(128, 128)

        def forward(self, x):
            return self.head(self.blocks(self.embedding(x) + self.position[:, :x.shape[1]]))

    def batch(generator):
        offset = torch.randint(0, 128, (8, 1), generator=generator)
        stride = torch.randint(1, 5, (8, 1), generator=generator)
        seq = (offset + stride * torch.arange(65).reshape(1, -1)) % 128
        return seq[:, :-1].to(device), seq[:, 1:].to(device), digest_tensor(seq)

    def digest_tensor(value):
        return hashlib.sha256(value.cpu().contiguous().numpy().tobytes()).hexdigest()

    model = Model().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001, weight_decay=.01, foreach=False)
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda step: max(0., 1 - step / 120))
    generator = torch.Generator().manual_seed(args.seed + 10000)
    out = BASE / 'runs' / args.run_id
    out.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = BASE / 'checkpoints' / str(args.seed)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    load_seconds = 0.
    start_step = 0
    if args.mode in ('full', 'weights'):
        before = time.monotonic()
        checkpoint = checkpoint_dir / 'step060.pt'
        manifest = json.loads(checkpoint.with_suffix('.json').read_text())
        assert checkpoint.stat().st_size == manifest['bytes'] and digest(checkpoint) == manifest['sha256']
        state = torch.load(checkpoint, map_location='cpu', weights_only=False)
        model.load_state_dict(state['model'])
        start_step = state['step']
        if args.mode == 'full':
            optimizer.load_state_dict(state['optimizer'])
            scheduler.load_state_dict(state['scheduler'])
            torch.set_rng_state(state['cpu_rng'])
            torch.cuda.set_rng_state_all(state['cuda_rng'])
            generator.set_state(state['batch_rng'])
        torch.cuda.synchronize()
        load_seconds = time.monotonic() - before
    train_start = time.monotonic()
    rows, saves = [], []
    model.train()
    for step in range(start_step, 120):
        before = time.monotonic()
        x, y, bhash = batch(generator)
        optimizer.zero_grad(set_to_none=True)
        logits = model(x)
        loss = F.cross_entropy(logits.reshape(-1, 128), y.reshape(-1))
        assert torch.isfinite(loss), 'Nonfinite training loss'
        loss.backward()
        lr = optimizer.param_groups[0]['lr']
        optimizer.step()
        scheduler.step()
        torch.cuda.synchronize()
        rows.append({'step': step + 1, 'loss': loss.item(), 'lr': lr, 'batch_sha256': bhash,
                     'step_seconds': time.monotonic() - before})
        if args.mode == 'fault' and (step + 1) % 20 == 0:
            before = time.monotonic()
            ck = checkpoint_dir / f'step{step+1:03d}.pt'
            tmp = ck.with_suffix('.tmp')
            torch.save({'model': model.state_dict(), 'optimizer': optimizer.state_dict(),
                'scheduler': scheduler.state_dict(), 'step': step + 1,
                'cpu_rng': torch.get_rng_state(), 'cuda_rng': torch.cuda.get_rng_state_all(),
                'batch_rng': generator.get_state()}, tmp)
            tmp.replace(ck)
            manifest = {'file': ck.name, 'bytes': ck.stat().st_size, 'sha256': digest(ck),
                        'step': step + 1}
            write(ck.with_suffix('.json'), manifest)
            saves.append(dict(manifest, save_seconds=time.monotonic() - before))
        if args.mode == 'fault' and step + 1 == 73:
            write(out / 'result.json', {'status': 'injected_fault', 'mode': args.mode,
                'seed': args.seed, 'completed_step': 73, 'latest_checkpoint_step': 60,
                'lost_steps': 13, 'rows': rows, 'saves': saves,
                'train_seconds': time.monotonic() - train_start, 'environment': environment(torch)})
            os._exit(86)
    torch.cuda.synchronize()
    train_seconds = time.monotonic() - train_start
    model.eval()
    evaluation = torch.Generator().manual_seed(99999)
    with torch.inference_mode():
        x, y, _ = batch(evaluation)
        logits = model(x)
        eval_loss = F.cross_entropy(logits.reshape(-1, 128), y.reshape(-1)).item()
    final = {k: v.detach().cpu() for k, v in model.state_dict().items()}
    torch.save(final, out / 'final.pt')
    result = {'status': 'complete', 'mode': args.mode, 'seed': args.seed, 'start_step': start_step,
        'end_step': 120, 'rows': rows, 'saves': saves, 'eval_loss': eval_loss,
        'checkpoint_load_seconds': load_seconds, 'train_seconds': train_seconds,
        'parameters': sum(p.numel() for p in model.parameters()), 'environment': environment(torch),
        'peak_cuda_memory_bytes': torch.cuda.max_memory_allocated(),
        'final_state_sha256': digest(out / 'final.pt')}
    if args.mode in ('full', 'weights'):
        baseline = BASE / 'runs' / f'train-baseline-{args.seed}'
        original = torch.load(baseline / 'final.pt', weights_only=True)
        diff = torch.cat([(final[k].float() - original[k].float()).reshape(-1) for k in final])
        ref = json.loads((baseline / 'result.json').read_text())
        result.update({'parameter_max_abs_error': diff.abs().max().item(),
            'parameter_rms_error': diff.square().mean().sqrt().item(),
            'eval_loss_abs_error': abs(eval_loss - ref['eval_loss']),
            'batch_sequence_matches': [r['batch_sha256'] for r in rows] ==
                                     [r['batch_sha256'] for r in ref['rows'][start_step:]],
            'max_loss_abs_error': max(abs(r['loss'] - b['loss'])
                for r, b in zip(rows, ref['rows'][start_step:]))})
    write(out / 'result.json', result)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['prepare', 'storage', 'storage-child', 'train'])
    p.add_argument('--run-id')
    p.add_argument('--arm', choices=['A', 'B', 'C'])
    p.add_argument('--model-path')
    p.add_argument('--output')
    p.add_argument('--mode', choices=['baseline', 'fault', 'full', 'weights'])
    p.add_argument('--seed', type=int)
    args = p.parse_args()
    {'prepare': prepare, 'storage': lambda: storage(args),
     'storage-child': lambda: storage_child(args), 'train': lambda: training(args)}[args.action]()


if __name__ == '__main__':
    main()
