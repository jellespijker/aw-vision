"""System resource monitoring: CPU/memory/GPU idle checks for CPU-aware processing."""
import os
import time
from datetime import datetime

import psutil

from aw_vision.config import config


class MonitorMixin:
    def get_nvidia_gpus_usage(self) -> list[dict]:
        """Query nvidia-smi to get GPU utilization and process list."""
        import shutil
        import subprocess

        if not shutil.which("nvidia-smi"):
            return []

        try:
            # Query GPU index and utilization
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=index,utilization.gpu", "--format=csv,noheader,nounits"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=1.5
            )
            if res.returncode != 0:
                return []

            gpus = []
            for line in res.stdout.strip().split("\n"):
                if line:
                    parts = line.split(",")
                    if len(parts) == 2:
                        idx = int(parts[0].strip())
                        util = float(parts[1].strip())
                        gpus.append({"index": idx, "utilization": util, "ollama_running": False})

            # Check if any ollama processes are running on the GPU
            res_proc = subprocess.run(
                ["nvidia-smi", "--query-compute-apps=gpu_index,pid,process_name", "--format=csv,noheader"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=1.5
            )
            if res_proc.returncode == 0:
                for line in res_proc.stdout.strip().split("\n"):
                    if line:
                        parts = line.split(",")
                        if len(parts) >= 3:
                            gpu_idx_str = parts[0].strip()
                            proc_name = parts[2].strip().lower()
                            if "ollama" in proc_name or "llama-server" in proc_name or "llama" in proc_name:
                                try:
                                    gpu_idx = int(gpu_idx_str)
                                    for gpu in gpus:
                                        if gpu["index"] == gpu_idx:
                                            gpu["ollama_running"] = True
                                except ValueError:
                                    pass

            return gpus
        except Exception as e:
            print(f"Error querying nvidia-smi for GPU utilization: {e}")
            return []

    def is_system_idle(self) -> bool:
        """Check if CPU, Memory, and optionally GPU usage are below idle thresholds."""
        cpu_usage = psutil.cpu_percent(interval=0.5)
        mem_usage = psutil.virtual_memory().percent

        idle = cpu_usage < config.cpu_threshold and mem_usage < config.memory_threshold
        status_msg = f"[{datetime.now()}] System resources check - CPU: {cpu_usage}% (limit {config.cpu_threshold}%), Memory: {mem_usage}% (limit {config.memory_threshold}%)"

        # Check GPU usage if nvidia-smi is available
        gpus = self.get_nvidia_gpus_usage()
        gpu_active_limit_exceeded = False

        for gpu in gpus:
            idx = gpu["index"]
            util = gpu["utilization"]
            ollama_active = gpu["ollama_running"]
            status_msg += f", GPU[{idx}]: {util}%"
            if ollama_active:
                status_msg += " (Ollama running on GPU)"
                if util > config.gpu_threshold:
                    gpu_active_limit_exceeded = True
                    status_msg += f" [BUSY: >{config.gpu_threshold}%]"

        print(status_msg)
        if gpu_active_limit_exceeded:
            return False

        return idle
