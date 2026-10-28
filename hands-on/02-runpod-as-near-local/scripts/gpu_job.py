"""Runs on the Pod without any RunPod/S3 credentials."""
import argparse
import hashlib
import json
import os
import platform
import subprocess
import time
import traceback
from pathlib import Path


def write_json(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--repeat-after-seconds', type=int, default=0)
    args = parser.parse_args()
    out = Path('/workspace/experiment/runs') / args.run_id
    out.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    result = {'run_id': args.run_id}
    write_json(out / 'status.json', {'status': 'running'})
    try:
        import torch
        import transformers
        from huggingface_hub import snapshot_download
        from transformers import AutoModelForCausalLM, AutoTokenizer

        cfg = json.loads(Path('experiment.json').read_text(encoding='utf-8'))
        smoke = Path('/workspace/smoke/roundtrip.txt').read_bytes()
        result['persistent_smoke_sha256'] = hashlib.sha256(smoke).hexdigest()
        assert result['persistent_smoke_sha256'] == cfg['s3_smoke_sha256']
        marker = Path('/tmp/runpod-experiment-ephemeral-marker')
        result['ephemeral_marker_existed'] = marker.exists()
        assert not marker.exists(), 'A new Pod unexpectedly retained the ephemeral marker'
        marker.write_text(args.run_id)
        assert torch.cuda.is_available(), 'CUDA unavailable'
        assert torch.cuda.device_count() == 1, 'Expected exactly one GPU'
        torch.manual_seed(cfg['seed'])
        torch.cuda.manual_seed_all(cfg['seed'])
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.use_deterministic_algorithms(True)
        a = torch.tensor([[1., 2.], [3., 4.]])
        expected = a @ a
        actual = (a.cuda() @ a.cuda()).cpu()
        w0_error = (actual - expected).abs().max().item()
        assert w0_error <= cfg['output_validation']['w0_max_abs_error']
        result.update({'python': platform.python_version(), 'torch': torch.__version__,
                       'transformers': transformers.__version__,
                       'cuda': torch.version.cuda, 'gpu': torch.cuda.get_device_name(0),
                       'w0_max_abs_error': w0_error,
                       'driver': subprocess.check_output(['nvidia-smi', '--query-gpu=driver_version',
                           '--format=csv,noheader'], text=True).strip()})
        before_download = time.monotonic()
        snapshot = snapshot_download(cfg['model_id'], revision=cfg['model_revision'],
            allow_patterns=['*.json', '*.txt', '*.safetensors', '*.model'], max_workers=4)
        result['download_seconds'] = time.monotonic() - before_download
        manifest = []
        hash_start = time.monotonic()
        for file in sorted(Path(snapshot).iterdir()):
            if file.is_file():
                digest = hashlib.sha256()
                with file.open('rb') as stream:
                    for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                        digest.update(block)
                manifest.append({'path': file.name, 'bytes': file.stat().st_size,
                                 'sha256': digest.hexdigest()})
                if file.name == 'model.safetensors':
                    with file.open('rb') as stream:
                        result['model_first_64k_sha256'] = hashlib.sha256(stream.read(65536)).hexdigest()
        result['hash_seconds'] = time.monotonic() - hash_start
        result['model_manifest'] = manifest
        result['model_id'] = cfg['model_id']
        result['model_revision'] = cfg['model_revision']
        before_load = time.monotonic()
        tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
        dtype = {'float16': torch.float16, 'bfloat16': torch.bfloat16}[cfg['precision']]
        if dtype == torch.bfloat16:
            assert torch.cuda.is_bf16_supported(), 'Selected GPU does not support bfloat16'
        model = AutoModelForCausalLM.from_pretrained(snapshot, local_files_only=True,
            dtype=dtype, attn_implementation='eager').to('cuda').eval()
        result['precision'] = cfg['precision']
        messages = [{'role': 'system', 'content': 'You are a helpful assistant.'},
                    {'role': 'user', 'content': cfg['prompt']}]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer([text], return_tensors='pt').to('cuda')
        torch.cuda.synchronize()
        result['model_load_seconds'] = time.monotonic() - before_load
        result['ready_seconds'] = time.monotonic() - start
        write_json(out / 'ready.json', {'ready_seconds': result['ready_seconds']})
        inference_start = time.monotonic()
        with torch.inference_mode():
            logits = model(**inputs).logits[0, -1].float()
            assert bool(torch.isfinite(logits).all()), 'Non-finite logits'
            result['first_logits_sample'] = logits[:64].cpu().tolist()
            outputs = model.generate(**inputs, max_new_tokens=cfg['max_new_tokens'],
                                     do_sample=False, pad_token_id=tokenizer.eos_token_id)
        torch.cuda.synchronize()
        result['inference_seconds'] = time.monotonic() - inference_start
        tokens = outputs[0, inputs.input_ids.shape[1]:].cpu().tolist()
        assert tokens, 'No generated tokens'
        result['generated_token_ids'] = tokens
        result['generated_text'] = tokenizer.decode(tokens, skip_special_tokens=True)
        assert result['generated_text'].strip(), 'Empty generated text'
        result['peak_cuda_memory_bytes'] = torch.cuda.max_memory_allocated()
        result['total_remote_seconds'] = time.monotonic() - start
        result['status'] = 'complete'
        write_json(out / 'result.json', result)
        raw = (out / 'result.json').read_bytes()
        write_json(out / 'manifest.complete.json', {'file': 'result.json', 'bytes': len(raw),
                                                  'sha256': hashlib.sha256(raw).hexdigest()})
        write_json(out / 'status.json', {'status': 'complete'})
        if args.repeat_after_seconds:
            # Keep the model resident for the keep-policy baseline.
            wait_until = time.monotonic() + args.repeat_after_seconds
            while time.monotonic() < wait_until:
                time.sleep(min(10, max(0, wait_until - time.monotonic())))
            second_start = time.monotonic()
            with torch.inference_mode():
                logits2 = model(**inputs).logits[0, -1].float()
                assert bool(torch.isfinite(logits2).all())
                outputs2 = model.generate(**inputs, max_new_tokens=cfg['max_new_tokens'],
                    do_sample=False, pad_token_id=tokenizer.eos_token_id)
            torch.cuda.synchronize()
            tokens2 = outputs2[0, inputs.input_ids.shape[1]:].cpu().tolist()
            second = {'run_id': args.run_id + '-second', 'status': 'complete',
                'resident_model_reused': True, 'generated_token_ids': tokens2,
                'generated_text': tokenizer.decode(tokens2, skip_special_tokens=True),
                'first_logits_sample': logits2[:64].cpu().tolist(),
                'inference_seconds': time.monotonic() - second_start,
                'intent_to_result_seconds': time.monotonic() - second_start}
            assert tokens2 and second['generated_text'].strip()
            write_json(out / 'second-result.json', second)
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)
        result['status'] = 'failed'
        write_json(out / 'result.json', result)
        write_json(out / 'status.json', {'status': 'failed'})
        traceback.print_exc()
        raise


if __name__ == '__main__':
    main()
