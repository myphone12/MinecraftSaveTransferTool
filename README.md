# Minecraft 存档玩家数据迁移工具

基于 tkinter 的 Minecraft 存档玩家数据管理小工具，支持房主修改、UUID 迁移/交换、玩家参数编辑与存档基础参数修改。所有操作先进入待操作队列（支持撤销/重做），确认保存后才写入存档。

## 功能

- **玩家列表**：扫描存档玩家 UUID，通过 Mojang API 获取玩家名、Crafatar/Minotar 获取头像；离线玩家显示"离线玩家"+ 史蒂夫头像
- **修改房主**：旧版存档将目标玩家数据完整克隆到 `level.dat` 的 `Data/Player`（背包、属性无丢失）；新版存档写入 `Data/singleplayer_uuid`；缺失标签自动创建（服务器存档亦可用）
- **UUID 迁移/交换**：搜索文件名含目标 UUID 的 `.dat/.nbt/.snbt/.json`，替换文件内容（字符串、`TAG_Int_Array`/`TAG_Long_Array`/字节数组形式的 UUID，含模组哈希目录重命名）并重命名文件；双方均有文件时自动经临时 UUID 三步交换；迁移范围可按 玩家数据 / 进度数据 / 统计数据 / 其他(mod数据) 勾选
- **玩家参数编辑**：双击玩家弹窗修改游戏模式、生命值、饥饿值（游戏风格可点击状态条，支持半颗）、饱和度、经验等级（自动按原版公式重算 XpTotal/XpP/Score）；旧版房主同步双写 `level.dat`
- **存档基础参数**：存档名称、难度、锁定难度、允许命令、默认游戏模式（新旧版难度存储格式自动转换）
- **UUID 获取**：按玩家名获取 UUID——在线 API / PCL2 离线算法（标准、Steve、Alex）/ PCL2-CE·HMCL·Bukkit 算法（标准、传统）
- **文件菜单**：保存全部修改到存档、备份存档（复制到 `backups/时间戳`）、另存为修改存档（在副本上应用待操作，原存档不动）
- **操作日志**：底部日志区实时显示确认预览（将修改的文件清单）与执行明细

## 存档格式支持

| 格式 | 玩家数据 | 房主标记 |
|---|---|---|
| 旧版 | `playerdata/<uuid>.dat` | `level.dat → Data/Player` |
| 新版 | `players/data/<uuid>.dat`（进度/统计在 `players/advancements`、`players/stats`） | `level.dat → Data/singleplayer_uuid` |

选择存档时自动检测格式；服务器存档（无房主标记）同样支持，修改房主时自动创建所需标签。

## 运行环境

- Python 3.10+（自带 tkinter）
- NBT 读写使用 [twoolie/NBT](https://github.com/twoolie/NBT)
- 玩家名/头像获取需要网络；无网络时显示离线玩家与史蒂夫头像

直接运行：

```bash
python main.py
```

## 打包 exe（Nuitka）

```
python -m nuitka --standalone --onefile ^
  --windows-icon-from-ico="./res/icon.ico" --enable-plugin=tk-inter ^
  --include-data-dir=res=res ^
  --include-data-files=NBT-version-1.5.1/nbt/nbt.py=NBT-version-1.5.1/nbt/nbt.py ^
  --assume-yes-for-downloads main.py
```

要点：
- `--include-data-dir=res=res` 必须（图标资源）
- `--include-data-files=...nbt.py=...` 必须：程序在运行时直接加载该源码文件（绕过 nbt 包 `__init__.py` 的星号导入，其在 Nuitka 编译后会导致循环导入崩溃，且不受 pip 安装的同名包干扰），因此无需设置 PYTHONPATH，PowerShell/cmd/bash 下命令一致
- 注意用 `--include-data-files` 而不是 `--include-data-dir` 打包 nbt.py：目录因含 `__init__.py` 会被 Nuitka 跳过

## 项目结构

```
main.py            程序入口
ui.py              主窗口（菜单、玩家列表、功能面板、日志区）
player_dialog.py   玩家参数编辑弹窗与可点击状态条
save_manager.py    存档加载、格式检测、UUID 文件扫描与分类
nbt_ops.py         NBT 读写、UUID 替换、房主克隆、世界/玩家参数读写
operations.py      待操作队列、撤销/重做、执行引擎、备份/另存为
player_api.py      玩家名/头像在线获取（后台线程）
uuid_gen.py        PCL2 / PCL2-CE·HMCL 离线 UUID 算法
res/               图标资源（心形/鸡腿状态条、史蒂夫、窗口图标）
NBT-version-1.5.1/ vendored nbt 库
```

## 注意事项

- **修改房主前建议先备份**：单人模式进入存档时加载的即为房主数据，仅改房主不迁移 UUID 可能导致存档覆盖异常（界面中已有警示）
- 所有"确认"仅记录待操作，可撤销（Ctrl+Z）/重做（Ctrl+Y）/重置；执行"保存全部修改到存档"才真正写盘
- 模组显示名中的 8 位 UUID 短前缀（如 `名字#6fa5a27b`）不参与替换，仅影响显示文本

## 网盘链接

蓝奏云链接：<https://smb233.lanzouw.com/b0kpbtwjc>
密码：14r2