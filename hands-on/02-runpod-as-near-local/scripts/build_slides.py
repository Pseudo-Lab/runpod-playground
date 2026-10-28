"""Build an offline HTML deck from the recorded experiment data."""
import hashlib
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'records/followup'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def svg(body, width, height, label):
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(label)}" '
            f'xmlns="http://www.w3.org/2000/svg"><title>{html.escape(label)}</title>{body}</svg>')


def text(x, y, value, size=24, color='#65736a', anchor='start', weight=400):
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}" fill="{color}" font-size="{size}" font-weight="{weight}">{html.escape(str(value))}</text>'


def loss_chart():
    body = ''
    colors = {'baseline': '#244137', 'full': '#33996b', 'weights': '#ba6a3d'}
    for i, seed in enumerate((11, 22, 33)):
        left = 65 + i * 458
        top, width, height = 58, 365, 310
        body += text(left + width / 2, 28, f'seed {seed}', 27, '#233b31', 'middle', 650)
        for tick in (0, 1, 2, 3, 4, 5):
            y = top + height - tick / 5.5 * height
            body += f'<path d="M{left},{y}h{width}" stroke="#dce1d4"/>'
            body += text(left - 15, y + 7, tick, 20, anchor='end')
        for tick in (0, 60, 120):
            x = left + tick / 120 * width
            body += text(x, top + height + 31, tick, 20, anchor='middle')
        for mode in ('baseline', 'full', 'weights'):
            rows = read(R / f'train-{mode}-{seed}/result.json')['rows']
            points = ' '.join(f'{left+r["step"]/120*width:.2f},{top+height-r["loss"]/5.5*height:.2f}' for r in rows)
            dash = ' stroke-dasharray="9 7"' if mode == 'full' else (' stroke-dasharray="3 6"' if mode == 'weights' else '')
            body += f'<polyline points="{points}" fill="none" stroke="{colors[mode]}" stroke-width="3.6"{dash}/>'
        x = left + .5 * width
        body += f'<path d="M{x},{top}v{height}" stroke="#9aab98" stroke-dasharray="4 5"/>'
        body += text(left + width / 2, 437, 'optimizer step', 20, anchor='middle')
    for x, mode, label in ((300, 'baseline', '무중단'), (600, 'full', '전체 상태 복구'), (1000, 'weights', '가중치만 복구')):
        dash = '' if mode == 'baseline' else (' stroke-dasharray="9 7"' if mode == 'full' else ' stroke-dasharray="3 6"')
        body += f'<path d="M{x-65},475h48" stroke="{colors[mode]}" stroke-width="4"{dash}/>'
        body += text(x, 483, label, 23, '#3c5144')
    body += text(2, 28, 'loss', 20)
    return svg(body, 1400, 510, '세 seed의 학습 loss. 전체 상태 복구는 무중단과 겹치고, 가중치만 복구는 다른 곡선을 따른다.')


def storage_chart():
    rows = [read(R / f'storage-{b}-{a}/result.json') for b in (1, 2, 3) for a in 'ABC']
    fields = [('dependency_copy_seconds', '의존성 복사', '#9bb2be'),
              ('model_copy_seconds', '모델 복사', '#edb66e'), ('import_seconds', 'import', '#8072ac'),
              ('hash_seconds', 'hash 검증', '#a3cf91'), ('load_seconds', '모델 로드', '#307c88'),
              ('inference_seconds', '추론', '#d77a5b')]
    body = ''
    for tick in (0, 20, 40, 60, 80, 100):
        y = 440 - tick * 3.8
        body += f'<path d="M75,{y}H1355" stroke="#d8ded0"/>' + text(58, y + 7, tick, 22, anchor='end')
    for i, row in enumerate(rows):
        x, baseline = 115 + i * 140, 440
        total = 0
        for key, _, color in fields:
            value = row[key]
            h = value * 3.8
            body += f'<rect x="{x}" y="{baseline-h:.2f}" width="85" height="{h:.2f}" fill="{color}"/>'
            baseline -= h
            total += value
        h = max(0, row['total_seconds'] - total) * 3.8
        body += f'<rect x="{x}" y="{baseline-h:.2f}" width="85" height="{h:.2f}" fill="#dddcd3"/>'
        body += text(x + 42, baseline - h - 13, f'{row["total_seconds"]:.1f}', 21, '#344d3e', 'middle', 650)
        body += text(x + 42, 478, row['run_id'].replace('storage-', ''), 23, anchor='middle')
    body += text(27, 32, '초', 22)
    for i, (_, label, color) in enumerate(fields):
        x, y = 110 + (i % 3) * 430, 533 + (i // 3) * 39
        body += f'<rect x="{x}" y="{y-17}" width="22" height="22" fill="{color}"/>' + text(x + 35, y, label, 22)
    return svg(body, 1400, 600, '새 Pod 세 블록의 저장 위치별 9회 측정. 막대 높이는 복사비용을 포함한 전체시간이다.')


def stage_chart():
    r = read(R / 'storage-1-A/result.json')
    parts = [(r['import_seconds'], 'Python import', '#295f4b'),
             (r['hash_seconds'], 'hash 검증', '#9eb38c'),
             (r['load_seconds'], '모델 로드', '#bd8052'),
             (r['inference_seconds'], '추론', '#dbab7f')]
    parts.append((r['total_seconds'] - sum(x[0] for x in parts), '기타', '#dadfd2'))
    body, x = '', 0
    for value, label, color in parts:
        width = value / r['total_seconds'] * 1400
        body += f'<rect x="{x:.2f}" y="40" width="{width:.2f}" height="100" fill="{color}"/>'
        if label == 'Python import':
            body += text(34, 104, f'{label}  {value:.1f}초', 36, '#ffffff', weight=650)
        x += width
    for i, (value, label, color) in enumerate(parts):
        x = i * 280
        body += f'<rect x="{x}" y="184" width="15" height="15" fill="{color}"/>'
        body += text(x + 26, 199, label, 23)
        body += text(x + 26, 245, f'{value:.1f}초', 34, '#233b31', weight=650)
    return svg(body, 1400, 280, '첫 블록 A의 전체 38.4초 중 import가27.4초를 차지했다.')


def bars(values, labels, colors, maximum, suffix='초'):
    body = ''
    for i, (value, label, color) in enumerate(zip(values, labels, colors)):
        y = 35 + i * 114
        width = value / maximum * 970
        body += text(0, y + 39, label, 29, '#334c3c', weight=600)
        body += f'<rect x="270" y="{y}" width="970" height="57" rx="2" fill="#e5e9dd"/>'
        body += f'<rect x="270" y="{y}" width="{width:.2f}" height="57" rx="2" fill="{color}"/>'
        body += text(1273, y + 41, f'{value:.1f}{suffix}', 30, '#233b31', weight=650)
    return svg(body, 1400, 60 + len(values) * 114, '동일 척도의 시간 비교')


def timeline():
    body = text(90, 40, '중단 전 Pod', 25, '#65736a') + text(90, 300, '삭제 후 새 Pod', 25, '#65736a')
    body += '<path d="M120 150H874" stroke="#a4b39a" stroke-width="5"/><path d="M740 410H1360" stroke="#295f4b" stroke-width="5"/>'
    body += '<path d="M740 410H874" stroke="#bb754b" stroke-width="8" stroke-dasharray="8 8"/>'
    for step in (0, 20, 40, 60, 73):
        x = 120 + step / 120 * 1240
        color = '#b2643e' if step == 73 else '#295f4b'
        body += f'<circle cx="{x:.2f}" cy="150" r="{14 if step in (60,73) else 9}" fill="{color}"/>'
        body += text(x, 207, step, 29, '#233b31', 'middle', 650)
    body += text(740, 100, '최신 확정 checkpoint', 25, '#295f4b', 'middle', 600)
    body += text(940, 154, '프로세스 종료', 26, '#a95532', weight=650)
    body += '<path d="M740 226V375" stroke="#8ea383" stroke-width="3" stroke-dasharray="7 8"/>'
    body += text(769, 320, '상태 복원', 24, '#295f4b')
    for step in (60, 73, 120):
        x = 120 + step / 120 * 1240
        body += f'<circle cx="{x:.2f}" cy="410" r="12" fill="#295f4b"/>' + text(x, 465, step, 29, '#233b31', 'middle', 650)
    body += text(240, 405, '13', 108, '#aa5938', weight=650) + text(240, 457, 'step 재계산', 28, '#aa5938')
    return svg(body, 1400, 510, '73step에서 중단하고 최신 checkpoint60step으로 복구해13step을 다시 계산했다.')


def main():
    summary = read(ROOT / 'reports/followup-results.json')
    assert summary['all_tokens_and_hashes_match']
    replacements = {
        '{{loss_chart}}': loss_chart(), '{{storage_chart}}': storage_chart(),
        '{{stage_chart}}': stage_chart(), '{{timeline}}': timeline(),
        '{{import_chart}}': bars([24.442, 2.287], ['A  volume 직접', 'B  의존성 복사'], ['#295f4b', '#b8794c'], 27),
        '{{total_chart}}': bars([summary['storage_median_total_seconds'][a] for a in 'ABC'],
            ['A  volume 직접', 'B  의존성 복사', 'C  모델까지 복사'], ['#295f4b', '#b8794c', '#cba17a'], 95),
    }
    # Keep full-precision source measurements behind the displayed rounded values.
    imports = []
    import statistics
    for a in 'AB':
        imports.append(statistics.median(read(R / f'storage-{b}-{a}/result.json')['import_seconds'] for b in (1,2,3)))
    replacements['{{import_chart}}'] = bars(imports, ['A  volume 직접', 'B  의존성 복사'], ['#295f4b', '#b8794c'], 27)
    template = (ROOT / 'deck/template.html').read_text(encoding='utf-8')
    notes = read(ROOT / 'deck/notes.json')
    assert len(notes) == 25
    note_iter = iter(notes)
    def replace_note(_):
        note = next(note_iter)
        paragraphs = ''.join('<p>' + html.escape(p) + '</p>' for p in note['text'].split('\n\n'))
        return '<aside class="speaker-notes">' + paragraphs + '<p class="source">근거: ' + html.escape(note['source']) + '</p></aside>'
    template, count = re.subn(r'<aside class="speaker-notes">.*?</aside>', replace_note, template, flags=re.S)
    assert count == 25
    footnotes = read(ROOT / 'deck/footnotes.json')
    assert len(footnotes) == 25
    slide_iter = iter(footnotes)
    def replace_footnote(match):
        value = next(slide_iter)
        content = match[0]
        if value is not None:
            content, count = re.subn(r'<p class="footnote">.*?</p>',
                '<p class="footnote">' + html.escape(value) + '</p>', content, flags=re.S)
            assert count == 1
        return content
    template, count = re.subn(r'<section class="slide\b[^>]*>.*?</section>', replace_footnote, template, flags=re.S)
    assert count == 25
    for key, value in replacements.items():
        assert template.count(key) == 1, key
        template = template.replace(key, value)
    assert '{{' not in template
    output = ROOT / 'slides.html'
    output.write_text(template, encoding='utf-8')
    print(json.dumps({'path': str(output), 'bytes': output.stat().st_size,
                      'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
