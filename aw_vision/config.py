import json
import os
from pathlib import Path

# Try to use tomllib (Python 3.11+), fallback to custom simple parser or json
try:
    import tomllib
except ImportError:
    tomllib = None

# Default settings
DEFAULT_CONFIG = {
    "watcher": {
        "screenshot_interval_seconds": 60,
        "screenshots_dir": "~/.local/share/aw-vision/screenshots",
    },
    "processing": {
        "cpu_threshold_percent": 30.0,
        "memory_threshold_percent": 80.0,
        "check_interval_seconds": 10,
        "max_screenshot_lifetime_days": 14,
        "cleanup_interval_hours": 1,
    },
    "ollama": {
        "host": "http://localhost:11434",
        "vision_model": "gemma4:e4b-it-qat",
        "ocr_model": "glm-ocr:q8_0",
        "embedding_model": "embeddinggemma",
    },
    "server": {"host": "127.0.0.1", "port": 5666, "cors_origins": ["*"]},
}


class Config:
    def __init__(self, config_path: str = "config.toml"):
        self.config_path = Path(config_path)
        self.settings = DEFAULT_CONFIG.copy()
        self.load()

    def _parse_toml_simple(self, text: str) -> dict:
        """A simple custom fallback parser for config.toml."""
        res = {}
        current_section = None
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip()
                res[current_section] = {}
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                # Try to convert types
                if v.lower() == "true":
                    v = True
                elif v.lower() == "false":
                    v = False
                elif v.startswith("[") and v.endswith("]"):
                    # list of strings
                    v = [item.strip().strip('"').strip("'") for item in v[1:-1].split(",") if item.strip()]
                else:
                    try:
                        v = float(v) if "." in v else int(v)
                    except ValueError:
                        pass

                if current_section:
                    res[current_section][k] = v
                else:
                    res[k] = v
        return res

    def load(self):
        if self.config_path.exists():
            try:
                with open(self.config_path, "rb") as f:
                    if tomllib:
                        user_settings = tomllib.load(f)
                    else:
                        text = f.read().decode("utf-8")
                        user_settings = self._parse_toml_simple(text)

                # Merge with defaults
                for section, keys in user_settings.items():
                    if isinstance(keys, dict) and section in self.settings:
                        self.settings[section].update(keys)
                    else:
                        self.settings[section] = keys
            except Exception as e:
                print(f"Error loading config.toml, using defaults: {e}")

    @property
    def screenshot_interval(self) -> int:
        return int(self.settings["watcher"]["screenshot_interval_seconds"])

    @property
    def screenshots_dir(self) -> Path:
        raw_path = self.settings["watcher"]["screenshots_dir"]
        expanded = os.path.expanduser(raw_path)
        p = Path(expanded)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_dir(self) -> Path:
        p = Path(os.path.expanduser("~/.local/share/aw-vision/db"))
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cpu_threshold(self) -> float:
        return float(self.settings["processing"]["cpu_threshold_percent"])

    @property
    def memory_threshold(self) -> float:
        return float(self.settings["processing"]["memory_threshold_percent"])

    @property
    def check_interval(self) -> int:
        return int(self.settings["processing"]["check_interval_seconds"])

    @property
    def max_screenshot_lifetime_days(self) -> int:
        return int(self.settings["processing"].get("max_screenshot_lifetime_days", 14))

    @property
    def cleanup_interval_hours(self) -> int:
        return int(self.settings["processing"].get("cleanup_interval_hours", 1))

    @property
    def ollama_host(self) -> str:
        return self.settings["ollama"]["host"]

    @property
    def vision_model(self) -> str:
        return self.settings["ollama"]["vision_model"]

    @property
    def ocr_model(self) -> str:
        return self.settings["ollama"].get("ocr_model", "glm-ocr:q8_0")

    @property
    def embedding_model(self) -> str:
        return self.settings["ollama"]["embedding_model"]

    @property
    def server_host(self) -> str:
        return self.settings["server"]["host"]

    @property
    def server_port(self) -> int:
        return int(self.settings["server"]["port"])

    @property
    def cors_origins(self) -> list:
        return self.settings["server"]["cors_origins"]

    @property
    def projects_file(self) -> Path:
        return Path(self.settings.get("projects_file", "projects.json"))

    def load_projects(self) -> list:
        p_file = self.projects_file
        if p_file.exists():
            try:
                with open(p_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading projects.json: {e}")
        return []

    def save_projects(self, projects: list):
        try:
            with open(self.projects_file, "w", encoding="utf-8") as f:
                json.dump(projects, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving projects.json: {e}")


config = Config()
