# -*- coding: utf-8 -*-
"""uuid_gen.py — 各启动器的离线 UUID 生成算法。

还原以下算法（与启动器输出逐位一致）：
  - PCL2 传统算法（McLoginLegacyUuid）：名字长度 + 稳定哈希拼接后
    替换第 13 位为 '3'、第 17 位为 '9'（大写十六进制）
  - PCL2 离线皮肤算法（McLoginLegacyUuidWithCustomSkin）：在传统算法
    基础上递增末 5 位十六进制，直到 UUID 的"皮肤性别"符合要求
  - PCL2-CE/HMCL/BakaXL/Bukkit 标准算法：MD5("OfflinePlayer:"+名字)
    设置 v3 版本位与变体位，等价于 Java UUID.nameUUIDFromBytes
  - PCL2-CE"传统"算法：与 PCL2 传统算法完全一致（GetHash/StrFill 同实现）
"""

import hashlib

MASK64 = 0xFFFFFFFFFFFFFFFF
HASH_XOR_CONST = 0xA98F501BC684032F


def _utf16_units(s: str):
    """按 .NET/VB 语义把字符串拆为 UTF-16 代码单元序列。

    C# 的 foreach char 与 VB 的 String.Length 都以 UTF-16 代码单元为准。
    Minecraft 玩家名均为 ASCII，此处保证对任意输入行为一致。
    """
    raw = s.encode("utf-16-le")
    return [int.from_bytes(raw[i:i + 2], "little")
            for i in range(0, len(raw), 2)]


def get_stable_hash(s: str) -> int:
    """PCL 的 GetStableHashCode / PCL2-CE 的 GetHash（二者实现相同）。

    64 位无符号 djb2 变体：result = (result << 5) ^ result ^ char，
    初始值 5381，最终异或常量 0xA98F501BC684032F。
    """
    result = 5381
    for unit in _utf16_units(s):
        result = ((result << 5) ^ result ^ unit) & MASK64
    return result ^ HASH_XOR_CONST


def _fill16(s: str) -> str:
    """EnsureLength / StrFill：左侧补 '0' 到 16 位，超长则截断为前 16 位。"""
    return s[:16] if len(s) > 16 else s.rjust(16, "0")


def pcl2_legacy_uuid(name: str) -> str:
    """PCL2 传统离线 UUID（大写、无横杠 32 位十六进制）。

    FullUuid = 名字长度的hex(左补0到16位) + 稳定哈希的hex(左补0到16位)，
    然后取 [0:12] + "3" + [13:16] + "9" + [17:32]。
    """
    units = _utf16_units(name)
    full = (_fill16(format(len(units), "X"))
            + _fill16(format(get_stable_hash(name), "X")))
    return full[0:12] + "3" + full[13:16] + "9" + full[17:32]


def mc_skin_sex(uuid32: str) -> str:
    """PCL2 的 McSkinSex：判断 UUID 对应的默认皮肤模型。

    取第 7/15/23/31 位（0 起）十六进制数字异或，结果为奇数 → Alex，
    偶数 → Steve；长度不是 32 一律视为 Steve。
    """
    if len(uuid32) != 32:
        return "Steve"
    a = int(uuid32[7], 16)
    b = int(uuid32[15], 16)
    c = int(uuid32[23], 16)
    d = int(uuid32[31], 16)
    return "Alex" if (a ^ b ^ c ^ d) % 2 else "Steve"


def pcl2_skin_uuid(name: str, skin: str) -> str:
    """PCL2 带离线皮肤设置的 UUID。

    skin: 'standard'（默认，即传统算法）/ 'steve' / 'alex'。
    Steve/Alex 模式：循环递增末 5 位十六进制（遇 FFFFF 先归零为 00000
    再加一），直到 McSkinSex 与目标一致，与 PCL2 的 VB 实现逐位一致。
    """
    uuid = pcl2_legacy_uuid(name)
    if skin == "standard":
        return uuid
    target = "Steve" if skin == "steve" else "Alex"
    while mc_skin_sex(uuid) != target:
        if uuid.endswith("FFFFF"):
            uuid = uuid[:27] + "00000"
        uuid = uuid[:27] + format(int(uuid[27:], 16) + 1, "X").rjust(5, "0")
    return uuid


def pclce_standard_uuid(name: str) -> str:
    """PCL2-CE/HMCL/BakaXL/Bukkit 标准离线 UUID（小写、无横杠）。

    MD5("OfflinePlayer:" + 名字) 后设置版本位（hash[6] → v3）与
    变体位（hash[8] → RFC 4122），按大端序输出十六进制，
    等价于 Java 的 UUID.nameUUIDFromBytes。
    """
    digest = bytearray(
        hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30   # 版本 3
    digest[8] = (digest[8] & 0x3F) | 0x80   # RFC 4122 变体
    return digest.hex()
