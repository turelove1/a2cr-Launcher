# a2Cr Launcher

一个使用 Python 制作的 CLI Minecraft 启动器

## 如何开发

### Step 1 克隆源代码和准备开发环境

1. 首先，这个程序是基于 Python
   开发的，因此，这里推荐的开发环境是 [JetBrains PyCharm](https://www.jetbrains.com/pycharm/download/)  
   _[Visual Studio Code](https://code.visualstudio.com) 也是可以的_

2. 其次，是 Python 环境，这里推荐使用 `uv`， 一个极其轻量的 Python 虚拟环境和包管理器。  
   把这段脚本复制到 PowerShell 里即可（桌面右键 --> 终端）

    ```bash
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

3. 再之后，安装 [Git](https://git-scm.com/install/windows) ，这个是用来克隆源代码的工具  
   如果还没有安装的话，点上面链接下载安装包，安装一路下一步就可以

4. 接下来，是仓库的配置  
   如果需要对这个项目开发的话，需要 [Fork 代码](https://github.com/CILXRY/a2cr-Launcher/fork)
   ，也就是给代码仓库创建一个副本。  
   在创建一个 Fork 之后的项目，点击右上角的绿色的 `code`， 复制地址
5. 然后，在文件管理器里找一个存放代码的位置，打开终端

   ```bash
   git clone <刚刚复制的地址> # 比如， git clone https://github.com/CILXRY/a2cr-Launcher
   
   # Git 的配置
   git config --global user.name "你的名字"
   git config --global user.email "你的邮箱" # 设置和 GitHub 相同的邮箱
   ```
6. 最后，在 PyCharm 里打开这个存放代码的文件夹，在终端里运行 `uv run al` 即可。

## 使用

```bash
uv run al version                         # 查看可用版本
uv run al install --version 26.2          # 安装原版
uv run al launch --version 26.2           # 启动原版
```

### 导入整合包

支持三种整合包格式：

- **Modrinth** `.mrpack`
- **CurseForge** 整合包 `.zip`（压缩包里有 `manifest.json`）
- **HMCL / PCL** 导出的整合包（压缩包里有 `.minecraft` 目录）

```bash
uv run al import "Fabulously Optimized.mrpack"
uv run al import "Create 整合包.zip" --name "机械动力"
```

导入时会自动完成：

1. 识别 Minecraft 版本和加载器（Fabric / Quilt / Forge / NeoForge）
2. 下载原版客户端、资源文件和运行库
3. 安装对应加载器（Forge / NeoForge 会调用官方安装器，第一次会慢一些）
4. 解压 `overrides` 或整合包自带的文件到 `~/.a2CrLauncher/instances/<实例名>/`
5. 下载清单里的 mods

导入完成后启动：

```bash
uv run al launch --instance "机械动力"
uv run al launch --instance "机械动力" --memory 8G   # 大型整合包可以调大内存
```

查看已经导入的整合包：

```bash
uv run al instance list
```

### 下载模组

从 [Modrinth](https://modrinth.com/mods) 搜索模组，直接装进指定实例（自动适配实例的 Minecraft 版本和加载器，并补上前置依赖）：

```bash
# 在实例的版本/加载器范围内搜索
uv run al mod search jei --instance "机械动力"

# 安装（自动选最新兼容版本，自动下载 required 依赖）
uv run al mod install jei --instance "机械动力"

# 只看某个版本、不装依赖
uv run al mod install jei --instance "机械动力" --version-id <Modrinth 版本 id> --no-deps

# 查看实例里已经装了哪些模组
uv run al mod list --instance "机械动力"
```

没有实例时也可以按版本和加载器搜索：

```bash
uv run al mod search sodium --version 1.21.1 --loader fabric
```

