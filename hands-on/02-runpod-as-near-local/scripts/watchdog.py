"""Independent deadline cleanup. Only delete exact names owned by this experiment."""
import argparse
import json
import time
from pathlib import Path

from runpod_api import ROOT, Runpod, utc_now


def sweep(api, ledger, dry_run=False):
    actions = []
    now = time.time()
    for kind in ('pod', 'volume'):
        endpoint = 'pods' if kind == 'pod' else 'networkvolumes'
        expired = [r for r in ledger.get('resources', [])
                   if r['kind'] == kind and not r.get('deleted') and r['expires_at'] <= now]
        if not expired:
            continue
        existing = api.request('GET', endpoint)
        for owned in expired:
            for actual in existing:
                if actual['name'] != owned['name']:
                    continue
                if owned.get('id') and actual['id'] != owned['id']:
                    continue
                if kind == 'volume':
                    pods = api.request('GET', 'pods')
                    if any(p.get('networkVolume', {}).get('id') == actual['id']
                           for p in pods if p.get('networkVolume')):
                        continue
                actions.append({'at_utc': utc_now(), 'kind': kind, 'id': actual['id'],
                                'name': actual['name'], 'dry_run': dry_run})
                if not dry_run:
                    api.request('DELETE', endpoint + '/' + actual['id'])
    return actions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ledger', default='private/ledger.json')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    path = ROOT / args.ledger
    api = Runpod()
    while True:
        try:
            ledger = json.loads(path.read_text(encoding='utf-8'))
            if ledger.get('finished'):
                return
            for event in sweep(api, ledger, args.dry_run):
                with (ROOT / 'private/watchdog-events.jsonl').open('a', encoding='utf-8') as f:
                    f.write(json.dumps(event) + '\n')
                print(json.dumps(event), flush=True)
        except Exception as exc:
            print(type(exc).__name__ + ': ' + str(exc), flush=True)
        if args.once:
            return
        time.sleep(10)


if __name__ == '__main__':
    main()
