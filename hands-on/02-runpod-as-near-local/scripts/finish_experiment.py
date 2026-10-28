"""Verify local backups, delete owned resources, and capture final billing evidence."""
import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlencode

from experiment import cleanup, load_ledger
from runpod_api import ROOT, Runpod, save_json, utc_now


def main():
    verified = 0
    for path in (ROOT / 'records').glob('*/manifest.complete.json'):
        manifest = json.loads(path.read_text(encoding='utf-8'))
        raw = (path.parent / manifest['file']).read_bytes()
        if len(raw) != manifest['bytes'] or hashlib.sha256(raw).hexdigest() != manifest['sha256']:
            raise RuntimeError('Local backup checksum failed: ' + str(path.parent))
        verified += 1
    if not verified:
        raise RuntimeError('No verified local inference results; review before deleting storage')
    verified_second = 0
    for path in (ROOT / 'records').glob('*/second-result.json'):
        second = json.loads(path.read_text(encoding='utf-8'))
        metrics = json.loads((path.parent / 'metrics.json').read_text(encoding='utf-8'))
        if second != metrics.get('second') or second.get('status') != 'complete':
            raise RuntimeError('Second-inference backup mismatch: ' + str(path.parent))
        if not second.get('generated_token_ids') or not second.get('generated_text', '').strip():
            raise RuntimeError('Second-inference backup is empty')
        verified_second += 1
    cleanup(all_resources=True)
    api = Runpod()
    state = load_ledger()
    pods = api.request('GET', 'pods')
    volumes = api.request('GET', 'networkvolumes')
    owned_ids = {r['id'] for r in state['resources'] if r.get('id')}
    remaining_owned = [r for r in pods + volumes if r['id'] in owned_ids]
    if remaining_owned:
        raise RuntimeError('Owned resources remain after cleanup')
    account = api.graphql('{myself {clientBalance currentSpendPerHr}}')['myself']
    save_json(ROOT / 'private/account-after.json', account)
    start = datetime.fromisoformat(state['started_at_utc']).replace(minute=0, second=0, microsecond=0)
    end = datetime.now(timezone.utc)
    billing = {}
    for kind in ('pods', 'networkvolumes'):
        try:
            params = {'startTime': start.isoformat(), 'endTime': end.isoformat(), 'bucketSize': 'hour'}
            if kind == 'pods':
                params['grouping'] = 'podId'
            query = urlencode(params)
            billing[kind] = api.request('GET', 'billing/' + kind + '?' + query)
        except Exception as exc:
            billing[kind] = {'error': type(exc).__name__ + ': ' + str(exc)}
    save_json(ROOT / 'private/billing-final-query.json', billing)
    initial = json.loads((ROOT / 'private/account-initial.json').read_text(encoding='utf-8'))
    final = {'at_utc': utc_now(), 'local_artifacts_verified': verified,
             'resident_second_inference_backups_verified': verified_second,
             'remaining_owned_resources': 0, 'account_pod_count': len(pods),
             'account_network_volume_count': len(volumes),
             'account_current_spend_per_hour': account['currentSpendPerHr'],
             'observed_account_balance_decrease_usd': initial['clientBalance'] - account['clientBalance'],
             'balance_change_note': 'Observed account-level change, not a finalized per-run invoice.',
             'billing_response_available': {k: bool(v) and isinstance(v, list) for k, v in billing.items()},
             'billing_finalized': False,
             'watchdog_exit_requested': state['finished']}
    save_json(ROOT / 'records/final-cleanup.json', final)
    cfg = json.loads((ROOT / 'experiment.json').read_text(encoding='utf-8'))
    cfg['status'] = 'experiment_finished_resources_deleted'
    save_json(ROOT / 'experiment.json', cfg)
    print(json.dumps(final), flush=True)


if __name__ == '__main__':
    main()
