import json
from pathlib import Path

import requests

from a2cr_launcher.core.http_util import http_get
from a2cr_launcher.core.paths import VERSIONS_DIR

# Minecraft 版本列表
MOJANG_VERSION_LIST_URL = 'https://piston-meta.mojang.com/mc/game/version_manifest_v2.json'


def _cache_path() -> Path:
    return Path(VERSIONS_DIR, MOJANG_VERSION_LIST_URL.strip().split("/")[-1])


def _read_cache(path: Path) -> dict:
    """读取本地的版本列表缓存，文件不存在/损坏时当作没有缓存。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(path: Path, data: dict) -> None:
    """原子地写缓存，失败也不影响本次使用（比如目录只读）。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        temp.replace(path)
    except OSError:
        pass


def get_version_manifest(version_type: str, limit=0):
    # 首先从本地的文件读取，远程不可用时作为备选
    local_data_path = _cache_path()
    local_data = _read_cache(local_data_path)

    try:
        remote_data = http_get(MOJANG_VERSION_LIST_URL).json()
    except (requests.RequestException, ValueError):
        remote_data = None

    if isinstance(remote_data, dict):
        # 根据本地和远程的最新版本来判断缓存的时效性
        if local_data.get("latest") != remote_data.get("latest"):
            _write_cache(local_data_path, remote_data)
        data = remote_data.get("versions")
    elif local_data.get("versions"):
        # 网络不可用，退回到本地缓存
        data = local_data.get("versions")
    else:
        raise requests.RequestException("无法获取 Minecraft 版本列表：网络不可用，本地也没有缓存")

    # 列版本列表
    versions_list = []
    if isinstance(data, list):
        for version in data:
            if version_type == "all" or version.get('type') == version_type:
                versions_list.append(version)
        if limit:
            return versions_list[:limit]

    return versions_list


def find_version(version_id: str):
    version_list = get_version_manifest("all", 0)
    for version in version_list:
        if version.get('id') == version_id:
            return version
    raise ValueError(f"找不到版本 {version_id}，可以用 `al version --limit 50` 查看可用版本")
