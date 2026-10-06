# -*- coding: utf-8 -*-
"""save_manager.py — 存档加载与文件扫描。

负责：
  1. 加载存档目录，从 playerdata 文件夹的文件名提取所有玩家 UUID
  2. 在存档中递归搜索文件名包含指定 UUID 的 .dat/.nbt/.snbt/.json 文件
  3. 维护玩家条目的显示状态（名称、头像），供 UI 绑定
"""

import os
import re

from nbt_ops import (
    UUID_RE,
    detect_host_uuid,
    detect_save_layout,
    playerdata_dir,
    playerdata_path,
    uuid_dashed,
    uuid_undashed,
)

# 参与 UUID 迁移的文件扩展名
UUID_FILE_EXTS = (".dat", ".nbt", ".snbt", ".json")

# 迁移范围分类：按文件相对存档根目录的文件夹划分
# 旧版为一级目录（playerdata/advancements/stats），
# 新版为 players/ 下的二级目录（players/data|advancements|stats）
PART_PLAYERDATA = "playerdata"      # 玩家数据
PART_ADVANCEMENTS = "advancements"  # 进度数据
PART_STATS = "stats"                # 统计数据
PART_OTHER = "other"                # 其他（mod 数据）
ALL_PARTS = (PART_PLAYERDATA, PART_ADVANCEMENTS, PART_STATS, PART_OTHER)

# 分类键 → UI 显示名
PART_LABELS = {
    PART_PLAYERDATA: "玩家数据",
    PART_ADVANCEMENTS: "进度数据",
    PART_STATS: "统计数据",
    PART_OTHER: "其他(mod数据)",
}

# 新版存档 players/ 下二级目录 → 分类
_NEW_SUB_DIRS = {
    "data": PART_PLAYERDATA,
    "advancements": PART_ADVANCEMENTS,
    "stats": PART_STATS,
}


def classify_path(save_dir: str, path: str) -> str:
    """返回文件所属的迁移范围分类（兼容新旧两版目录结构）。

    旧版：playerdata/、advancements/、stats/ 一级目录；
    新版：players/data、players/advancements、players/stats 二级目录；
    其余一律归为其他（mod 数据）。
    """
    rel = os.path.relpath(path, save_dir)
    parts = [p.lower() for p in rel.split(os.sep)]
    top = parts[0]
    if top in (PART_PLAYERDATA, PART_ADVANCEMENTS, PART_STATS):
        return top
    if top == "players" and len(parts) > 1:
        return _NEW_SUB_DIRS.get(parts[1], PART_OTHER)
    return PART_OTHER


class PlayerEntry:
    """一名玩家的显示状态。名称与头像先为占位值，API 返回后更新。"""

    def __init__(self, uuid: str):
        self.uuid = uuid_dashed(uuid)          # 标准带横杠小写形式
        self.name = "离线玩家"                  # 默认离线名称，API 成功后覆盖
        self.avatar_png = None                 # PNG 字节，None 表示使用史蒂夫兜底
        self.online = False                    # 是否成功从 API 获取到信息

    def display_name(self) -> str:
        return self.name if self.online else "离线玩家"


def find_uuid_files(save_dir: str, uuid: str, parts=None):
    """递归搜索存档目录中文件名包含目标 UUID 的 .dat/.nbt/.snbt/.json 文件。

    返回绝对路径列表。文件名匹配同时考虑带横杠与无横杠两种形式，
    大小写不敏感。parts 为迁移范围分类集合（None 表示不过滤）。
    模块级函数以便对"另存为"的副本目录复用。
    """
    dashed = uuid_dashed(uuid)
    undashed = uuid_undashed(uuid)
    results = []
    for root, _dirs, files in os.walk(save_dir):
        for fname in files:
            lower = fname.lower()
            if dashed in lower or undashed in lower:
                if lower.endswith(UUID_FILE_EXTS):
                    path = os.path.join(root, fname)
                    if parts is None or classify_path(save_dir, path) in parts:
                        results.append(path)
    return sorted(results)


class SaveManager:
    """当前打开存档的管理器。"""

    def __init__(self):
        self.save_dir = None          # 存档根目录路径
        self.players = []             # list[PlayerEntry]
        self.host_uuid = None         # 当前 level.dat 中检测到的房主 UUID
        self.layout = None            # 存档布局（'old' / 'new'）

    # ------------------------------------------------------------------
    def load(self, save_dir: str) -> None:
        """加载存档：校验目录结构、检测布局并扫描玩家 UUID。

        校验 level.dat 存在（确认是有效存档），检测新版/旧版布局，
        然后从玩家数据目录（旧版 playerdata/、新版 players/data/）
        的文件名中提取 UUID（忽略 _old 备份文件）。
        """
        save_dir = os.path.abspath(save_dir)
        if not os.path.isfile(os.path.join(save_dir, "level.dat")):
            raise ValueError("所选目录中没有 level.dat，不是有效的 Minecraft 存档")

        self.save_dir = save_dir
        self.players = []
        self.layout = detect_save_layout(save_dir)
        # 旧版从 Data/Player/UUID、新版从 Data/singleplayer_uuid 检测房主；
        # 服务器存档两者皆无 → None
        self.host_uuid = detect_host_uuid(save_dir)

        pd_dir = playerdata_dir(save_dir, self.layout)
        if os.path.isdir(pd_dir):
            seen = set()
            for fname in os.listdir(pd_dir):
                stem, ext = os.path.splitext(fname)
                # 只处理 .dat 主文件（.dat_old 的扩展名是 .dat_old，天然被排除）
                if ext.lower() != ".dat":
                    continue
                # 文件名即 UUID，校验格式防止误读其他文件
                if UUID_RE.fullmatch(stem) and stem.lower() not in seen:
                    seen.add(stem.lower())
                    self.players.append(PlayerEntry(stem))

    # ------------------------------------------------------------------
    def is_loaded(self) -> bool:
        return self.save_dir is not None

    def get_playerdata_path(self, uuid: str) -> str:
        """返回指定玩家 playerdata 主文件路径（布局感知）。"""
        return playerdata_path(self.save_dir, uuid, self.layout)

    # ------------------------------------------------------------------
    def find_uuid_files(self, uuid: str, parts=None):
        """递归搜索存档中文件名包含目标 UUID 的文件（委托模块级函数）。"""
        return find_uuid_files(self.save_dir, uuid, parts)
