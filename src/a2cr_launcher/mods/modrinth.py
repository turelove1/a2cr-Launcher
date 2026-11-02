"""Modrinth API 客户端（搜索 / 项目 / 版本）。"""

import json
from typing import Any

from a2cr_launcher.core.http_util import http_get

API = "https://api.modrinth.com/v2"


def _get(path: str, **params) -> Any:
    response = http_get(API + path, params=params)
    return response.json()


def search(query: str, mc_version: str | None = None, loader: str | None = None, limit: int = 10) -> list[dict]:
    """搜索模组，可按 Minecraft 版本和加载器过滤。"""
    facets = [["project_type:mod"]]
    if mc_version:
        facets.append([f"versions:{mc_version}"])
    if loader:
        facets.append([f"categories:{loader}"])

    data = _get("/search", query=query, limit=limit, index="relevance", facets=json.dumps(facets))
    return data.get("hits") or []


def project(slug_or_id: str) -> dict:
    return _get(f"/project/{slug_or_id}")


def versions(slug_or_id: str, mc_version: str | None = None, loader: str | None = None) -> list[dict]:
    params = {}
    if mc_version:
        params["game_versions"] = json.dumps([mc_version])
    if loader:
        params["loaders"] = json.dumps([loader])
    return _get(f"/project/{slug_or_id}/version", **params) or []


def version(version_id: str) -> dict:
    return _get(f"/version/{version_id}")


def primary_file(version_data: dict) -> dict | None:
    files = version_data.get("files") or []
    for item in files:
        if item.get("primary"):
            return item
    return files[0] if files else None
