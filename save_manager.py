# -*- coding: utf-8 -*-
"""save_manager.py — 存档加载与文件扫描。

负责：
  1. 加载存档目录，从 playerdata 文件夹的文件名提取所有玩家 UUID
  2. 在存档中递归搜索文件名包含指定 UUID 的 .dat/.nbt/.snbt/.json 文件
  3. 维护玩家条目的显示状态（名称、头像），供 UI 绑定
"""

import os
import re

from nbt_ops import UUID_RE, uuid_dashed, uuid_undashed

# 参与 UUID 迁移的文件扩展名
UUID_FILE_EXTS = (".dat", ".nbt", ".snbt", ".json")


class PlayerEntry:
    """一名玩家的显示状态。名称与头像先为占位值，API 返回后更新。"""

    def __init__(self, uuid: str):
        self.uuid = uuid_dashed(uuid)          # 标准带横杠小写形式
        self.name = "离线玩家"                  # 默认离线名称，API 成功后覆盖
        self.avatar_png = None                 # PNG 字节，None 表示使用史蒂夫兜底
        self.online = False                    # 是否成功从 API 获取到信息

    def display_name(self) -> str:
        return self.name if self.online else "离线玩家"


class SaveManager:
    """当前打开存档的管理器。"""

    def __init__(self):
        self.save_dir = None          # 存档根目录路径
        self.players = []             # list[PlayerEntry]

    # ------------------------------------------------------------------
    def load(self, save_dir: str) -> None:
        """加载存档：校验目录结构并扫描玩家 UUID。

        校验 level.dat 存在（确认是有效存档），然后从 playerdata/*.dat
        的文件名中提取 UUID（忽略 _old 备份文件）。
        """
        save_dir = os.path.abspath(save_dir)
        if not os.path.isfile(os.path.join(save_dir, "level.dat")):
            raise ValueError("所选目录中没有 level.dat，不是有效的 Minecraft 存档")

        self.save_dir = save_dir
        self.players = []

        playerdata_dir = os.path.join(save_dir, "playerdata")
        if os.path.isdir(playerdata_dir):
            seen = set()
            for fname in os.listdir(playerdata_dir):
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
        """返回指定玩家 playerdata 主文件路径。"""
        return os.path.join(self.save_dir, "playerdata",
                            uuid_dashed(uuid) + ".dat")

    # ------------------------------------------------------------------
    def find_uuid_files(self, uuid: str):
        """递归搜索存档中文件名包含目标 UUID 的 .dat/.nbt/.snbt/.json 文件。

        返回绝对路径列表。文件名匹配同时考虑带横杠与无横杠两种形式，
        大小写不敏感。
        """
        dashed = uuid_dashed(uuid)
        undashed = uuid_undashed(uuid)
        results = []
        for root, _dirs, files in os.walk(self.save_dir):
            for fname in files:
                lower = fname.lower()
                if dashed in lower or undashed in lower:
                    if lower.endswith(UUID_FILE_EXTS):
                        results.append(os.path.join(root, fname))
        return sorted(results)
