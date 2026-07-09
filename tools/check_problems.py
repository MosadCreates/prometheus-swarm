import json
p = json.load(open("research/benchmark/problems.json"))
print(f"Total problems: {len(p)}")
for x in p:
    print(f"  {x['id']}: {x['dataset']['name']} ({x['modality']}) | {x['task_type']}")
