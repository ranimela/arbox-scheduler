import urllib.request
import json
import zipfile
import io

runs = {74: 26650918284, 75: 26686920802}
for run_num, db_id in runs.items():
    print(f"\n--- Logs for Run {run_num} ---")
    url = f"https://api.github.com/repos/ranimela/arbox-scheduler/actions/runs/{db_id}/logs"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla"})
    try:
        with urllib.request.urlopen(req) as r:
            zip_data = r.read()
            with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
                # Find log file for run step
                for name in z.namelist():
                    if "Run Arbox Scheduler Agent" in name or "4_" in name:
                        print(f"File: {name}")
                        log_content = z.read(name).decode("utf-8", errors="ignore")
                        # Print last 30 lines
                        lines = log_content.splitlines()
                        for line in lines[-30:]:
                            print(line)
    except Exception as e:
        print("Error fetching logs:", e)
