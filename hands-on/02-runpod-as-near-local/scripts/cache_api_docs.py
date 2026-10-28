"""Cache public RunPod API documentation without credentials or account responses."""
import argparse
import hashlib
import json
from datetime import datetime, timezone

import requests

from runpod_api import ROOT, save_json, utc_now

CACHE = ROOT / 'cache/runpod-api'
SOURCES = {
    'openapi.json': 'https://rest.runpod.io/v1/openapi.json',
    'graphql-manage-pods.mdx': 'https://raw.githubusercontent.com/runpod/docs/main/sdks/graphql/manage-pods.mdx',
    's3-api.mdx': 'https://raw.githubusercontent.com/runpod/docs/main/storage/s3-api.mdx',
}
TTL_SECONDS = 7 * 24 * 60 * 60


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    index = CACHE / 'index.json'
    if index.exists() and not args.refresh:
        cached = json.loads(index.read_text(encoding='utf-8'))
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached['fetched_at_utc'])).total_seconds()
        if 0 <= age < TTL_SECONDS and all((CACHE / name).exists() for name in SOURCES):
            print('Using local RunPod API documentation cache')
            return
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0 runpod-experiment'
    files = []
    CACHE.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        response = session.get(url, timeout=(10, 40))
        response.raise_for_status()
        raw = response.content
        if name.endswith('.json'):
            json.loads(raw)
        (CACHE / name).write_bytes(raw)
        files.append({'path': name, 'source': url, 'sha256': hashlib.sha256(raw).hexdigest(),
                      'bytes': len(raw)})
    save_json(index, {'fetched_at_utc': utc_now(), 'ttl_seconds': TTL_SECONDS,
                      'contains_credentials': False, 'files': files})
    print('Cached public API documentation:', ', '.join(SOURCES))


if __name__ == '__main__':
    main()
