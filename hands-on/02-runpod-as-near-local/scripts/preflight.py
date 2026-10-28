"""Read-only discovery and 24-hour GPU price cache; creates no paid resources."""
import argparse
import json
from datetime import datetime, timezone

from runpod_api import ROOT, Runpod, credentials, save_json, utc_now

CACHE = ROOT / 'cache/gpu-prices.json'
TTL_SECONDS = 24 * 60 * 60


def price_cache(api, refresh=False):
    if CACHE.exists() and not refresh:
        cached = json.loads(CACHE.read_text(encoding='utf-8'))
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached['fetched_at_utc'])).total_seconds()
        if cached.get('schema_version') == 1 and 0 <= age < TTL_SECONDS:
            return cached, True
    catalog = api.graphql('''{ gpuTypes { id displayName memoryInGb securePrice communityPrice }
                             dataCenters { id location s3apiEnabled } }''')
    dcs = [dc for dc in catalog['dataCenters'] if dc['s3apiEnabled']]
    fields = []
    for i, dc in enumerate(dcs):
        fields.append(f'''dc{i}: gpuTypes {{ id lowestPrice(input: {{gpuCount:1,
             secureCloud:true, dataCenterId:{json.dumps(dc['id'])},
             minMemoryInGb:16, minVcpuCount:2, supportPublicIp:true}})
             {{ uninterruptablePrice stockStatus }} }}''')
    quotes = api.graphql('{ ' + '\n'.join(fields) + ' }')
    rows = []
    for i, dc in enumerate(dcs):
        for gpu in quotes[f'dc{i}']:
            price = gpu.get('lowestPrice')
            if price and price.get('uninterruptablePrice') is not None:
                rows.append({'gpu_type': gpu['id'], 'data_center': dc['id'],
                             'usd_per_gpu_hour': price['uninterruptablePrice'],
                             'stock_at_fetch': price.get('stockStatus')})
    result = {'schema_version': 1, 'fetched_at_utc': utc_now(), 'ttl_seconds': TTL_SECONDS,
              'source': 'https://api.runpod.io/graphql', 'currency': 'USD',
              'cloud_type': 'SECURE', 'billing': 'ON_DEMAND', 'gpu_count': 1,
              'note': 'Prices are cached; stock_at_fetch is historical, not live availability.',
              'catalog': catalog['gpuTypes'], 'data_centers': dcs, 'quotes': rows}
    save_json(CACHE, result)
    return result, False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-prices', action='store_true')
    args = parser.parse_args()
    api = Runpod()
    cache, reused = price_cache(api, args.refresh_prices)
    availability = api.graphql('''{ myself { clientBalance currentSpendPerHr }
        dataCenters { id s3apiEnabled gpuAvailability(input:{gpuCount:1,secureCloud:true,
        minMemoryInGb:16,minVcpuCount:2}) { gpuTypeId available stockStatus } } }''')
    refs = [q for q in cache['quotes'] if q['gpu_type'] == 'NVIDIA GeForce RTX 5090'
            and q['stock_at_fetch'] not in (None, 'None', 'Unavailable')]
    if not refs:
        raise RuntimeError('No RTX 5090 reference quote; do not create resources.')
    reference = min(refs, key=lambda q: q['usd_per_gpu_hour'])
    live = {(dc['id'], g['gpuTypeId']) for dc in availability['dataCenters']
            if dc['s3apiEnabled'] for g in dc['gpuAvailability'] if g['available']}
    candidates = sorted([q for q in cache['quotes']
                         if q['usd_per_gpu_hour'] <= reference['usd_per_gpu_hour']
                         and (q['data_center'], q['gpu_type']) in live],
                        key=lambda q: q['usd_per_gpu_hour'])
    env = credentials()
    report = {'checked_at_utc': utc_now(), 'cache_reused': reused,
              'cache_path': 'cache/gpu-prices.json', 'reference_5090': reference,
              'candidates': candidates,
              's3_credentials_present': all(env.get(k) for k in (
                  'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY')),
              'existing_pods': len(api.request('GET', 'pods')),
              'existing_network_volumes': len(api.request('GET', 'networkvolumes')),
              'paid_resources_created': False}
    save_json(ROOT / 'records/preflight.json', report)
    account_before = ROOT / 'private/account-before.json'
    if not account_before.exists():
        save_json(account_before, availability['myself'])
    save_json(ROOT / 'private/account-latest.json', availability['myself'])
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
