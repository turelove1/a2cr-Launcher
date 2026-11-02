import json
from pathlib import Path

from a2cr_launcher.core.http_util import http_get
from a2cr_launcher.core.paths import VERSIONS_DIR
from a2cr_launcher.meta.manifest import find_version


def _meta_path(version_id: str) -> Path:
    return Path(VERSIONS_DIR, version_id, f"{version_id}.json")


def _read_local(version_id: str) -> dict | None:
    """读取安装时存下来的版本 meta，网络不可用时启动就靠它。"""
    try:
        with open(_meta_path(version_id), "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) and data.get("id") == version_id else None


def _write_local(version_id: str, meta: dict) -> None:
    try:
        path = _meta_path(version_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(meta, f)
        temp.replace(path)
    except OSError:
        pass


def get_version_meta(version_id: str, refresh: bool = False) -> dict:
    """
    获取版本 meta。

    Args:
        version_id (str): 版本号
        refresh (bool): 是否强制从网络重新获取（安装时用，保证拿到最新的文件列表）

    Returns:
        dict: 版本的 meta
    """
    if not refresh:
        local = _read_local(version_id)
        if local is not None:
            return local

    version_meta_url = find_version(version_id).get("url")
    meta = http_get(version_meta_url).json()
    if isinstance(meta, dict):
        _write_local(version_id, meta)
    return meta
