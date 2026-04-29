import json
from pathlib import Path

NEW_TARGETS = {
    "cs":        10000,
    "math":       8000,
    "physics":    8000,
    "astro-ph":   6000,
    "cond-mat":   6000,
    "quant-ph":   5000,
    "stat":       5000,
    "hep-ph":     4000,
    "hep-th":     4000,
    "gr-qc":      3000,
    "eess":       3000,
    "q-bio":      2000,
    "hep-ex":     2000,
    "nucl-th":    2000,
    "nucl-ex":    2000,
    "math-ph":    2000,
    "hep-lat":    2000,
    "econ":       2000,
    "nlin":       2000,
    "q-fin":      2000,
}

# ── Fix 1: update category_state.json counts from actual checkpoint data ──
checkpoint_path = Path("backend/core/antiplagiator/data/raw/checkpoint_raw.jsonl")
state_path      = Path("backend/core/antiplagiator/data/raw/category_state.json")
done_path       = Path("backend/core/antiplagiator/data/raw/checkpoint_raw_done_cats.json")

# Count actual papers per category in the checkpoint
actual_counts: dict[str, int] = {}
with checkpoint_path.open("r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        record = json.loads(line)
        cat = str(record.get("primary_category", "")).split(".")[0]  # top-level code
        actual_counts[cat] = actual_counts.get(cat, 0) + 1

print("Actual counts from checkpoint:")
for cat, count in sorted(actual_counts.items()):
    print(f"  {cat}: {count}")

# Load existing state
with state_path.open("r") as f:
    state = json.load(f)

# Update counts to match reality, keep offsets
for cat in state:
    real_count = actual_counts.get(cat, state[cat]["count"])
    old_count  = state[cat]["count"]
    if real_count != old_count:
        print(f"Fixing {cat}: count {old_count} → {real_count}")
        state[cat]["count"] = real_count

# Add any missing categories with 0
for cat in NEW_TARGETS:
    if cat not in state:
        state[cat] = {"offset": 0, "count": 0}
        print(f"Added missing category: {cat}")

with state_path.open("w") as f:
    json.dump(state, f, indent=2)
print("\ncategory_state.json updated.")

# ── Fix 2: clear done_cats for everything below new target ────────────────
if done_path.exists():
    with done_path.open("r") as f:
        done_cats = set(json.load(f))
else:
    done_cats = set()

still_done = [
    cat for cat in done_cats
    if state.get(cat, {}).get("count", 0) >= NEW_TARGETS.get(cat, 9999999)
]
removed = done_cats - set(still_done)

with done_path.open("w") as f:
    json.dump(still_done, f, indent=2)

print(f"\nCleared from done list ({len(removed)} categories): {sorted(removed)}")
print(f"Still marked done ({len(still_done)} categories): {sorted(still_done)}")
print("\nReady to run extractor with --resume.")