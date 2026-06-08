from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT_PATH = Path(__file__).resolve().parents[2]
"""Maa 项目根目录。"""

RESOURCES_PATH = ROOT_PATH / "resources"
"""只保存规划需要的数据资源，不再承载旧 GUI 资源。"""


def read_json(path: str | Path, default: Any = None) -> Any:
    """读取 UTF-8 JSON，缺失或格式错误时返回默认值。"""
    if default is None:
        default = {}
    try:
        with Path(path).open("r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

