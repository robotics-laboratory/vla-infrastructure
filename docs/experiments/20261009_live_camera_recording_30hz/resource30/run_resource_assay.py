"""Passive single-recorder resource assay; config contains explicit command argv.

No shell, environment dumps, SDK edits, GPU workloads or action modifications.
Only owned subprocess trees can be stopped on timeout/failure. CPU affinity/nice
are process-scoped argv prefixes. Parent supplies recording/background commands.
"""
import argparse
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import traceback

BASE_FIELDS = ["index", "uuid", "utilization.gpu", "memory.total", "memory.used",
               "memory.free", "power.draw", "power.limit", "temperature.gpu",
               "clocks.current.graphics", "clocks.current.sm", "clocks.current.memory"]
OPTIONAL_FIELDS = ["utilization.encoder", "utilization.decoder"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def proc_stat(path):
    raw = Path(path).read_text()
    end = raw.rfind(")")
    tail = raw[end + 2:].split()  # tail[0] is field3, state; comm may contain spaces.
    return dict(pid=int(raw.split("(", 1)[0]), comm=raw[raw.index("(")+1:end],
                state=tail[0], ppid=int(tail[1]), pgid=int(tail[2]), sid=int(tail[3]),
                utime_ticks=int(tail[11]), stime_ticks=int(tail[12]), nice=int(tail[16]),
                threads=int(tail[17]), start_ticks=int(tail[19]),
                vsize_bytes=int(tail[20]), rss_pages=int(tail[21]), stat_raw=raw.strip())


def system_sample(roots, owned):
    begin = time.monotonic_ns()
    cpu_raw = Path("/proc/stat").read_text()
    cpus = {line.split()[0]: [int(v) for v in line.split()[1:]]
            for line in cpu_raw.splitlines() if line.startswith("cpu")}
    mem_raw = Path("/proc/meminfo").read_text()
    memory = {line.split(":", 1)[0]: line.split(":", 1)[1].strip()
              for line in mem_raw.splitlines() if ":" in line}
    stats = {}
    for folder in Path("/proc").iterdir():
        if folder.name.isdigit():
            try:
                item = proc_stat(folder / "stat")
                stats[item["pid"]] = item
            except (OSError, ValueError, IndexError):
                pass  # Exited PID race; only owned-process detail failures are emitted below.
    groups = {}
    for name, pid in roots.items():
        selected = {pid}
        while name != "monitor":
            extra = {p for p, v in stats.items() if v["ppid"] in selected}
            if extra <= selected:
                break
            selected |= extra
        owned[name].update((p, stats[p]["start_ticks"]) for p in selected if p in stats)
        selected |= {p for p, start in owned[name] if p in stats and stats[p]["start_ticks"] == start}
        details = []
        for pid in sorted(selected):
            if pid not in stats:
                continue
            item = dict(stats[pid], observed_monotonic_ns=time.monotonic_ns())
            for key in ("status", "io"):
                try:
                    item[key + "_raw"] = Path(f"/proc/{pid}/{key}").read_text()
                except OSError as exc:
                    item[key + "_error"] = str(exc)
            details.append(item)
        groups[name] = details
    return dict(begin_monotonic_ns=begin, end_monotonic_ns=time.monotonic_ns(),
                cpu_ticks=cpus, meminfo=memory, proc_stat_raw=cpu_raw,
                meminfo_raw=mem_raw, processes=groups)


def command_spec(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("argv"), list) or not raw["argv"]:
        raise ValueError("Command spec requires nonempty argv list")
    if any(not isinstance(v, str) or "\0" in v for v in raw["argv"]):
        raise ValueError("argv must contain strings without NUL")
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in raw.get("env", {}).items()):
        raise ValueError("env must be explicit string overrides")
    affinity = raw.get("affinity")
    if affinity is not None and (not affinity or any(type(c) is not int or c < 0 for c in affinity)):
        raise ValueError("affinity requires nonnegative CPU IDs")
    nice = raw.get("nice", 0)
    if type(nice) is not int or not -20 <= nice <= 19:
        raise ValueError("nice outside-20..19")
    if raw.get("timeout_s", 240) <= 0:
        raise ValueError("timeout must be positive")
    return raw


def launch(spec, name, output):
    command = spec["argv"][:]
    if spec.get("affinity") is not None:
        command = ["taskset", "--cpu-list", ",".join(map(str, spec["affinity"])), *command]
    if spec.get("nice", 0):
        command = ["nice", "-n", str(spec["nice"]), *command]
    stdout = (output / (name + ".stdout")).open("xb")
    stderr = (output / (name + ".stderr")).open("xb")
    begin = time.monotonic_ns()
    try:
        proc = subprocess.Popen(command, cwd=spec.get("cwd"),
                                env=dict(os.environ, **spec.get("env", {})),
                                stdout=stdout, stderr=stderr, start_new_session=True)
    finally:
        stdout.close()
        stderr.close()
    return proc, dict(argv=command, requested_argv=spec["argv"], env_overrides=spec.get("env", {}),
                      cwd=spec.get("cwd"), affinity=spec.get("affinity"), nice=spec.get("nice", 0),
                      pid=proc.pid, launch_begin_monotonic_ns=begin,
                      launch_end_monotonic_ns=time.monotonic_ns(), timeout_s=spec.get("timeout_s", 240))


def query_gpu(fields, timeout):
    argv = ["nvidia-smi", "--query-gpu=" + ",".join(fields), "--format=csv,noheader,nounits"]
    begin = time.monotonic_ns()
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        row = dict(argv=argv, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr)
        if not result.returncode:
            row["devices"] = [dict(zip(fields, [x.strip() for x in v]))
                              for v in csv.reader(result.stdout.splitlines()) if len(v) == len(fields)]
    except (OSError, subprocess.TimeoutExpired) as exc:
        row = dict(argv=argv, exit_code=None, error=str(exc))
    return dict(begin_monotonic_ns=begin, end_monotonic_ns=time.monotonic_ns(), **row)


def matches(spec):
    """Passive readiness: exists-marker, or at least one matching complete JSON line."""
    path = Path(spec["path"])
    if not path.is_file():
        return False
    if not spec.get("match"):
        return True
    # Logs are bounded by the configured recording budget, not untrusted streams.
    for line in reversed(path.read_text().splitlines()):
        try:
            row = json.loads(line)
            if all(row.get(key) == value for key, value in spec["match"].items()):
                return True
        except json.JSONDecodeError:
            pass  # Concurrent partial final line; next sample retries.
    return False


def stop_owned(procs, owned, receipt):
    """Identity-check PID start ticks before signaling known descendants; no pkill."""
    if not procs:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for name, proc in procs.items():
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, sig)
                    receipt["cleanup"].append(dict(group=proc.pid, signal=int(sig)))
                except ProcessLookupError:
                    pass
            for pid, start in sorted(owned[name]):
                try:
                    if proc_stat(f"/proc/{pid}/stat")["start_ticks"] == start:
                        os.kill(pid, sig)
                        receipt["cleanup"].append(dict(pid=pid, signal=int(sig), start_ticks=start))
                except (ProcessLookupError, FileNotFoundError):
                    pass
        if sig == signal.SIGTERM:
            time.sleep(1)
    for proc in procs.values():
        proc.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--background-command-file", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    receipt = dict(schema="single_recording_resource_assay_v1", passed=False,
                   source_sha256=sha(__file__), commands={}, cleanup=[], events=[])
    procs, roots = {}, {"monitor":os.getpid()}
    owned = {"monitor":set(), "recorder":set(), "background":set()}
    lock = None
    try:
        config = json.loads(args.config.read_text())
        command_spec(config)
        background = command_spec(json.loads(args.background_command_file.read_text())) if args.background_command_file else None
        copied = {}
        for label, path in [("helper", Path(__file__)), ("config", args.config), *([("background-config", args.background_command_file)] if background else [])]:
            dest = args.output / (label + "-" + path.name)
            dest.write_bytes(path.read_bytes())
            copied[str(path)] = dest.name
        receipt = dict(schema="single_recording_resource_assay_v1", passed=False, physical=False,
                       quest_connected=False, dataset_admissible=False,
                       interval_s=config.get("interval_s", .5), config=str(args.config),
                       source_sha256=sha(__file__), inputs_sha256={str(args.config):sha(args.config)},
                       commands={}, cleanup=[], events=[], copied_inputs=copied)
        for label, spec in [("recorder", config), *([("background", background)] if background else [])]:
            pinned = []
            for ordinal, value in enumerate(spec.get("source_paths", [])):
                path = Path(value)
                dest = args.output / f"{label}-source-{ordinal:03d}-{path.name}"
                dest.write_bytes(path.read_bytes())
                pinned.append(dict(path=str(path), retained=dest.name, sha256=sha(path)))
            receipt.setdefault("command_sources", {})[label] = pinned
        receipt["clock_info"] = {name:vars(time.get_clock_info(name)) for name in ("monotonic", "perf_counter", "time")}
        if background:
            receipt["inputs_sha256"][str(args.background_command_file)] = sha(args.background_command_file)
        interval = receipt["interval_s"]
        if interval <= 0:
            raise ValueError("interval must be positive")
        lock_path = Path(config.get("lock_file", str(args.output.parent / ".recording-assay.lock")))
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = lock_path.open("a")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fields = BASE_FIELDS + OPTIONAL_FIELDS
        timeout = config.get("gpu_query_timeout_s", 1)
        preflight = system_sample(roots, owned)
        receipt["clock_ticks_per_s"] = os.sysconf("SC_CLK_TCK")
        receipt["page_size_bytes"] = os.sysconf("SC_PAGE_SIZE")
        receipt["monitor_affinity"] = sorted(os.sched_getaffinity(0))
        topology = {}
        for folder in Path("/sys/devices/system/cpu").glob("cpu[0-9]*"):
            topology[folder.name] = {}
            for field in ("core_id", "physical_package_id", "thread_siblings_list"):
                try:
                    topology[folder.name][field] = (folder / "topology" / field).read_text().strip()
                except OSError as exc:
                    topology[folder.name][field] = dict(error=str(exc))
        receipt["cpu_topology"] = topology
        attempts = []
        if config.get("query_gpu", True):
            attempts.append(query_gpu(fields, timeout))
            if attempts[-1].get("exit_code") != 0:
                fields = BASE_FIELDS[:]
                attempts.append(query_gpu(fields, timeout))
                if attempts[-1].get("exit_code") == 0:
                    for optional in OPTIONAL_FIELDS:
                        attempts.append(query_gpu(["index", optional], timeout))
                        if attempts[-1].get("exit_code") == 0:
                            fields.append(optional)
                    attempts.append(query_gpu(fields, timeout))
            receipt["gpu_query_available"] = attempts[-1].get("exit_code") == 0
        else:
            fields = []
            receipt["gpu_query_available"] = False
        compute_apps = None
        if config.get("query_gpu", True):
            argv = ["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory", "--format=csv,noheader,nounits"]
            begin = time.monotonic_ns()
            try:
                proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
                compute_apps = dict(argv=argv, exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
            except (OSError, subprocess.TimeoutExpired) as exc:
                compute_apps = dict(argv=argv, error=str(exc), exit_code=None)
            compute_apps.update(begin_monotonic_ns=begin, end_monotonic_ns=time.monotonic_ns())
        save(args.output / "preflight.json", dict(system=preflight, gpu_attempts=attempts, compute_apps=compute_apps))
        receipt["gpu_fields"] = fields
        receipt["telemetry_complete"] = not config.get("query_gpu", True) or receipt["gpu_query_available"]
        if args.preflight_only:
            receipt["passed"] = True
            return
        procs["recorder"], receipt["commands"]["recorder"] = launch(config, "recorder", args.output)
        roots["recorder"] = procs["recorder"].pid
        epoch = time.monotonic_ns()
        sample = 0
        triggered, ready = False, False
        with (args.output / "samples.jsonl").open("x") as stream:
            while True:
                now = time.monotonic_ns()
                if background and not triggered:
                    trigger = config.get("background_trigger")
                    if trigger is None or matches(trigger):
                        procs["background"], receipt["commands"]["background"] = launch(background, "background", args.output)
                        roots["background"] = procs["background"].pid
                        triggered = True
                        receipt["events"].append(dict(event="background_triggered", monotonic_ns=time.monotonic_ns(), trigger=trigger))
                    elif now - epoch > trigger.get("timeout_s", 120) * 1e9:
                        raise TimeoutError("Background readiness trigger timeout")
                if triggered and not ready:
                    condition = background.get("ready")
                    age = (now - receipt["commands"]["background"]["launch_begin_monotonic_ns"]) / 1e9
                    ready = matches(condition) if condition else age >= background.get("min_alive_s", .5)
                    if ready:
                        receipt["events"].append(dict(event="background_ready", monotonic_ns=time.monotonic_ns(), evidence=condition or {"alive_seconds":age, "semantics":"alive proxy, not meaningful CPU work"}))
                    elif age > (condition or {}).get("timeout_s", 30):
                        raise TimeoutError("Background ready-marker timeout")
                row = system_sample(roots, owned)
                row.update(sample_index=sample, scheduled_monotonic_ns=epoch+int(sample*interval*1e9),
                           monitor_unix_ns=time.time_ns(), processes_exit_codes={name:p.poll() for name,p in procs.items()})
                if fields:
                    row["gpu"] = query_gpu(fields, timeout)
                row["capture_end_monotonic_ns"] = time.monotonic_ns()
                stream.write(json.dumps(row) + "\n")
                stream.flush()
                sample += 1
                for name, proc in procs.items():
                    meta = receipt["commands"][name]
                    code = proc.poll()
                    if code is not None and "exit_code" not in meta:
                        meta.update(exit_code=code, exit_observed_monotonic_ns=time.monotonic_ns())
                    if code is not None and code != 0:
                        raise RuntimeError(name + " process failed with exit" + str(code))
                    if code is None and time.monotonic_ns()-meta["launch_begin_monotonic_ns"] > meta["timeout_s"]*1e9:
                        raise TimeoutError(name + " process timeout")
                if procs["recorder"].poll() is not None and background and not triggered:
                    raise RuntimeError("Recorder ended before background trigger")
                if all(p.poll() is not None for p in procs.values()):
                    if background and not ready:
                        raise RuntimeError("Background exited before readiness")
                    break
                deadline = epoch + int(sample * interval * 1e9)
                time.sleep(max(0, (deadline-time.monotonic_ns())/1e9))
        receipt["passed"] = True
    except BaseException:
        receipt["error"] = traceback.format_exc()
        stop_owned(procs, owned, receipt)
        raise
    finally:
        for name, proc in procs.items():
            receipt["commands"][name].setdefault("exit_code", proc.poll())
        receipt["finished_monotonic_ns"] = time.monotonic_ns()
        receipt["source_bytes_unchanged"] = sha(__file__) == receipt["source_sha256"]
        save(args.output / "receipt.json", receipt)
        if lock is not None:
            lock.close()


if __name__ == "__main__":
    main()
