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
# 修改房主：克隆 playerdata 到 level.dat 的 Data/Player
# ---------------------------------------------------------------------------

def clone_player_to_level(save_dir: str, target_uuid: str) -> None:
    """将目标玩家的 playerdata 内容整体替换 level.dat 中 Data/Player。

    单人存档的房主玩家数据保存在 level.dat 的 Data/Player 复合标签中，
    因此把目标玩家 playerdata/<uuid>.dat 的全部内容深拷贝过去即可完成房主转移，
    背包、属性、坐标等复合列表均无丢失。
    """
    player_path = os.path.join(save_dir, "playerdata",
                               uuid_dashed(target_uuid) + ".dat")
    level_path = os.path.join(save_dir, "level.dat")

    player_nbt = deep_copy_nbt(load_nbt(player_path)[0])
    level_nbt, level_compressed = load_nbt(level_path)

    if "Data" not in level_nbt:
        raise ValueError("level.dat 中缺少 Data 标签，可能不是有效的存档")
    data = level_nbt["Data"]
    if "Player" not in data:
        raise ValueError("level.dat 的 Data 中缺少 Player 标签")

    player_compound = data["Player"]
    # 清空原有 Player 的所有子标签，再写入目标玩家的全部标签
    player_compound.clear()
    for key in list(player_nbt.keys()):
        tag = player_nbt[key]
        tag.name = key
        player_compound[key] = tag

    save_nbt(level_nbt, level_path, level_compressed)
