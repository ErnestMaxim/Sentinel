import json
from collections import Counter
from pathlib import Path

path = Path('core/antiplagiator/data/raw/checkpoint_raw.jsonl')
cats = Counter()
total = 0
with path.open(encoding='utf-8') as f:
    for line in f:
        if line.strip():
            d = json.loads(line)
            cat = str(d.get('primary_category', '')).split('.')[0]
            cats[cat] += 1
            total += 1

print(f'Total papers: {total}')
print()
print('Category        Papers')
print('-' * 25)
for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
    print(f'{cat:<15} {count:>8}')
