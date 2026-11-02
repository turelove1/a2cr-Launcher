"""整合包导入：识别格式 → 装原版 → 装加载器 → 建实例 → 解压 overrides → 下载 mods。"""

from pathlib import Path

from a2cr_launcher import instance
from a2cr_launcher.core.download import download
from a2cr_launcher.core.paths import ASSETS_DIR, LIBRARIES_DIR, LOG_CONFIGS_DIR, VERSIONS_DIR
from a2cr_launcher.launch.install import download_assets, download_client, download_libraries, download_logging
from a2cr_launcher.meta.versions import get_version_meta
from a2cr_launcher.modloader import install_loader
from a2cr_launcher.modpack import archive, curseforge, local, modrinth


def detect(path: Path) -> dict:
    """根据压缩包内容判断整合包格式。"""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"找不到整合包文件：{path}")
    if modrinth.is_modrinth(path):
        return modrinth.read(path)
    if curseforge.is_curseforge(path):
        return curseforge.read(path)
    if local.is_local(path):
        return local.read(path)
    raise ValueError("无法识别的整合包格式：支持 Modrinth .mrpack、CurseForge .zip、HMCL/PCL 导出的压缩包")


def _install_vanilla(mc_version: str, log) -> None:
    log(f"安装原版 Minecraft {mc_version} ...")
    meta = get_version_meta(mc_version, refresh=True)
    results = [
        download_client(meta, VERSIONS_DIR),
        download_logging(meta, LOG_CONFIGS_DIR),
        download_assets(meta, ASSETS_DIR),
        download_libraries(meta, LIBRARIES_DIR),
    ]
    if not all(results):
        raise RuntimeError(f"原版 {mc_version} 没有下载完整，请重新运行导入命令")


def _target_path(root: Path, relative: str) -> Path | None:
    target = (Path(root) / relative).resolve()
    try:
        target.relative_to(Path(root).resolve())
    except ValueError:
        return None
    return target


def import_pack(path: Path, name: str | None = None, log=print) -> dict:
    """
    导入一个整合包。

    Args:
        path: 整合包压缩包路径
        name: 实例名，为空时用整合包自带的名字
        log: 输出日志的函数

    Returns:
        dict: 新建实例的元数据
    """
    path = Path(path)
    plan = detect(path)

    description = f"{plan['name']}（Minecraft {plan['mc_version']}"
    if plan["loader"] != "vanilla":
        description += f" / {plan['loader']} {plan['loader_version']}"
    log(description + "）")

    failed_files: list[dict] = []
    if plan["format"] == "curseforge":
        total = len(plan["files"])
        log(f"解析 {total} 个 CurseForge 文件 ...")

        def _progress(done, count):
            if count and (done == count or done % 20 == 0):
                log(f"  已解析 {done}/{count}")

        def _error(item, _exc):
            log(f"  跳过无法解析的文件：project {item['project']} / file {item['file_id']}")

        plan["files"], failed_files = curseforge.resolve_files(
            plan["files"], on_progress=_progress, on_error=_error)
        log("文件地址解析完成")
        if failed_files:
            log(f"有 {len(failed_files)} 个文件在镜像和官网都查不到，已跳过，其余文件会继续导入")

    _install_vanilla(plan["mc_version"], log)

    if plan["loader"] == "vanilla":
        version_id = plan["mc_version"]
    else:
        log(f"安装 {plan['loader']} {plan['loader_version']} ...")
        version_id = install_loader(plan["mc_version"], plan["loader"], plan["loader_version"], log=log)

    source = {"format": plan["format"], "file": str(path), "pack_version": plan["pack_version"]}
    existing = None if name else instance.find_by_source(str(path))
    if existing is not None:
        # 同一个压缩包重复导入（比如上次下载失败）时，接着用原来的实例继续补文件
        meta = existing
        meta.update({
            "mc_version": plan["mc_version"],
            "version_id": version_id,
            "loader": {"type": plan["loader"], "version": plan["loader_version"]},
            "source": source,
        })
        instance.save(meta)
        log(f"继续使用已有实例：{meta['folder']}")
    else:
        meta = instance.create(
            name or plan["name"],
            plan["mc_version"],
            version_id,
            loader={"type": plan["loader"], "version": plan["loader_version"]},
            source=source,
        )
        log(f"创建实例：{meta['folder']}")

    directory = instance.instance_dir(meta["folder"])

    if plan["format"] == "local":
        extracted = archive.extract_prefix(path, plan["extract_prefix"], directory,
                                           skip_prefixes=plan["skip_prefixes"])
        log(f"解压整合包文件 {extracted} 个")
    elif plan["overrides"]:
        extracted = archive.extract_overrides(path, plan["overrides"], directory)
        log(f"解压 overrides {extracted} 个文件")

    targets = []
    for item in plan["files"]:
        target = _target_path(directory, item["path"])
        if target is None:
            continue
        targets.append((item["url"], target, item["sha1"], item["size"]))
    if targets:
        if not download(targets, description="整合包文件"):
            raise RuntimeError("整合包里的文件没有下载完整，重新运行导入命令会继续补下")

    if failed_files:
        missing_path = Path(directory, "missing-files.txt")
        lines = [f"project={item['project']} file={item['file_id']} {item['error']}" for item in failed_files]
        missing_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log(f"缺少 {len(failed_files)} 个文件，清单已写入 {missing_path}；重新导入会再试一次")

    Path(directory, "mods").mkdir(exist_ok=True)
    return meta
