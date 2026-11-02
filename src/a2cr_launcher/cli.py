from argparse import ArgumentParser
from datetime import datetime
from os import pathsep
from pathlib import Path
from sys import exit

from requests import RequestException
from rich.console import Console
from rich.table import Table

from a2cr_launcher import instance
from a2cr_launcher.core.paths import VERSIONS_DIR, LIBRARIES_DIR, ASSETS_DIR, INSTANCES_DIR, LOG_CONFIGS_DIR
from a2cr_launcher.core.platform_info import current_platform
from a2cr_launcher.launch.arguments import build_arguments
from a2cr_launcher.launch.install import (download_client, download_logging, download_assets, download_libraries,
                                          ensure_natives_dirs)
from a2cr_launcher.launch.process import launch
from a2cr_launcher.meta.manifest import get_version_manifest
from a2cr_launcher.meta.merge import resolve_meta
from a2cr_launcher.meta.versions import get_version_meta
from a2cr_launcher.modpack import import_pack
from a2cr_launcher.mods import modrinth
from a2cr_launcher.mods.install import instance_context as mod_instance_context
from a2cr_launcher.mods.install import install as install_mod
from a2cr_launcher.mods.install import list_installed as list_installed_mods


def _start_game(console: Console, version_id: str, game_dir: Path, memory: str = "4G") -> int:
    """解析版本（合并 inheritsFrom）、检查文件、启动游戏，返回退出码。"""
    try:
        meta = resolve_meta(version_id)
    except ValueError as err:
        console.print(f"[red]{err}[/red]")
        return 1
    except RequestException as err:
        console.print(f"[red][Network Error] 无法获取版本信息，请检查网络或者代理设置: {err}[/red]")
        return 1

    game_dir.mkdir(parents=True, exist_ok=True)
    try:
        ensure_natives_dirs(version_id)
    except OSError as err:
        console.print(f"[red]无法创建 natives 目录: {err}[/red]")
        return 1

    if not isinstance(meta.get("arguments"), dict):
        console.print("[red]这个版本用的是旧的启动参数格式（1.13 以前），当前启动器还不支持。[/red]")
        return 1

    try:
        arguments = build_arguments(meta, game_dir, max_memory=memory)
    except RuntimeError as err:
        console.print(f"[red]{err}[/red]")
        return 1

    # 开游戏之前先确认文件齐不齐，否则 Java 只会抛一堆看不懂的 ClassNotFound
    if "-cp" in arguments:
        classpath = arguments[arguments.index("-cp") + 1]
        missing = [item for item in classpath.split(pathsep) if item and not Path(item).is_file()]
        if missing:
            console.print(f"[red]缺少 {len(missing)} 个运行库或客户端文件，"
                          f"请先运行 `al install --version {meta.get('_baseVersion', version_id)}`[/red]")
            for item in missing[:5]:
                console.print(f"  [yellow]{item}[/yellow]")
            if len(missing) > 5:
                console.print(f"  ... 还有 {len(missing) - 5} 个")
            return 1

    console.print(f"Java: [cyan]{arguments[0]}[/cyan]")
    console.print(f"游戏目录: [cyan]{game_dir}[/cyan]")
    console.print(f"日志文件: [cyan]{Path(game_dir, 'logs', 'latest.log')}[/cyan]")
    exit_code = launch(arguments, game_dir)
    console.print(f"游戏已退出，退出码 {exit_code}")
    return exit_code


def main():
    console = Console()
    parser = ArgumentParser(description='a2cr Minecraft Launcher')
    subparsers = parser.add_subparsers(dest='command')

    version_parser = subparsers.add_parser('version')
    version_parser.add_argument('--limit', default=20, type=int)
    version_parser.add_argument('--type', action='store', default='release')

    install_parser = subparsers.add_parser('install')
    install_parser.add_argument('--version', action='store')

    launch_parser = subparsers.add_parser('launch')
    launch_parser.add_argument('--version', action='store')
    launch_parser.add_argument('--instance', action='store')
    launch_parser.add_argument('--memory', action='store', default='4G')

    import_parser = subparsers.add_parser('import')
    import_parser.add_argument('path', help='整合包压缩包（.mrpack / .zip）')
    import_parser.add_argument('--name', action='store', help='实例名，默认用整合包自带的名字')

    instance_parser = subparsers.add_parser('instance')
    instance_sub = instance_parser.add_subparsers(dest='instance_action')
    instance_sub.add_parser('list')

    mod_parser = subparsers.add_parser('mod')
    mod_sub = mod_parser.add_subparsers(dest='mod_action', required=True)

    mod_search = mod_sub.add_parser('search', help='在 Modrinth 搜索模组')
    mod_search.add_argument('query')
    mod_search.add_argument('--limit', type=int, default=10)
    mod_search.add_argument('--instance', help='按这个实例的版本/加载器过滤')
    mod_search.add_argument('--version', help='Minecraft 版本（不给 --instance 时必填）')
    mod_search.add_argument('--loader', choices=['forge', 'neoforge', 'fabric', 'quilt'],
                            help='加载器（不给 --instance 时必填）')

    mod_install = mod_sub.add_parser('install', help='把模组下载到实例')
    mod_install.add_argument('slug', help='Modrinth 项目 slug，比如 jei')
    mod_install.add_argument('--instance', required=True)
    mod_install.add_argument('--version-id', help='指定 Modrinth 版本 id（默认自动选最新兼容版本）')
    mod_install.add_argument('--no-deps', action='store_true', help='不自动安装前置依赖')

    mod_list = mod_sub.add_parser('list', help='列出实例里已安装的模组')
    mod_list.add_argument('--instance', required=True)

    args = parser.parse_args()

    if "unknown" in current_platform():
        print("检测到不支持的系统。")
        exit(1)

    if args.command == 'version':
        try:
            version_list = get_version_manifest(args.type, args.limit)
        except RequestException as err:
            print(f'[Network Error] 无法连接服务器,请检查网络或者代理设置: {err}')
            exit(1)

        version_table = Table(title="Minecraft Version List")
        version_table.add_column("ID")
        version_table.add_column("Type")
        version_table.add_column("Update Time")
        version_table.add_column("Release Time")
        for version in version_list:
            version_table.add_row(version.get('id'), version.get('type'),
                                  datetime.fromisoformat(version["time"]).strftime("%Y-%m-%d %H:%M:%S") if version.get(
                                      "time") else None,
                                  datetime.fromisoformat(version["releaseTime"]).strftime(
                                      "%Y-%m-%d %H:%M:%S") if version.get("releaseTime") else None)

        console.print(version_table)

    elif args.command == 'install':
        console.print(f"开始安装 Minecraft [bold]{args.version}[/bold]")
        try:
            meta = get_version_meta(args.version, refresh=True)
        except ValueError as err:
            console.print(f"[red]{err}[/red]")
            exit(1)
        except RequestException as err:
            console.print(f"[red][Network Error] 无法获取版本信息，请检查网络或者代理设置: {err}[/red]")
            exit(1)

        steps = [
            ("客户端", lambda: download_client(meta, VERSIONS_DIR)),
            ("日志配置", lambda: download_logging(meta, LOG_CONFIGS_DIR)),
            ("资源文件", lambda: download_assets(meta, ASSETS_DIR)),
            ("运行库", lambda: download_libraries(meta, LIBRARIES_DIR)),
        ]
        failed = []
        for index, (name, step) in enumerate(steps, start=1):
            console.rule(f"[bold]{index}/{len(steps)} {name}")
            try:
                ok = step()
            except Exception as err:  # 单个部分出错不应该让整个安装直接崩掉
                console.print(f"[red]{name} 失败: {type(err).__name__}: {err}[/red]")
                ok = False
            if not ok:
                failed.append(name)

        if failed:
            console.print(f"[red]安装未完成，缺少：{'、'.join(failed)}[/red]")
            console.print("重新运行同一条命令即可从断点继续，已经完整的文件会自动跳过。")
            exit(1)
        console.print("[green]全部下载完成。[/green]")

    elif args.command == 'import':
        def _plain_log(text: str) -> None:
            # 安装器输出里可能有 emoji，走 rich 的旧版 Windows 渲染会因 GBK 编码崩溃
            print(text, flush=True)

        try:
            meta = import_pack(Path(args.path), args.name, log=_plain_log)
        except (FileNotFoundError, ValueError, RuntimeError, RequestException, OSError) as err:
            console.print(f"[red]导入失败：{err}[/red]")
            exit(1)

        console.print(f"[green]整合包导入完成：{meta['name']}[/green]")
        console.print(f"启动命令：al launch --instance [bold]{meta['folder']}[/bold]")

    elif args.command == 'instance':
        if args.instance_action != 'list':
            instance_parser.print_help()
            exit(1)
        instances = instance.list_all()
        if not instances:
            console.print("还没有导入任何整合包，先运行 `al import <整合包.zip>`。")
            exit(0)
        table = Table(title="Instances")
        table.add_column("名字")
        table.add_column("目录")
        table.add_column("Minecraft")
        table.add_column("加载器")
        table.add_column("导入时间")
        for item in instances:
            loader = item.get("loader") or {}
            loader_text = f"{loader.get('type', 'vanilla')} {loader.get('version', '')}".strip()
            table.add_row(item.get("name", ""), item.get("folder", ""), item.get("mc_version", ""),
                          loader_text, item.get("created_at", ""))
        console.print(table)

    elif args.command == 'mod':
        if args.mod_action == 'search':
            mc_version, loader = args.version, args.loader
            if args.instance:
                try:
                    _, mc_version, loader, _ = mod_instance_context(args.instance)
                except ValueError as err:
                    console.print(f"[red]{err}[/red]")
                    exit(1)
            if not mc_version or not loader:
                console.print("[red]搜索模组需要 --instance，或者同时指定 --version 和 --loader[/red]")
                exit(1)

            try:
                hits = modrinth.search(args.query, mc_version, loader, args.limit)
            except RequestException as err:
                console.print(f"[red][Network Error] 搜索失败，请检查网络或者代理设置: {err}[/red]")
                exit(1)

            if not hits:
                console.print(f"没有找到适配 Minecraft {mc_version} / {loader} 的模组。")
                exit(0)

            result_table = Table(title=f"Modrinth 搜索结果（{mc_version} / {loader}）")
            result_table.add_column("名称")
            result_table.add_column("Slug")
            result_table.add_column("下载量", justify="right")
            result_table.add_column("说明")
            for hit in hits:
                description = (hit.get("description") or "").replace("\n", " ")
                if len(description) > 50:
                    description = description[:50] + "..."
                result_table.add_row(hit.get("title", ""), hit.get("slug", ""),
                                     f"{hit.get('downloads', 0):,}", description)
            console.print(result_table)
            console.print(f"安装：al mod install <slug> --instance \"{args.instance or '<实例名>'}\"")

        elif args.mod_action == 'install':
            try:
                files = install_mod(args.slug, args.instance, args.version_id,
                                    with_deps=not args.no_deps,
                                    log=lambda text: console.print(text, markup=False, highlight=False))
            except (ValueError, RuntimeError, RequestException, OSError) as err:
                console.print(f"[red]安装失败：{err}[/red]")
                exit(1)
            console.print(f"[green]完成，共处理 {len(files)} 个模组文件。[/green]")
            console.print(f"启动：al launch --instance \"{args.instance}\" --memory 8G")

        elif args.mod_action == 'list':
            try:
                files = list_installed_mods(args.instance)
            except ValueError as err:
                console.print(f"[red]{err}[/red]")
                exit(1)
            if not files:
                console.print("这个实例还没有安装任何模组。")
                exit(0)
            mods_table = Table(title=f"已安装模组（{args.instance}）")
            mods_table.add_column("文件名")
            mods_table.add_column("大小", justify="right")
            for path in files:
                mods_table.add_row(path.name, f"{path.stat().st_size / 1024 / 1024:.1f} MB")
            console.print(mods_table)

    elif args.command == 'launch':
        if args.instance:
            meta = instance.load(args.instance)
            if meta is None:
                console.print(f"[red]找不到实例：{args.instance}，可以用 `al instance list` 查看已导入的整合包[/red]")
                exit(1)
            game_dir = instance.instance_dir(meta["folder"])
            exit(_start_game(console, meta["version_id"], game_dir, args.memory))
        if args.version:
            exit(_start_game(console, args.version, Path(INSTANCES_DIR, args.version), args.memory))
        console.print("[red]请指定 --version（原版版本）或 --instance（整合包实例）[/red]")
        exit(1)

    else:
        parser.print_help()
        exit(1)


if __name__ == '__main__':
    main()
