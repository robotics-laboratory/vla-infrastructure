from pathlib import Path
import json
import subprocess
import sys
import os
import time
import threading

c = json.loads(Path(sys.argv[1]).read_text())
prefix = Path(c["prefix"])
source = Path(c["source"])
env = os.environ.copy()
env.update(c.get("env", {}))
cmd = [*c.get("prefix_command", []), c["python"], str(source), *c["args"]]
receipt = dict(
    command=cmd,
    source=str(source),
    sources={str(p): p.read_text() for p in source.parent.glob("*.py")},
    launcher_source=Path(__file__).read_text(),
    selected_environment=c.get("env", {}),
    started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
)
prefix.with_suffix(".launch.json").write_text(json.dumps(receipt, indent=2) + "\n")
rows = []
done = threading.Event()
proc = None


def monitor():
    while not done.is_set():
        try:
            raw = subprocess.check_output(
                ["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader"],
                text=True,
                timeout=5,
            )
            rows.append(dict(wall_ns=time.time_ns(), active=raw))
        except Exception as e:
            rows.append(dict(wall_ns=time.time_ns(), error=str(e)))
        done.wait(1)


thread = threading.Thread(target=monitor)
thread.start()
start = time.monotonic()
result = {}
try:
    with prefix.with_suffix(".log").open("w") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
        result["child_pid"] = proc.pid
        result["returncode"] = proc.wait(timeout=c.get("timeout", 300))
except Exception as e:
    result["launcher_error"] = repr(e)
    if proc and proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=20)
finally:
    done.set()
    thread.join()
    result["elapsed_s"] = time.monotonic() - start
    result["monitor"] = rows
    prefix.with_suffix(".process.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({k: v for k, v in result.items() if k != "monitor"}))
out = Path(c["output"]) / "result.json"
if out.exists():
    r = json.loads(out.read_text())
    print(
        json.dumps(
            {
                k: r.get(k)
                for k in [
                    "passed",
                    "error",
                    "packet_counts",
                    "empty_packets",
                    "whole_working_s",
                    "drain_s",
                ]
            }
        )
    )
    print("wall_hz", r.get("performance", {}).get("effective_wall_hz"))
else:
    print(prefix.with_suffix(".log").read_text()[-2000:])
