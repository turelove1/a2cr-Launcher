"""CurseForge 整合包（manifest.json + overrides）解析。

CurseForge 清单里只有 projectID / fileID，需要额外解析出文件名和下载地址。
解析顺序：
  1. MCIM 的 CurseForge 镜像接口（带 downloadUrl 和 sha1）
  2. MCIM 查不到时，用 r.jina.ai 读取 CurseForge 文件页（能绕过官网的 Cloudflare 403），
     拿到 File name 后再拼 ForgeCDN 地址
  3. 都失败的文件会被跳过并报告，不影响其余文件导入
"""

import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import requests

from a2cr_launcher.core.download import get_session

FILE_API = "https://mod.mcimirror.top/curseforge/v1/mods/{project}/files/{file_id}"
PROJECT_API = "https://mod.mcimirror.top/curseforge/v1/mods/{project}"
CDN_URL = "https://mediafilez.forgecdn.net/files/{major}/{minor}/{name}"

LOADER_PREFIXES = {"forge": "forge", "neoforge": "neoforge", "fabric": "fabric", "quilt": "quilt"}

_PROJECT_PAGES: dict[int, str] = {}


class CurseForgeUnavailable(RuntimeError):
    """某个 CurseForge 文件既没有镜像也没有官网页面，无法解析。"""


def is_curseforge(archive: Path) -> bool:
    try:
        with zipfile.ZipFile(archive) as z:
            if "manifest.json" not in z.namelist():
                return False
            data = json.loads(z.read("manifest.json"))
    except (zipfile.BadZipFile, json.JSONDecodeError, OSError):
        return False
    return isinstance(data, dict) and "minecraft" in data and "files" in data


def _cdn_url(file_id: int, filename: str) -> str:
    return CDN_URL.format(major=file_id // 1000, minor=file_id % 1000, name=quote(filename))


def _get_json(url: str):
    """单次请求，失败返回 None；解析阶段不重试，避免一个坏文件卡很久。"""
    try:
        response = get_session().get(url, timeout=30)
        if response.status_code != 200:
            return None
        return response.json()
    except (requests.RequestException, ValueError):
        return None


def _get_text(url: str):
    try:
        response = get_session().get(url, timeout=60)
        if response.status_code != 200:
            return None
        return response.text
    except requests.RequestException:
        return None


def _project_page(project_id: int) -> str | None:
    """取项目官网地址（带分类，比如 /mc-mods/ 或 /texture-packs/），用于拼文件页 URL。"""
    if project_id in _PROJECT_PAGES:
        return _PROJECT_PAGES[project_id]

    data = (_get_json(PROJECT_API.format(project=project_id)) or {}).get("data") or {}
    page = (data.get("links") or {}).get("websiteUrl") or ""
    if not page and data.get("slug"):
        page = f"https://www.curseforge.com/minecraft/mc-mods/{data['slug']}"
    page = page.rstrip("/")
    if page:
        _PROJECT_PAGES[project_id] = page
        return page
    return None


def _destination(page: str, filename: str) -> str:
    """资源包放 resourcepacks/，其它（mod、world 等）放 mods/。"""
    if "/texture-packs/" in page:
        return f"resourcepacks/{filename}"
    return f"mods/{filename}"


def _entry_from_data(file_id: int, data: dict) -> dict | None:
    filename = data.get("fileName") or ""
    if not filename:
        return None
    sha1 = ""
    for digest in data.get("hashes") or []:
        if digest.get("algo") == 1:
            sha1 = digest.get("value", "")
            break
    return {
        "path": f"mods/{filename}",
        "url": data.get("downloadUrl") or _cdn_url(file_id, filename),
        "sha1": sha1,
        "size": data.get("fileLength") or 0,
    }


def _resolve_via_jina(project_id: int, file_id: int) -> dict | None:
    """MCIM 没有收录的文件（比如作者删掉了旧版本），用 r.jina.ai 读 CurseForge 文件页。"""
    page = _project_page(project_id)
    if not page:
        return None

    text = _get_text(f"https://r.jina.ai/{page}/files/{file_id}")
    if not text:
        return None

    match = re.search(r"File name[ \t]+(.+?)\s*$", text, re.MULTILINE)
    if not match:
        return None
    filename = match.group(1).strip()

    # 官网只显示一位小数的 MB，不够准；size 留 0，让下载器按实际大小处理
    url = _cdn_url(file_id, filename)
    head = get_session().head(url, timeout=30, allow_redirects=True)
    if head.status_code != 200:
        return None
    return {"path": _destination(page, filename), "url": url, "sha1": "", "size": 0}


def resolve_file(project_id: int, file_id: int) -> dict:
    """解析一个 CurseForge 文件的文件名 / 下载地址 / sha1 / 大小。"""
    data = _get_json(FILE_API.format(project=project_id, file_id=file_id)) or {}
    entry = _entry_from_data(file_id, data.get("data") or {})
    if entry:
        # 资源包是 .zip，要放进 resourcepacks/ 而不是 mods/
        if entry["path"].endswith(".zip"):
            page = _project_page(project_id)
            if page:
                entry["path"] = _destination(page, Path(entry["path"]).name)
        return entry

    entry = _resolve_via_jina(project_id, file_id)
    if entry:
        return entry

    raise CurseForgeUnavailable(f"project {project_id} / file {file_id} 在镜像和官网都查不到")


def resolve_files(files: list[dict], on_progress=None, on_error=None) -> tuple[list[dict], list[dict]]:
    """
    并行解析清单里的所有文件，保持顺序。

    Returns:
        (解析成功的文件列表, 解析失败的文件列表)
    """
    resolved: list[dict] = []
    failed: list[dict] = []
    total = len(files)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(resolve_file, item["project"], item["file_id"]) for item in files]
        for index, future in enumerate(futures, start=1):
            try:
                resolved.append(future.result())
            except Exception as exc:
                failed.append({**files[index - 1], "error": str(exc)})
                if on_error:
                    on_error(files[index - 1], exc)
            if on_progress:
                on_progress(index, total)
    return resolved, failed


def read(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("manifest.json"))
        names = z.namelist()

    minecraft = manifest.get("minecraft") or {}
    mc_version = minecraft.get("version")
    if not mc_version:
        raise ValueError("不是有效的 CurseForge 整合包：manifest.minecraft 里没有 version")

    loader_type, loader_version = "vanilla", ""
    loaders = minecraft.get("modLoaders") or []
    if loaders:
        raw = str(loaders[0].get("id", ""))
        for prefix, kind in LOADER_PREFIXES.items():
            if raw.startswith(prefix + "-"):
                loader_type, loader_version = kind, raw[len(prefix) + 1:]
                break

    # 新版清单把名字放在 manifest 子对象里，老版清单直接放在顶层
    info = manifest.get("manifest") or manifest
    overrides = str(manifest.get("overrides") or "overrides").strip("/")
    overrides = [overrides] if any(entry.startswith(overrides + "/") for entry in names) else []

    files = [{"project": item["projectID"], "file_id": item["fileID"]}
             for item in manifest.get("files") or [] if item.get("required", True)]

    return {
        "format": "curseforge",
        "name": info.get("name") or Path(archive).stem,
        "pack_version": str(info.get("version") or ""),
        "mc_version": mc_version,
        "loader": loader_type,
        "loader_version": loader_version,
        "files": files,
        "overrides": overrides,
        "archive": Path(archive),
    }
