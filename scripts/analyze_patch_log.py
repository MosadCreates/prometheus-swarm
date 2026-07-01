import json
from collections import Counter, defaultdict

PATCH_LOG_PATH = r"C:\Users\moham\OneDrive\Desktop\prometheus-swarm\research\patch_log.jsonl"
OUTPUT_PATH = r"C:\Users\moham\OneDrive\Desktop\prometheus-swarm\outputs\patch_log_analysis.json"

entries = []
with open(PATCH_LOG_PATH) as f:
    for line in f:
        line = line.strip()
        if line:
            entries.append(json.loads(line))

total_entries = len(entries)

outcome_counter = Counter()
category_counter = Counter()
confidence_by_outcome = defaultdict(list)
confidences = []
lines_changed_list = []
durations = []

for e in entries:
    outcome = e.get("patch_outcome", "unknown")
    outcome_counter[outcome] += 1

    cat = e.get("error_taxonomy_category", "unknown")
    category_counter[cat] += 1

    conf = e.get("confidence_score")
    if conf is not None:
        confidences.append(conf)
        confidence_by_outcome[outcome].append(conf)

    lc = e.get("lines_changed")
    if lc is not None:
        lines_changed_list.append(lc)

    ts = e.get("timestamp")
    if ts:
        durations.append(ts)

outcome_distribution = {
    outcome: {
        "count": count,
        "percentage": round(count / total_entries * 100, 2) if total_entries > 0 else 0.0,
    }
    for outcome, count in sorted(outcome_counter.items())
}

avg_confidence_overall = round(sum(confidences) / len(confidences), 4) if confidences else 0.0

avg_confidence_by_outcome = {}
for outcome, vals in confidence_by_outcome.items():
    avg_confidence_by_outcome[outcome] = round(sum(vals) / len(vals), 4)

avg_lines_changed = (
    round(sum(lines_changed_list) / len(lines_changed_list), 2) if lines_changed_list else 0.0
)

error_taxonomy = {
    cat: {
        "count": count,
        "percentage": round(count / total_entries * 100, 2) if total_entries > 0 else 0.0,
    }
    for cat, count in sorted(category_counter.items(), key=lambda x: -x[1])
}

most_common_categories = [cat for cat, _ in category_counter.most_common(5)]

print("=" * 60)
print("PATCH LOG ANALYSIS")
print("=" * 60)
print(f"\nTotal patch entries: {total_entries}")

print("\n--- Patch Outcome Distribution ---")
for outcome, info in sorted(outcome_distribution.items()):
    print(f"  {outcome:12s}: {info['count']:>3} ({info['percentage']:.2f}%)")

print("\n--- Average Confidence Score ---")
print(f"  Overall:           {avg_confidence_overall}")
for outcome in sorted(avg_confidence_by_outcome):
    print(f"  {outcome:12s}: {avg_confidence_by_outcome[outcome]}")

print("\n--- Lines Changed ---")
print(f"  Average: {avg_lines_changed}")

if lines_changed_list:
    print(f"  Min:     {min(lines_changed_list)}")
    print(f"  Max:     {max(lines_changed_list)}")

print("\n--- Error Taxonomy Distribution ---")
for cat, info in error_taxonomy.items():
    print(f"  {cat:30s}: {info['count']:>3} ({info['percentage']:.2f}%)")

print("\n--- Most Common Error Categories ---")
for i, cat in enumerate(most_common_categories[:5], 1):
    info = error_taxonomy[cat]
    print(f"  {i}. {cat} ({info['count']} occurrences)")

if len(entries) >= 2 and durations:
    print("\n--- Patch Duration ---")
    print(f"  Timestamps available: {len(durations)}")

analysis = {
    "source_file": "research/patch_log.jsonl",
    "total_entries": total_entries,
    "patch_outcome_distribution": outcome_distribution,
    "average_confidence_score": {
        "overall": avg_confidence_overall,
        "by_outcome": avg_confidence_by_outcome,
    },
    "average_lines_changed": avg_lines_changed,
    "lines_changed_range": {
        "min": min(lines_changed_list) if lines_changed_list else None,
        "max": max(lines_changed_list) if lines_changed_list else None,
    },
    "error_taxonomy_distribution": error_taxonomy,
    "most_common_error_categories": most_common_categories,
}

with open(OUTPUT_PATH, "w") as f:
    json.dump(analysis, f, indent=2)

print(f"\nResults saved to: {OUTPUT_PATH}")
