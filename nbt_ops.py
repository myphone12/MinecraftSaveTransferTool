# -*- coding: utf-8 -*-
"""nbt_ops.py — NBT 文件读写与 UUID 操作封装。

基于本地 nbt 库（NBT-version-1.5.1）实现对 .dat / .nbt 文件的读取、
修改与保存，提供三类核心能力：
  1. UUID 形式转换（带横杠 / 无横杠 / Java UUID int 数组）
  2. 深度遍历 NBT 树，替换其中出现的目标 UUID（字符串与整型数组形式）
  3. 将目标玩家 playerdata 完整克隆为 level.dat 的 Data/Player（修改房主）
"""

import io
import os
import re
import sys

# 将本地 nbt 库加入模块搜索路径（未安装到 site-packages，直接以源码目录引用）
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "NBT-version-1.5.1"))

from nbt.nbt import (  # noqa: E402
    NBTFile,
    TAG_Byte_Array,
    TAG_Compound,
    TAG_Int_Array,
    TAG_List,
    TAG_Long_Array,
    TAG_String,
)

# UUID 正则：匹配标准的 8-4-4-4-12 十六进制格式
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


# ---------------------------------------------------------------------------
# UUID 形式转换
# ---------------------------------------------------------------------------

def uuid_dashed(uuid: str) -> str:
    """返回带横杠的小写 UUID（xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx）。"""
    hex_str = uuid.replace("-", "").lower()
    return "-".join([hex_str[0:8], hex_str[8:12], hex_str[12:16],
                     hex_str[16:20], hex_str[20:32]])


def uuid_undashed(uuid: str) -> str:
    """返回无横杠的小写 UUID（32 位十六进制字符串）。"""
    return uuid.replace("-", "").lower()


def uuid_to_ints(uuid: str):
    """将 UUID 转为 Java UUID 的 4 个有符号 32 位整数。

    Minecraft 在 NBT 中常以 TAG_Int_Array（如实体的 UUID 标签）存储 UUID，
    即 UUID 的 128 位按大端序切分为 4 个 int32。
    """
    b = bytes.fromhex(uuid_undashed(uuid))
    ints = []
    for i in range(4):
        v = int.from_bytes(b[i * 4:(i + 1) * 4], "big", signed=False)
        # 转为有符号 int32（Java 语义）
        ints.append(v - 0x100000000 if v >= 0x80000000 else v)
    return ints


def uuid_to_longs(uuid: str):
    """将 UUID 转为 Java UUID 的 2 个有符号 64 位整数（most, least）。

    部分模组以 TAG_Long_Array 存储 UUID。
    """
    b = bytes.fromhex(uuid_undashed(uuid))
    longs = []
    for i in range(2):
        v = int.from_bytes(b[i * 8:(i + 1) * 8], "big", signed=False)
        longs.append(v - 0x10000000000000000 if v >= 0x8000000000000000 else v)
    return longs


# ---------------------------------------------------------------------------
# NBT 文件读写
# ---------------------------------------------------------------------------

def load_nbt(path: str):
    """读取 NBT 文件，自动识别 gzip 压缩与原始未压缩两种格式。

    返回 (NBTFile, compressed)。原版存档的 .dat/.nbt 均为 gzip 压缩，
    但部分模组的 .nbt 文件是未压缩的原始 NBT 流。
    """
    try:
        return NBTFile(filename=path), True
    except Exception:
        # gzip 解析失败 → 尝试按未压缩的原始 NBT 流解析
        with open(path, "rb") as f:
            raw = f.read()
        return NBTFile(buffer=io.BytesIO(raw)), False


def save_nbt(nbt_file: NBTFile, path: str, compressed: bool = True) -> None:
    """将 NBT 树写回文件，compressed 决定使用 gzip 压缩还是原始格式。"""
    if compressed:
        nbt_file.write_file(filename=path)
    else:
        buf = io.BytesIO()
        nbt_file.write_file(buffer=buf)
        with open(path, "wb") as f:
            f.write(buf.getvalue())


def deep_copy_nbt(nbt_file: NBTFile) -> NBTFile:
    """通过序列化到内存缓冲区再解析，实现 NBT 树的深拷贝。"""
    buf = io.BytesIO()
    nbt_file.write_file(buffer=buf)
    buf.seek(0)
    return NBTFile(buffer=buf)


# ---------------------------------------------------------------------------
# UUID 替换（NBT 树 / 文本文件）
# ---------------------------------------------------------------------------

def _replace_in_tag(tag, old_forms, new_forms, counter):
    """递归遍历 NBT 树，替换所有匹配目标 UUID 的值。

    old_forms / new_forms: (dashed, undashed, ints, longs) 四种表示。
    counter: 单元素列表，用于累计替换次数。
    """
    old_dashed, old_undashed, old_ints, old_longs = old_forms
    new_dashed, new_undashed, new_ints, new_longs = new_forms

    if isinstance(tag, TAG_String):
        # 字符串标签：替换其中出现的 UUID（大小写不敏感，保持原格式）
        value = tag.value
        pattern = re.compile(re.escape(old_dashed) + "|" + re.escape(old_undashed),
                             re.IGNORECASE)
        if pattern.search(value):
            def _sub(m):
                # 根据匹配到的形式（是否带横杠）决定替换形式
                return new_dashed if "-" in m.group(0) else new_undashed
            tag.value = pattern.sub(_sub, value)
            counter[0] += 1

    elif isinstance(tag, TAG_Int_Array):
        # 4 个 int 的数组且与目标 UUID 相同 → 替换为新 UUID 的 int 数组
        if len(tag.value) == 4 and list(tag.value) == old_ints:
            tag.value = new_ints
            counter[0] += 1

    elif isinstance(tag, TAG_Long_Array):
        # 2 个 long 的数组且与目标 UUID 相同 → 替换为新 UUID 的 long 数组
        if len(tag.value) == 2 and list(tag.value) == old_longs:
            tag.value = new_longs
            counter[0] += 1

    elif isinstance(tag, TAG_Byte_Array):
        # 字节数组中可能出现 UUID 的原始 16 字节形式
        old_bytes = bytes.fromhex(old_undashed)
        new_bytes = bytes.fromhex(new_undashed)
        raw = bytes(tag.value)
        if old_bytes in raw:
            tag.value = list(raw.replace(old_bytes, new_bytes))
            counter[0] += 1

    elif isinstance(tag, TAG_List):
        for child in tag:
            _replace_in_tag(child, old_forms, new_forms, counter)

    elif isinstance(tag, TAG_Compound):
        for child in tag.values():
            _replace_in_tag(child, old_forms, new_forms, counter)


def replace_uuid_in_nbt_file(path: str, old_uuid: str, new_uuid: str) -> int:
    """打开 .dat / .nbt 文件，替换树中所有目标 UUID，保存并返回替换次数。

    若文件无法按 NBT 解析（例如个别模组以 SNBT 文本存放 .nbt），
    则回退为纯文本替换，保证迁移不因单个文件格式特殊而中断。
    """
    old_forms = (uuid_dashed(old_uuid), uuid_undashed(old_uuid),
                 uuid_to_ints(old_uuid), uuid_to_longs(old_uuid))
    new_forms = (uuid_dashed(new_uuid), uuid_undashed(new_uuid),
                 uuid_to_ints(new_uuid), uuid_to_longs(new_uuid))
    try:
        nbt_file, compressed = load_nbt(path)
    except Exception:
        return replace_uuid_in_text_file(path, old_uuid, new_uuid)
    counter = [0]
    _replace_in_tag(nbt_file, old_forms, new_forms, counter)
    if counter[0] > 0:
        save_nbt(nbt_file, path, compressed)
    return counter[0]


def replace_uuid_in_text_file(path: str, old_uuid: str, new_uuid: str) -> int:
    """打开 .snbt / .json 文本文件，替换其中的目标 UUID，返回替换次数。"""
    with open(path, "r", encoding="utf-8", errors="surrogatepass") as f:
        content = f.read()
    pattern = re.compile(
        re.escape(uuid_dashed(old_uuid)) + "|" + re.escape(uuid_undashed(old_uuid)),
        re.IGNORECASE,
    )
    def _sub(m):
        return uuid_dashed(new_uuid) if "-" in m.group(0) else uuid_undashed(new_uuid)
    new_content, count = pattern.subn(_sub, content)
    if count > 0:
        with open(path, "w", encoding="utf-8", errors="surrogatepass") as f:
            f.write(new_content)
    return count


# ---------------------------------------------------------------------------
# 修改房主：旧版克隆 playerdata 到 Data/Player；新版写 Data/singleplayer_uuid
# ---------------------------------------------------------------------------

def set_host_in_level(save_dir: str, target_uuid: str,
                      layout: str = None) -> None:
    """把存档房主设为目标玩家，缺失的标签/复合标签自动创建。

    旧版：level.dat 的 Data/Player 复合标签即房主数据。将目标玩家
    playerdata 的全部内容深拷贝过去（背包、属性等复合列表无丢失）；
    服务器存档没有 Player 复合标签时自动创建。
    新版：房主由 Data/singleplayer_uuid（TAG_Int_Array）标记，
    玩家数据始终在 players/data 中，直接写入该标签（缺失则创建）。
    """
    from nbt.nbt import TAG_Compound, TAG_Int_Array

    if layout is None:
        layout = detect_save_layout(save_dir)
    target_uuid = uuid_dashed(target_uuid)
    player_path = playerdata_path(save_dir, target_uuid, layout)
    level_path = os.path.join(save_dir, "level.dat")
    level_nbt, level_compressed = load_nbt(level_path)

    if "Data" not in level_nbt:
        raise ValueError("level.dat 中缺少 Data 标签，可能不是有效的存档")
    data = level_nbt["Data"]

    if layout == LAYOUT_NEW:
        # 新版：写入/创建 singleplayer_uuid 标签
        uuid_tag = TAG_Int_Array(name="singleplayer_uuid")
        uuid_tag.value = uuid_to_ints(target_uuid)
        data["singleplayer_uuid"] = uuid_tag
        save_nbt(level_nbt, level_path, level_compressed)
        return

    # 旧版：克隆 playerdata 到 Data/Player（缺失则创建 Player 复合标签）
    if "Player" not in data.keys():
        data["Player"] = TAG_Compound(name="Player")
    player_nbt = deep_copy_nbt(load_nbt(player_path)[0])

    player_compound = data["Player"]
    # 清空原有 Player 的所有子标签，再写入目标玩家的全部标签
    player_compound.clear()
    for key in list(player_nbt.keys()):
        tag = player_nbt[key]
        tag.name = key
        player_compound[key] = tag

    # 保障：确保 Player/UUID 与目标玩家一致（游戏以该标签识别房主身份）
    uuid_tag = TAG_Int_Array(name="UUID")
    uuid_tag.value = uuid_to_ints(target_uuid)
    player_compound["UUID"] = uuid_tag

    save_nbt(level_nbt, level_path, level_compressed)


# 兼容旧名称
clone_player_to_level = set_host_in_level


# ---------------------------------------------------------------------------
# 存档格式检测与路径助手
# ---------------------------------------------------------------------------

# 存档布局：'old' = 旧版（playerdata/、Data/Player）
#           'new' = 新版（players/data|advancements|stats、Data/singleplayer_uuid）
LAYOUT_OLD = "old"
LAYOUT_NEW = "new"


def detect_save_layout(save_dir: str) -> str:
    """检测存档布局：存在 players/data 目录或 level.dat 含 singleplayer_uuid
    标签 → 新版；否则旧版。服务器存档（无 Player compound）按其目录结构判断。
    """
    if os.path.isdir(os.path.join(save_dir, "players", "data")):
        return LAYOUT_NEW
    try:
        level_nbt, _ = load_nbt(os.path.join(save_dir, "level.dat"))
        if "singleplayer_uuid" in level_nbt["Data"].keys():
            return LAYOUT_NEW
    except Exception:
        pass
    return LAYOUT_OLD


def playerdata_dir(save_dir: str, layout: str = None) -> str:
    """返回玩家数据目录：新版 players/data，旧版 playerdata。"""
    if layout is None:
        layout = detect_save_layout(save_dir)
    if layout == LAYOUT_NEW:
        return os.path.join(save_dir, "players", "data")
    return os.path.join(save_dir, "playerdata")


def playerdata_path(save_dir: str, uuid: str, layout: str = None) -> str:
    """返回指定玩家 playerdata 主文件路径（布局感知）。"""
    return os.path.join(playerdata_dir(save_dir, layout),
                        uuid_dashed(uuid) + ".dat")


# ---------------------------------------------------------------------------
# 房主检测
# ---------------------------------------------------------------------------

def ints_to_uuid(ints) -> str:
    """将 Java UUID 的 4 个有符号 int32 还原为带横杠小写 UUID。"""
    b = b"".join((i & 0xFFFFFFFF).to_bytes(4, "big", signed=False) for i in ints)
    return uuid_dashed(b.hex())


def detect_host_uuid(save_dir: str):
    """检测当前房主玩家的 UUID。

    旧版：level.dat 的 Data/Player/UUID（Player 复合标签即房主数据）；
    新版：level.dat 的 Data/singleplayer_uuid。
    检测不到（服务器存档无房主等）时返回 None。
    """
    try:
        level_nbt, _ = load_nbt(os.path.join(save_dir, "level.dat"))
        data = level_nbt["Data"]
        if "singleplayer_uuid" in data.keys():
            return ints_to_uuid(list(data["singleplayer_uuid"].value))
        if "Player" in data.keys():
            player = data["Player"]
            if "UUID" in player.keys():
                return ints_to_uuid(list(player["UUID"].value))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 存档基础参数（level.dat 的 Data 标签）
# ---------------------------------------------------------------------------

# 新版 difficulty_settings/difficulty 字符串 ↔ 难度数值
DIFFICULTY_STR_TO_INT = {"peaceful": 0, "easy": 1, "normal": 2, "hard": 3}
DIFFICULTY_INT_TO_STR = {v: k for k, v in DIFFICULTY_STR_TO_INT.items()}


def read_world_settings(save_dir: str) -> dict:
    """读取存档基础参数：名称、难度、锁定难度、允许命令、默认游戏模式。

    旧版难度存于 Data/Difficulty（byte）与 Data/DifficultyLocked（byte）；
    新版存于 Data/difficulty_settings 复合标签（difficulty 为字符串、
    locked 为 byte）。缺失的标签按游戏默认值补齐（普通难度、未锁定）。
    """
    level_nbt, _ = load_nbt(os.path.join(save_dir, "level.dat"))
    data = level_nbt["Data"]

    if "difficulty_settings" in data.keys():
        # 新版布局
        ds = data["difficulty_settings"]
        diff_str = str(ds["difficulty"].value) if "difficulty" in ds.keys() \
            else "normal"
        difficulty = DIFFICULTY_STR_TO_INT.get(diff_str.lower(), 2)
        locked = bool(ds["locked"].value) if "locked" in ds.keys() else False
    else:
        # 旧版布局
        difficulty = int(data["Difficulty"].value) \
            if "Difficulty" in data.keys() else 2
        locked = bool(data["DifficultyLocked"].value) \
            if "DifficultyLocked" in data.keys() else False

    return {
        "LevelName": str(data["LevelName"].value)
        if "LevelName" in data.keys() else "",
        "Difficulty": difficulty,
        "DifficultyLocked": locked,
        "allowCommands": bool(data["allowCommands"].value)
        if "allowCommands" in data.keys() else False,
        "GameType": int(data["GameType"].value)
        if "GameType" in data.keys() else 0,
    }


def write_world_settings(save_dir: str, settings: dict) -> None:
    """把存档基础参数写入 level.dat 的 Data 标签（只写传入的键）。

    按存档布局写入对应位置，缺失的标签/复合标签自动创建。
    """
    from nbt.nbt import TAG_Byte, TAG_Compound, TAG_Int, TAG_String

    level_path = os.path.join(save_dir, "level.dat")
    level_nbt, compressed = load_nbt(level_path)
    data = level_nbt["Data"]
    layout = detect_save_layout(save_dir)

    def _set(compound, key, value, tag_cls):
        """设置标签值；缺失时按给定类型创建。"""
        if key in compound.keys():
            compound[key].value = value
        else:
            compound[key] = tag_cls(name=key, value=value)

    for key, value in settings.items():
        if key == "Difficulty":
            if layout == LAYOUT_NEW or "difficulty_settings" in data.keys():
                # 新版：difficulty_settings/difficulty 为字符串
                if "difficulty_settings" not in data.keys():
                    data["difficulty_settings"] = TAG_Compound(
                        name="difficulty_settings")
                _set(data["difficulty_settings"], "difficulty",
                     DIFFICULTY_INT_TO_STR.get(int(value), "normal"), TAG_String)
            else:
                _set(data, "Difficulty", int(value), TAG_Byte)
        elif key == "DifficultyLocked":
            locked = 1 if value else 0
            if layout == LAYOUT_NEW or "difficulty_settings" in data.keys():
                if "difficulty_settings" not in data.keys():
                    data["difficulty_settings"] = TAG_Compound(
                        name="difficulty_settings")
                _set(data["difficulty_settings"], "locked", locked, TAG_Byte)
            else:
                _set(data, "DifficultyLocked", locked, TAG_Byte)
        elif key == "LevelName":
            _set(data, "LevelName", str(value), TAG_String)
        elif key == "allowCommands":
            _set(data, "allowCommands", 1 if value else 0, TAG_Byte)
        elif key == "GameType":
            _set(data, "GameType", int(value), TAG_Int)
        else:
            raise ValueError(f"不支持的世界参数字段：{key}")

    save_nbt(level_nbt, level_path, compressed)


# ---------------------------------------------------------------------------
# 玩家参数编辑（playerdata/<uuid>.dat，房主同步 level.dat）
# ---------------------------------------------------------------------------

# 可编辑玩家字段 → 期望的 NBT 标签类型名（用于标签缺失时重建）
PLAYER_FIELD_TYPES = {
    "playerGameType": "int",
    "Health": "float",
    "foodLevel": "int",
    "foodSaturationLevel": "float",
    "XpLevel": "int",
    "XpP": "float",
    "XpTotal": "int",
    "Score": "int",
}


def xp_total_for_level(level: int) -> int:
    """按原版公式计算到达指定经验等级所需的累计经验值。

    Minecraft Wiki 经验公式：
      level <= 16:  level^2 + 6*level
      17..31:       2.5*level^2 - 40.5*level + 360
      level >= 32:  4.5*level^2 - 162.5*level + 2220
    """
    if level <= 16:
        return level * level + 6 * level
    if level <= 31:
        return int(2.5 * level * level - 40.5 * level + 360)
    return int(4.5 * level * level - 162.5 * level + 2220)


def _set_player_field(compound, key: str, value) -> None:
    """设置复合标签中的字段值；标签缺失时按期望类型重建。

    按 PLAYER_FIELD_TYPES 声明的类型强制转换（int 字段收到 18.0 这类
    浮点值时转回 int），保证 TAG_Int 的 struct 打包不出错。
    """
    from nbt.nbt import TAG_Float, TAG_Int
    is_int = PLAYER_FIELD_TYPES[key] == "int"
    value = int(round(value)) if is_int else float(value)
    if key in compound.keys():
        compound[key].value = value
    else:
        tag_cls = TAG_Int if is_int else TAG_Float
        compound[key] = tag_cls(name=key, value=value)


def _apply_player_changes(compound, changes: dict) -> None:
    """把参数字典应用到玩家 NBT 复合标签。

    修改 XpLevel 时按原版公式同步重算 XpTotal/XpP/Score，
    避免三者不一致导致游戏内经验显示异常。
    """
    changes = dict(changes)
    if "XpLevel" in changes:
        level = int(changes["XpLevel"])
        changes.setdefault("XpTotal", xp_total_for_level(level))
        changes.setdefault("XpP", 0.0)
        changes.setdefault("Score", changes["XpTotal"])
    for key, value in changes.items():
        if key not in PLAYER_FIELD_TYPES:
            raise ValueError(f"不支持的玩家字段：{key}")
        _set_player_field(compound, key, value)


def edit_player_data(save_dir: str, uuid: str, changes: dict) -> bool:
    """修改玩家参数：写入玩家数据文件（布局感知路径）。

    仅旧版存档需要双写：若该玩家正是 level.dat 中记录的房主且
    Data/Player 复合标签存在，同步修改其中对应标签。
    新版房主数据就在 players/data 文件中（singleplayer_uuid 仅是标记），
    无需双写。返回是否同时修改了 level.dat。
    """
    uuid = uuid_dashed(uuid)
    layout = detect_save_layout(save_dir)
    player_path = playerdata_path(save_dir, uuid, layout)
    player_nbt, player_compressed = load_nbt(player_path)
    _apply_player_changes(player_nbt, changes)
    save_nbt(player_nbt, player_path, player_compressed)

    also_level = False
    if layout == LAYOUT_OLD and detect_host_uuid(save_dir) == uuid:
        level_path = os.path.join(save_dir, "level.dat")
        level_nbt, level_compressed = load_nbt(level_path)
        data = level_nbt["Data"]
        if "Player" in data.keys():
            _apply_player_changes(data["Player"], changes)
            save_nbt(level_nbt, level_path, level_compressed)
            also_level = True
    return also_level


def read_player_fields(save_dir: str, uuid: str) -> dict:
    """读取玩家当前参数值（用于编辑弹窗回显，布局感知路径）。"""
    player_path = playerdata_path(save_dir, uuid)
    player_nbt, _ = load_nbt(player_path)
    values = {}
    for key in PLAYER_FIELD_TYPES:
        if key in player_nbt.keys():
            values[key] = player_nbt[key].value
    return values
