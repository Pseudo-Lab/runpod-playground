"""Three paired keep/ephemeral trials with a predeclared synthetic idle interval."""
import json
import time

from experiment import run_once
from runpod_api import ROOT, save_json, utc_now


def metrics(run_id):
    return json.loads((ROOT / 'records' / run_id / 'metrics.json').read_text(encoding='utf-8'))


def trial(run_id, hold_seconds=0):
    started = time.monotonic()
    attempts = []
    for attempt in range(2):
        actual_id = run_id if attempt == 0 else run_id + '-retry1'
        before = time.monotonic() - started
        attempts.append(actual_id)
        try:
            run_once(actual_id, hold_seconds=hold_seconds)
            r = metrics(actual_id)
            for field in ('completed_results', 'first_result'):
                r['timing_seconds'][field] += before
            r['attempt_run_ids'] = attempts
            return r
        except Exception:
            failed = metrics(actual_id)
            if attempt or failed.get('resource_created') or 'no instances currently available' not in failed.get('error', ''):
                raise
            print(f'{actual_id}: capacity unavailable; retry once in 30s (included in trial time)', flush=True)
            for _ in range(3):
                time.sleep(10)
    raise RuntimeError('Unreachable trial state')


def main():
    schedule = {'declared_at_utc': utc_now(), 'idle_seconds': 300, 'pairs': 3,
                'pattern_source': 'synthetic; no natural user-session call intervals available',
                'order': [['keep', 'ephemeral'], ['ephemeral', 'keep'], ['keep', 'ephemeral']],
                'interpretation': 'Only compare this 5-minute synthetic pattern; representative-user H2 remains unverified.'}
    path = ROOT / 'records/phase-c-schedule.json'
    if path.exists():
        raise RuntimeError('Phase C schedule already exists; do not silently rerun trials')
    save_json(path, schedule)
    for pair, arms in enumerate(schedule['order'], 1):
        for arm in arms:
            print(f'Phase C pair {pair}/3: {arm}', flush=True)
            if arm == 'keep':
                run_id = f'c{pair}k'
                r = trial(run_id, hold_seconds=schedule['idle_seconds'])
                summary = {'pair': pair, 'policy': arm, 'pattern': 'synthetic_300s',
                           'run_ids': r['attempt_run_ids'], 'success_count': 2,
                           'estimated_cost_usd': r['estimated_cost_usd'],
                           'complete_seconds': r['timing_seconds']['completed_results'],
                           'second_call_seconds': r['timing_seconds']['second_call'],
                           'resident_model_reused': r['second']['resident_model_reused']}
            else:
                first_id, second_id = f'c{pair}e1', f'c{pair}e2'
                start = time.monotonic()
                first = trial(first_id)
                # Deletion occupies the beginning of the idle interval, not extra idle.
                next_intent = first['persisted_at_epoch'] + schedule['idle_seconds']
                print(f'{first_id}: waiting without a Pod until second intent', flush=True)
                while time.time() < next_intent:
                    time.sleep(min(10, max(0, next_intent - time.time())))
                second = trial(second_id)
                summary = {'pair': pair, 'policy': arm, 'pattern': 'synthetic_300s',
                           'run_ids': first['attempt_run_ids'] + second['attempt_run_ids'], 'success_count': 2,
                           'estimated_cost_usd': first['estimated_cost_usd'] + second['estimated_cost_usd'],
                           'complete_seconds': (time.monotonic() - start
                               - second['timing_seconds']['delete_confirm']),
                           'second_call_seconds': second['timing_seconds']['first_result'],
                           'resident_model_reused': False}
            save_json(ROOT / 'records' / f'c{pair}-{arm}.json', summary)
            print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
