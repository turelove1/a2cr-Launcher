"""整合包实例的元数据管理。

每个实例是 ``instances/<名字>/`` 目录，里面除了游戏文件（mods、config、saves 等）
还有一个 ``instance.json`` 记录它用的是哪个 Minecraft 版本、哪个加载器。
"""

import json
import re
from datetime import datetime
from pathlib import Path

from a2cr_launcher.core.paths import INSTANCES_DIR

META_FILE = "instance.json"


def sanitize_name(name: str) -> str:
    """把整合包名字变成可以当文件夹名的形式。"""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().strip(".")
    return cleaned[:64] or "instance"


def instance_dir(name: str) -> Path:
    return Path(INSTANCES_DIR, name)


def _new_instance_dir(name: str) -> tuple[str, Path]:
    """重名时自动加后缀，避免覆盖已经导入的整合包。"""
    folder = sanitize_name(name)
    candidate = folder
    index = 2
    while instance_dir(candidate).is_dir() and any(instance_dir(candidate).iterdir()):
        candidate = f"{folder}-{index}"
        index += 1
    return candidate, instance_dir(candidate)


def create(name: str, mc_version: str, version_id: str, loader: dict | None = None,
           source: dict | None = None) -> dict:
    """
    创建一个实例并写入 instance.json。

    Args:
        name: 显示名字，同时用来生成目录名（重名会自动加后缀）
        mc_version: 基础 Minecraft 版本
        version_id: 启动时使用的版本 id（可能是加载器版本，如 fabric-loader-0.16.9-1.21.1）
        loader: {"type": "fabric", "version": "0.16.9"} 之类的加载器信息
        source: 整合包来源信息

    Returns:
        dict: 实例元数据（含实际目录名）
    """
    folder, directory = _new_instance_dir(name)
    directory.mkdir(parents=True, exist_ok=True)

    meta = {
        "name": name,
        "folder": folder,
        "mc_version": mc_version,
        "version_id": version_id,
        "loader": loader or {"type": "vanilla", "version": ""},
        "source": source or {},
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(Path(directory, META_FILE), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def load(name: str) -> dict | None:
    """按名字或目录读取实例元数据，不存在返回 None。"""
    directory = instance_dir(name)
    meta_path = Path(directory, META_FILE)
    try:
        # utf-8-sig：兼容用记事本改过、带 BOM 的 instance.json
        with open(meta_path, "r", encoding="utf-8-sig") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    meta.setdefault("folder", name)
    return meta


def list_all() -> list[dict]:
    """列出所有实例（按名字排序）。"""
    result = []
    try:
        folders = sorted(Path(INSTANCES_DIR).iterdir())
    except OSError:
        return result
    for folder in folders:
        if not folder.is_dir():
            continue
        meta = load(folder.name)
        if meta is not None:
            result.append(meta)
    return result


def find_by_source(file: str) -> dict | None:
    """按整合包文件路径找已经导入过的实例，用于失败后重跑/更新同一个实例。"""
    try:
        wanted = Path(file).resolve()
    except OSError:
        return None
    for meta in list_all():
        source_file = (meta.get("source") or {}).get("file")
        if not source_file:
            continue
        try:
            if Path(source_file).resolve() == wanted:
                return meta
        except OSError:
            continue
    return None


def save(meta: dict) -> None:
    """把实例元数据写回 instance.json。"""
    directory = instance_dir(meta["folder"])
    directory.mkdir(parents=True, exist_ok=True)
    with open(Path(directory, META_FILE), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

