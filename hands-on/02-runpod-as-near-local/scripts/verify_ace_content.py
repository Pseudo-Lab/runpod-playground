"""Check delivered ACE artifacts and their local evidence without cloud access."""
import hashlib
import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from dotenv import dotenv_values
from runpod_api import ROOT,save_json
from ace_slides import MAIN_COUNT,APPENDIX_COUNT

class Page(HTMLParser):
    def __init__(self):
        super().__init__();self.main=0;self.hidden=0;self.text=[];self.links=[];self.scripts=[];self.script=None;self.slides=0;self.audio=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='main':self.main+=1
        if tag in ('script','style'):self.hidden+=1
        if tag=='script':self.script=[]
        if tag=='a' and 'href' in a:self.links.append(a['href'])
        if tag=='section' and 'slide' in a.get('class','').split():self.slides+=1
        if tag=='audio':
            self.audio+=1
            assert 'autoplay' not in a
            assert a['src'].startswith('data:audio/mpeg;base64,')
    def handle_endtag(self,tag):
        if tag=='main':self.main-=1
        if tag in ('script','style'):self.hidden-=1
        if tag=='script':self.scripts.append(''.join(self.script));self.script=None
    def handle_data(self,data):
        if self.main and not self.hidden:self.text.append(data)
        if self.script is not None:self.script.append(data)

def main():
    pages={};hashes={}
    secrets=[v for k,v in dotenv_values(ROOT/'.env').items() if v and ('KEY' in k or 'SECRET' in k)]
    for filename in ('blog.html','slides.html'):
        source=(ROOT/filename).read_text(encoding='utf-8')
        assert not any(value in source for value in secrets),'Credential found in output'
        assert not re.search(r'\{\{\w+\}\}',source)
        assert '\ufffd' not in source and '계산대' not in source
        p=Page();p.feed(source);pages[filename]=p;hashes[filename]=hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()
        for i,script in enumerate(p.scripts):
            path=ROOT/'private'/f'ace-check-{filename}-{i}.js';path.write_text(script,encoding='utf-8')
            subprocess.run(['node','--check',str(path)],check=True,stdout=subprocess.DEVNULL)
        for href in p.links:
            if href.startswith(('http:','https:','#','mailto:','data:')):continue
            assert (ROOT/href.split('#')[0]).exists(),f'Missing evidence: {href}'
        assert p.audio==2
    count=len(re.sub(r'\s+','',''.join(pages['blog.html'].text)))
    assert count>=4023*3
    assert pages['slides.html'].slides==MAIN_COUNT+APPENDIX_COUNT
    for manifest in ('preregistered.json','policy-preregistered.json'):
        r=json.loads((ROOT/'records/ace-step'/manifest).read_text(encoding='utf-8'))
        assert all(hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h for f,h in r['source_sha256'].items())
    r=json.loads((ROOT/'reports/ace-step-results.json').read_text(encoding='utf-8'))
    assert r['all_music_files_locally_decoded_and_pcm_hash_verified']==23
    assert r['cleanup']['account_pod_count']==r['cleanup']['account_network_volume_count']==0
    result={'previous_main_chars_without_whitespace':4023,'current_main_chars_without_whitespace':count,
        'main_text_ratio':count/4023,'slides':MAIN_COUNT+APPENDIX_COUNT,'main_slides':MAIN_COUNT,'appendix_slides':APPENDIX_COUNT,
        'source_hashes_match':True,'relative_blog_links_resolve':True,'credential_scan':'passed',
        'inline_javascript_syntax':'passed','audio_players_per_document':2,'sha256':hashes,
        'resource_cleanup_evidence':'records/ace-step/final-cleanup.json'}
    save_json(ROOT/'reports/ace-content-verification.json',result)
    print(json.dumps(result,ensure_ascii=True,indent=2))

if __name__=='__main__':main()
