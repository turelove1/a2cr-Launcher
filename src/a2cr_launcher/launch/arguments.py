from os import pathsep
from pathlib import Path
from string import Template

from a2cr_launcher.auth.offline import offline_uuid
from a2cr_launcher.core.paths import VERSIONS_DIR, ASSETS_DIR, LIBRARIES_DIR, LOG_CONFIGS_DIR
from a2cr_launcher.core.platform_info import current_platform
from a2cr_launcher.java.discover import find_java
from a2cr_launcher.launch.classpath import build_classpath
from a2cr_launcher.launch.rules import is_allowed, feature_rule_list


def _substitute(value, values):
    """替换参数里的 ${...} 占位符。"""
    return Template(value).substitute(values) if isinstance(value, str) else value


def _build_java_arguments(arg_raw, values, meta, dropped_args):
    arguments = []

    # Memory
    arguments.append(f"-Xmx{values['max_memory']}")
    arguments.append(f"-Xms{values['max_memory']}")

    # Java Args
    for arg in arg_raw.get('jvm') or []:
        if type(arg) is dict:
            if is_allowed(arg["rules"], current_platform()[0], current_platform()[1]):
                if type(arg["value"]) is list:
                    # 这里用extend是指把arg["value"]里的值全部追加给arguments
                    arguments.extend(_substitute(item, values) for item in arg["value"])
                else:
                    arguments.append(_substitute(arg["value"], values))
            else:
                dropped_args.append(arg)
        elif type(arg) is str:
            arguments.append(_substitute(arg, values))
        else:
            dropped_args.append(arg)

    # Log4J
    if meta.get('logging'):
        arguments.append(Template(meta['logging']['client'].get("argument")).substitute(
            path=str(Path(LOG_CONFIGS_DIR, meta['logging']['client']["file"]["id"]))))

    # Main Class
    arguments.append(meta.get("mainClass"))

    return arguments


def _build_game_arguments(arg_raw, values):
    arguments = []
    for arg in arg_raw.get('game') or []:
        if type(arg) is dict:
            result = feature_rule_list([arg], current_platform()[0], current_platform()[1], values["current_features"],
                                       values["feature_variables"])
            if result:
                arguments.extend(result)
        elif type(arg) is str:
            arguments.append(_substitute(arg, values))
    return arguments


def build_arguments(meta, game_dir: Path, name="a2Cr", max_memory="16G"):
    version = meta["id"]
    base_version = meta.get("_baseVersion", version)
    main_class = str(meta.get("mainClass") or "")
    # Forge/NeoForge 的 BootstrapLauncher 会自己把打过补丁的 minecraft jar 加进模块层，
    # 再把原版 client.jar 一起放进去会出现两个导出同一包的模块（minecraft 和 client），
    # 模块解析直接失败。原版 / Fabric / Quilt 则需要这个 client.jar。
    include_client = "bootstraplauncher" not in main_class.lower()
    values = {
        "auth_player_name": name,
        "version_name": version,
        "game_directory": str(game_dir),
        "assets_root": str(ASSETS_DIR),
        "assets_index_name": meta["assetIndex"]["id"],
        "auth_uuid": offline_uuid(name),
        "auth_access_token": "0",
        "clientid": "", "auth_xuid": "",
        "user_type": "legacy",
        "version_type": meta.get("type", "release"),
        "natives_directory": str(Path(VERSIONS_DIR, version, "natives")),
        "library_directory": str(LIBRARIES_DIR),
        "classpath_separator": pathsep,
        "launcher_name": "a2cr-launcher", "launcher_version": "0.2",
        "max_memory": max_memory,
        "classpath": build_classpath(meta, LIBRARIES_DIR, current_platform()[0], current_platform()[1],
                                     str(Path(VERSIONS_DIR, base_version, "client.jar")),
                                     include_client=include_client),
        "current_features": {"is_demo_user": False, "has_custom_resolution": False, "has_quick_plays_support": False,
                             "is_quick_play_singleplayer": False, "is_quick_play_multiplayer": False,
                             "is_quick_play_realms": False},
        "feature_variables": {"resolution_width": 1920, "resolution_height": 1080, "quickPlayPath": "",
                              "quickPlaySingleplayer": "", "quickPlayMultiplayer": "", "quickPlayRealms": ""},
    }

    arguments = []
    dropped_args = []  # 排错用的
    arg_raw = meta.get('arguments')

    # Java Execution
    arguments.append(find_java(meta["javaVersion"]["majorVersion"], ))

    # Java Arguments
    arguments.extend(_build_java_arguments(arg_raw, values, meta, dropped_args))

    # Game Arguments
    arguments.extend(_build_game_arguments(arg_raw, values, ))

    return arguments
