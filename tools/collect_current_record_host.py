"""Rare before/after host sample for the current RECORD performance experiment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import time


def sample() -> dict:
    frequencies = []
    governors = set()
    for cpu in sorted(Path("/sys/devices/system/cpu").glob("cpu[0-9]*")):
        frequency = cpu / "cpufreq/scaling_cur_freq"
        governor = cpu / "cpufreq/scaling_governor"
        if frequency.is_file():
            frequencies.append(int(frequency.read_text()) / 1000.0)
        if governor.is_file():
            governors.add(governor.read_text().strip())
    temperatures = {}
    for zone in Path("/sys/class/thermal").glob("thermal_zone[0-9]*"):
        label, value = zone / "type", zone / "temp"
        if label.is_file() and value.is_file():
            try:
                temperatures[label.read_text().strip()] = int(value.read_text()) / 1000.0
            except ValueError:
                pass
    gpu_command = [
        "nvidia-smi", "--query-gpu=name,driver_version,memory.used,memory.total,"
        "utilization.gpu,temperature.gpu,clocks.current.graphics,clocks.current.memory",
        "--format=csv,noheader,nounits",
    ]
    gpu = subprocess.run(gpu_command, text=True, capture_output=True, check=False)
    disk = os.statvfs("/data")
    return {
        "wall_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": platform.node(), "kernel": platform.release(),
        "cpu_model": next(
            (line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
             if line.startswith("model name")), None
        ),
        "cpu_governors": sorted(governors),
        "cpu_frequency_mhz": {
            "min": min(frequencies) if frequencies else None,
            "max": max(frequencies) if frequencies else None,
            "mean": sum(frequencies) / len(frequencies) if frequencies else None,
        },
        "cpu_temperatures_c": temperatures,
        "load_average": os.getloadavg(),
        "proc_stat_cpu": Path("/proc/stat").read_text().splitlines()[0],
        "gpu_query_command": gpu_command,
        "gpu_query_exit": gpu.returncode,
        "gpu_csv": gpu.stdout.strip() if gpu.returncode == 0 else None,
        "gpu_error": gpu.stderr.strip() if gpu.returncode else None,
        "data_disk_free_bytes": disk.f_bavail * disk.f_frsize,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(sample(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
