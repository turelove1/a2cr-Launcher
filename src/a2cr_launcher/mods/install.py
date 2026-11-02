"""把 Modrinth 上的模组下载到指定整合包实例。"""

import json
from pathlib import Path

import requests

from a2cr_launcher import instance
from a2cr_launcher.core.download import download
from a2cr_launcher.mods import modrinth

MANIFEST_NAME = ".a2cr-mods.json"


def _manifest_path(directory: Path) -> Path:
    return Path(directory, "mods", MANIFEST_NAME)


def _load_manifest(directory: Path) -> dict:
    try:
        with open(_manifest_path(directory), "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_manifest(directory: Path, data: dict) -> None:
    try:
        path = _manifest_path(directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp.replace(path)
    except OSError:
        pass


def instance_context(name: str) -> tuple[dict, str, str, Path]:
    """返回 (实例元数据, Minecraft 版本, 加载器, 实例目录)。"""
    meta = instance.load(name)
    if meta is None:
        raise ValueError(f"找不到实例 {name}，可以先用 `al instance list` 看看")
    loader = (meta.get("loader") or {}).get("type") or "vanilla"
    if loader == "vanilla":
        raise ValueError("这个实例是原版，装模组没有意义；请用 Forge / Fabric / NeoForge 实例")
    return meta, meta["mc_version"], loader, instance.instance_dir(meta["folder"])


def pick_version(version_list: list[dict], mc_version: str, loader: str) -> dict | None:
    compatible = [version_data for version_data in version_list
                  if mc_version in (version_data.get("game_versions") or [])
                  and loader in (version_data.get("loaders") or [])]
    if not compatible:
        return None
    # 有正式版就优先正式版，避免默认装上 beta/alpha
    for version_data in compatible:
        if version_data.get("version_type") == "release":
            return version_data
    return compatible[0]


def resolve_main(slug: str, mc_version: str, loader: str, version_id: str | None = None) -> dict:
    if version_id:
        return modrinth.version(version_id)

    try:
        version_list = modrinth.versions(slug, mc_version, loader)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            raise ValueError(f"Modrinth 上找不到模组 {slug}") from exc
        raise

    version_data = pick_version(version_list, mc_version, loader)
    if version_data is None:
        raise ValueError(f"{slug} 没有适配 Minecraft {mc_version} / {loader} 的版本")
    return version_data


def _collect_required(version_data: dict, mc_version: str, loader: str, seen: set[str],
                      result: list[dict], log) -> None:
    for dependency in version_data.get("dependencies") or []:
        if dependency.get("dependency_type") != "required":
            continue

        project_id = dependency.get("project_id")
        if not project_id or project_id in seen:
            continue
        seen.add(project_id)

        try:
            if dependency.get("version_id"):
                dependency_version = modrinth.version(dependency["version_id"])
            else:
                dependency_version = pick_version(
                    modrinth.versions(project_id, mc_version, loader), mc_version, loader)
        except Exception as exc:  # 单个依赖解析失败不应该让整个安装失败
            log(f"  跳过依赖 {project_id}：{exc}")
            continue

        if dependency_version is None:
            log(f"  依赖 {project_id} 没有适配 {mc_version} / {loader} 的版本，已跳过")
            continue

        result.append(dependency_version)
        _collect_required(dependency_version, mc_version, loader, seen, result, log)


def install(slug: str, instance_name: str, version_id: str | None = None,
            with_deps: bool = True, log=print) -> list[str]:
    """
    安装模组到实例。

    Returns:
        list[str]: 实际下载的文件名
    """
    meta, mc_version, loader, directory = instance_context(instance_name)

    log(f"实例：{meta.get('name')}（Minecraft {mc_version} / {loader}）")
    main_version = resolve_main(slug, mc_version, loader, version_id)

    seen: set[str] = {main_version.get("project_id")} if main_version.get("project_id") else set()
    versions_to_install = [main_version]
    if with_deps:
        _collect_required(main_version, mc_version, loader, seen, versions_to_install, log)

    mods_dir = Path(directory, "mods")
    mods_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(directory)

    targets = []
    filenames = []
    old_files: list[Path] = []
    for version_data in versions_to_install:
        file_info = modrinth.primary_file(version_data)
        if not file_info:
            log(f"  {version_data.get('name') or version_data.get('id')} 没有可下载文件，已跳过")
            continue
        filename = file_info.get("filename") or Path(file_info["url"]).name
        filenames.append(filename)
        targets.append((
            file_info["url"],
            Path(mods_dir, filename),
            (file_info.get("hashes") or {}).get("sha1", ""),
            file_info.get("size") or 0,
        ))

        project_id = version_data.get("project_id") or filename
        previous = manifest.get(project_id) or {}
        if previous.get("filename") and previous["filename"] != filename:
            old_path = Path(mods_dir, previous["filename"])
            if old_path.is_file():
                old_files.append(old_path)

        manifest[project_id] = {
            "filename": filename,
            "version_id": version_data.get("id", ""),
            "version_number": version_data.get("version_number", ""),
            "name": version_data.get("name", ""),
        }
        log(f"  {filename}（{version_data.get('version_number') or ''}）")

    if not targets:
        raise ValueError("没有解析到任何可下载的模组文件")

    if not download(targets, description="模组"):
        raise RuntimeError("模组没有下载完整，重新运行命令会继续补下")

    for old_path in old_files:
        if old_path.is_file():
            old_path.unlink()
            log(f"  已移除旧版本 {old_path.name}")
    _save_manifest(directory, manifest)
    return filenames


def list_installed(instance_name: str) -> list[Path]:
    meta, _, _, directory = instance_context(instance_name)
    mods_dir = Path(directory, "mods")
    if not mods_dir.is_dir():
        return []
    return sorted(path for path in mods_dir.iterdir() if path.is_file() and path.suffix.lower() == ".jar")
