"""PC Sense MCP 配置模块。

从 config.json 读取配置，并提供合理的默认值。
不包含任何密钥（API Key 存放在 .secrets/API_KEY.txt，绝不进 config.json）。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"

DEFAULTS: Dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 8765,
    "focus_poll_interval": 1.0,
    "active_threshold_seconds": 60,
    "away_threshold_seconds": 300,
    "history_retention_days": 30,
    "max_open_windows": 100,
    "open_apps_limit": 15,
    "exclude_processes": [],
    "allowed_origins": [],
}

class Config:
    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = {**DEFAULTS, **(data or {})}

    def get(self, key: str) -> Any:
        return self._data.get(key, DEFAULTS.get(key))

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    @property
    def host(self) -> str:
        return str(self.get("host"))

    @property
    def port(self) -> int:
        return int(self.get("port"))

    @property
    def focus_poll_interval(self) -> float:
        return float(self.get("focus_poll_interval"))

    @property
    def active_threshold_seconds(self) -> int:
        return int(self.get("active_threshold_seconds"))

    @property
    def away_threshold_seconds(self) -> int:
        return int(self.get("away_threshold_seconds"))

    @property
    def history_retention_days(self) -> int:
        return int(self.get("history_retention_days"))

    @property
    def max_open_windows(self) -> int:
        return int(self.get("max_open_windows"))
    @property
    def open_apps_limit(self) -> int:
        return int(self.get("open_apps_limit"))
    @property
    def exclude_processes(self) -> list:
        return list(self.get("exclude_processes") or [])

    @property
    def allowed_origins(self) -> list:
        return list(self.get("allowed_origins") or [])
    def is_excluded_process(self, name: str) -> bool:
        if not name:
            return False
        return name.lower() in {p.lower() for p in self.exclude_processes}

    @property
    def api_key_path(self) -> Path:
        return PROJECT_ROOT / ".secrets" / "API_KEY.txt"

    @property
    def db_path(self) -> Path:
        return PROJECT_ROOT / "data" / "pc_sense.db"

    @property
    def log_path(self) -> Path:
        return PROJECT_ROOT / "logs" / "pc-sense.log"

    @property
    def secrets_dir(self) -> Path:
        return PROJECT_ROOT / ".secrets"

    @property
    def data_dir(self) -> Path:
        return PROJECT_ROOT / "data"

    @property
    def logs_dir(self) -> Path:
        return PROJECT_ROOT / "logs"


def load_config(path: Path | None = None) -> Config:
    """加载 config.json。文件缺失或损坏时回退到默认配置（并记日志）。"""
    cfg_path = path or DEFAULT_CONFIG_PATH
    data: Dict[str, Any] = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("config.json 解析失败，使用默认配置: %s", cfg_path)
            data = {}
    else:
        logger.info("config.json 不存在，使用默认配置: %s", cfg_path)
    return Config(data)


def api_key_from_env_or_file(cfg: Config) -> str | None:
    """优先从环境变量 API_KEY 读取；否则从 .secrets/API_KEY.txt 读取。

    返回 None 表示未配置。
    """
    key = os.environ.get("PC_SENSE_API_KEY") or os.environ.get("API_KEY")
    if key:
        return key.strip()
    path = cfg.api_key_path
    if path.exists():
        content = path.read_text(encoding="utf-8").strip()
        if content:
            return content
    return None