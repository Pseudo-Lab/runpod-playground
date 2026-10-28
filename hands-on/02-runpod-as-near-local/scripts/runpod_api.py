"""Local API access. Never send control-plane credentials to a Pod."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def credentials():
    values = dict(dotenv_values(ROOT / '.env'))
    values.update({k: v for k, v in os.environ.items() if k in (
        'RUNPOD_API_KEY', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY')})
    return values


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


class Runpod:
    def __init__(self):
        self.key = credentials().get('RUNPOD_API_KEY')
        if not self.key:
            raise RuntimeError('Missing RUNPOD_API_KEY in .env')
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': 'Bearer ' + self.key,
            'User-Agent': 'Mozilla/5.0 runpod-experiment',
        })

    def request(self, method, path, body=None):
        # No automatic retries for mutations: reconcile an uncertain create first.
        response = self.session.request(method, 'https://rest.runpod.io/v1/' + path,
                                        json=body, timeout=(10, 40))
        if not response.ok:
            raise RuntimeError(f'Runpod {method} {path}: HTTP {response.status_code}: '
                               + response.text[:500].replace(self.key, '[REDACTED]'))
        return response.json() if response.content else None

    def graphql(self, query):
        response = self.session.post('https://api.runpod.io/graphql',
                                     json={'query': query}, timeout=(10, 40))
        if not response.ok:
            raise RuntimeError(f'GraphQL HTTP {response.status_code}')
        result = response.json()
        if result.get('errors'):
            raise RuntimeError(json.dumps(result['errors']).replace(self.key, '[REDACTED]'))
        return result['data']
