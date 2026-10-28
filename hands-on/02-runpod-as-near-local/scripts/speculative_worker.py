"""Loopback-only, single-request GPU worker; contains no provider credentials."""
import argparse
import hashlib
import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE=Path('/workspace/followup')

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);args=p.parse_args()
    out=BASE/'runs'/args.run;out.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    import torch
    from transformers import AutoModelForCausalLM,AutoTokenizer
    torch.set_num_threads(2);torch.manual_seed(42);torch.cuda.manual_seed_all(42)
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    torch.use_deterministic_algorithms(True)
    cfg=json.loads((BASE/'config.json').read_text())
    snap=Path(json.loads((BASE/'prepared.json').read_text())['snapshot'])
    def digest(f):
        h=hashlib.sha256()
        with f.open('rb') as stream:
            for b in iter(lambda:stream.read(8*1024*1024),b''):h.update(b)
        return h.hexdigest()
    hashes={f.name:digest(f) for f in sorted(snap.iterdir()) if f.is_file()}
    tok=AutoTokenizer.from_pretrained(snap,local_files_only=True)
    model=AutoModelForCausalLM.from_pretrained(snap,local_files_only=True,dtype=torch.bfloat16,
        attn_implementation='eager').to('cuda').eval()
    prompt=tok.apply_chat_template([{'role':'system','content':'You are a helpful assistant.'},
        {'role':'user','content':cfg['prompt']}],tokenize=False,add_generation_prompt=True)
    inputs=tok([prompt],return_tensors='pt').to('cuda');torch.cuda.synchronize()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            before=time.monotonic()
            with torch.inference_mode():
                logits=model(**inputs).logits[0,-1].float()
                assert torch.isfinite(logits).all()
                result=model.generate(**inputs,max_new_tokens=cfg['max_new_tokens'],do_sample=False,
                    pad_token_id=tok.eos_token_id)
            torch.cuda.synchronize()
            payload=json.dumps({'tokens':result[0,inputs.input_ids.shape[1]:].cpu().tolist(),
                'inference_seconds':time.monotonic()-before}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(payload)));self.end_headers()
            self.wfile.write(payload)
    server=HTTPServer(('127.0.0.1',8879),Handler)
    (out/'ready.json').write_text(json.dumps({'pid':os.getpid(),'hashes':hashes,
        'load_and_verify_seconds':time.monotonic()-started,'gpu':torch.cuda.get_device_name(0)}))
    server.serve_forever()

if __name__=='__main__':main()
