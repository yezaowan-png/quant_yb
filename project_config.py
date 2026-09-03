"""Project-wide configuration loading with a single path policy."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_ENV_VAR = "QUANTYB_CONFIG"


def resolve_config_path(path: str | Path | None = None) -> Path:
    """Resolve an explicit, environment, or project-default config path."""
    raw_path = path if path is not None else os.environ.get(CONFIG_ENV_VAR)
    if raw_path is None or not str(raw_path).strip():
        return PROJECT_ROOT / "config.yaml"
    candidate = Path(raw_path).expanduser()
    return candidate if candidate.is_absolute() else Path.cwd() / candidate


def load_project_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load a YAML mapping and fail early with a useful configuration error."""
    config_path = resolve_config_path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    try:
        value = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"配置文件 YAML 无法解析: {config_path}: {exc}") from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"配置文件顶层必须是映射: {config_path}")
    return value
