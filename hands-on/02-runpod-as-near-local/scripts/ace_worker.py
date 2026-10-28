"""ACE-Step loopback worker and single-shot audio generation, without cloud keys."""
import argparse
import hashlib
import json
import os
import random
import time
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path

BASE=Path('/workspace/ace')

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(path)

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--once',action='store_true');args=p.parse_args()
    out=BASE/'runs'/args.run;out.mkdir(parents=True,exist_ok=True);start=time.monotonic()
    import numpy as np
    import torch
    import soundfile as sf
    from acestep.handler import AceStepHandler
    from acestep.llm_inference import LLMHandler
    from acestep.inference import GenerationParams,GenerationConfig,generate_music
    imported=time.monotonic();torch.set_num_threads(4)
    checkpoint=BASE/'source/checkpoints'
    used=['acestep-v15-turbo','vae','Qwen3-Embedding-0.6B','acestep-5Hz-lm-4B']
    before=time.monotonic()
    hashes={str(f.relative_to(checkpoint)):digest(f) for part in used for f in sorted((checkpoint/part).rglob('*.safetensors'))}
    assert len(hashes)>=5,'Missing model weights'
    hash_seconds=time.monotonic()-before
    before=time.monotonic();dit=AceStepHandler()
    status,ok=dit.initialize_service(project_root=str(BASE/'source'),config_path='acestep-v15-turbo',
        device='cuda',use_flash_attention=False,compile_model=False,offload_to_cpu=False,
        offload_dit_to_cpu=False,quantization=None)
    assert ok,status;dit_seconds=time.monotonic()-before
    before=time.monotonic();lm=LLMHandler()
    status,ok=lm.initialize(checkpoint_dir=str(checkpoint),lm_model_path='acestep-5Hz-lm-4B',
        backend='vllm',device='cuda',offload_to_cpu=False,dtype=torch.bfloat16)
    assert ok,status;lm_seconds=time.monotonic()-before
    torch.cuda.synchronize()
    ready={'run':args.run,'pid':os.getpid(),'import_seconds':imported-start,'weight_hash_seconds':hash_seconds,
        'dit_init_seconds':dit_seconds,'lm_init_seconds':lm_seconds,'worker_ready_seconds':time.monotonic()-start,
        'hashes':hashes,'gpu':torch.cuda.get_device_name(0),'torch':torch.__version__,
        'backend':lm.llm_backend,'flash_attention':False,'torch_compile':False,
        'cuda_memory_allocated_bytes':torch.cuda.memory_allocated(),'cuda_memory_reserved_bytes':torch.cuda.memory_reserved()}
    write(out/'ready.json',ready)
    count=0
    def generate(label):
        nonlocal count
        count+=1;seed=42;random.seed(seed);np.random.seed(seed);torch.manual_seed(seed);torch.cuda.manual_seed_all(seed)
        params=GenerationParams(task_type='text2music',caption='Instrumental lo-fi jazz hip-hop, mellow Rhodes electric piano, warm upright bass, relaxed dusty drum groove, intimate late-night atmosphere, gentle melodic development, clean mix, no vocals.',
            lyrics='[Instrumental]',instrumental=True,bpm=100,keyscale='D minor',timesignature='4',
            duration=60.,inference_steps=8,guidance_scale=1.,seed=seed,thinking=True,
            use_cot_metas=False,use_cot_caption=False,use_cot_language=False)
        config=GenerationConfig(batch_size=1,use_random_seed=False,seeds=[seed],audio_format='flac')
        torch.cuda.reset_peak_memory_stats();before=time.monotonic()
        result=generate_music(dit,lm,params,config,save_dir=str(out/label))
        torch.cuda.synchronize();seconds=time.monotonic()-before
        assert result.success and result.audios,result.error or result.status_message
        audio=result.audios[0];path=Path(audio['path']);data,sr=sf.read(path,always_2d=True,dtype='float32')
        duration=len(data)/sr;assert np.isfinite(data).all() and 58<=duration<=62
        rms=float(np.sqrt(np.mean(data.astype('float64')**2)));assert rms>1e-5
        info={'run':args.run,'request':label,'generation_seconds':seconds,'path':str(path),'bytes':path.stat().st_size,
            'sha256':digest(path),'pcm_sha256':hashlib.sha256(data.tobytes()).hexdigest(),'sample_rate':sr,
            'channels':data.shape[1],'duration_seconds':duration,'rms':rms,'peak':float(np.max(np.abs(data))),
            'clipping_fraction':float(np.mean(np.abs(data)>=.9999)),
            'peak_cuda_memory_allocated_bytes':torch.cuda.max_memory_allocated(),
            'peak_cuda_memory_reserved_bytes':torch.cuda.max_memory_reserved(),
            'time_costs':result.extra_outputs.get('time_costs',{}),'backend':lm.llm_backend,'seed':seed}
        write(out/(label+'.json'),info)
        return info
    if args.once:
        generate('music');return
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            try:
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))) or b'{}')
                label=body.get('label',f'music-{count+1}')
                assert label.replace('-','').isalnum()
                value=generate(label);status=200
            except Exception as exc:
                value={'error':type(exc).__name__+': '+str(exc)};write(out/'error.json',value);status=500
            payload=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    HTTPServer(('127.0.0.1',8881),Handler).serve_forever()

if __name__=='__main__':main()
