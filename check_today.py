import urllib.request
import json
url = "https://api.github.com/repos/ranimela/arbox-scheduler/actions/runs?per_page=5"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla"})
try:
    with urllib.request.urlopen(req) as r:
        runs = json.loads(r.read().decode())["workflow_runs"]
        for x in runs:
            print(f"{x.get('run_number')}: name={x.get('name')}, status={x.get('status')}, conclusion={x.get('conclusion')}, created_at={x.get('created_at')}")
except Exception as e:
    print(e)
