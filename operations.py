# -*- coding: utf-8 -*-
"""operations.py — 待操作队列与执行引擎。

用户在 UI 上确认的操作（修改房主 / UUID 迁移）先记录为待操作，
并即时反映到左侧玩家列表的显示状态（纯内存，不碰文件）。
只有菜单中选择"保存全部修改到存档 / 另存为修改存档"时才真正执行写盘。

撤销/重做通过操作列表 + 游标实现：
  ops = [op0, op1, op2, ...]，cursor 指向已生效操作的数量，
  撤销 cursor-1、重做 cursor+1、新增操作截断 cursor 之后的重做历史。
"""

import os
import shutil
import time

from nbt_ops import (
    edit_player_data,
    playerdata_path,
    replace_uuid_in_nbt_file,
    replace_uuid_in_text_file,
    set_host_in_level,
    uuid_dashed,
    uuid_undashed,
    write_world_settings,
)
from save_manager import find_uuid_files

# 交换 UUID 时使用的临时中转 UUID（合法十六进制格式，实际存档中不会出现）
TEMP_SWAP_UUID = "deadbeef-dead-beef-dead-beefdeadbeef"

# 世界参数字段 → 中文名（用于操作描述与日志）
WORLD_FIELD_LABELS = {
    "LevelName": "存档名称",
    "Difficulty": "难度",
    "DifficultyLocked": "锁定难度",
    "allowCommands": "允许命令",
    "GameType": "默认游戏模式",
}
DIFFICULTY_NAMES = {0: "和平", 1: "简单", 2: "普通", 3: "困难"}
GAMEMODE_NAMES = {0: "生存", 1: "创造", 2: "冒险", 3: "旁观"}

# 玩家参数字段 → 中文名
PLAYER_FIELD_LABELS = {
    "playerGameType": "游戏模式",
    "Health": "生命值",
    "foodLevel": "饥饿值",
    "foodSaturationLevel": "饱和度",
    "XpLevel": "经验等级",
    "XpP": "经验进度",
    "XpTotal": "累计经验",
    "Score": "经验分数",
}


# ---------------------------------------------------------------------------
# 操作定义
# ---------------------------------------------------------------------------

class SetHostOp:
    """修改房主：将 level.dat 的 Data/Player 替换为指定玩家的 playerdata。"""

    def __init__(self, uuid: str):
        self.uuid = uuid_dashed(uuid)

    def describe(self) -> str:
        return f"修改房主为 {self.uuid}"


class MigrateUuidOp:
    """UUID 迁移：把存档中 src 的玩家数据迁移到 dst。

    执行时若 src 与 dst 均有对应文件，则自动进行交换。
    parts 限定迁移范围（playerdata/advancements/stats/other 分类集合，
    None 表示全部）。
    """

    def __init__(self, src: str, dst: str, parts=None):
        self.src = uuid_dashed(src)
        self.dst = uuid_dashed(dst)
        self.parts = frozenset(parts) if parts is not None else None

    def describe(self) -> str:
        from save_manager import ALL_PARTS, PART_LABELS
        if self.parts is None or self.parts == frozenset(ALL_PARTS):
            scope = "全部范围"
        else:
            scope = "、".join(PART_LABELS[p] for p in ALL_PARTS if p in self.parts)
        return f"UUID 迁移 {self.src} -> {self.dst}（{scope}）"


class SetWorldOp:
    """修改存档基础参数（level.dat 的 Data 标签：名称/难度/命令等）。"""

    def __init__(self, settings: dict):
        self.settings = dict(settings)

    def describe(self) -> str:
        parts = []
        for key, value in self.settings.items():
            label = WORLD_FIELD_LABELS.get(key, key)
            if key == "Difficulty":
                value = DIFFICULTY_NAMES.get(value, value)
            elif key == "GameType":
                value = GAMEMODE_NAMES.get(value, value)
            elif isinstance(value, bool):
                value = "是" if value else "否"
            parts.append(f"{label}={value}")
        return "修改存档参数：" + "，".join(parts)


class EditPlayerOp:
    """修改玩家参数（playerdata/<uuid>.dat；房主同步 level.dat）。"""

    def __init__(self, uuid: str, changes: dict):
        self.uuid = uuid_dashed(uuid)
        self.changes = dict(changes)

    def describe(self) -> str:
        parts = []
        for key, value in self.changes.items():
            label = PLAYER_FIELD_LABELS.get(key, key)
            if key == "playerGameType":
                value = GAMEMODE_NAMES.get(value, value)
            elif isinstance(value, float):
                value = round(value, 2)
            parts.append(f"{label}={value}")
        return f"修改玩家参数 {self.uuid}：" + "，".join(parts)


# ---------------------------------------------------------------------------
# 显示行：左侧玩家列表的一行状态
# ---------------------------------------------------------------------------

class DisplayRow:
    """由基础玩家数据 + 生效中的待操作推导出的显示状态。"""

    def __init__(self, uuid: str, name: str, avatar_png, online: bool):
        self.uuid = uuid
        self.name = name
        self.avatar_png = avatar_png
        self.online = online

    def display_name(self) -> str:
        return self.name if self.online else "离线玩家"


# ---------------------------------------------------------------------------
# 文件级迁移实现
# ---------------------------------------------------------------------------

def _replace_uuid_in_name(fname: str, src: str, dst: str) -> str:
    """替换文件名中的 UUID（同时处理带横杠/无横杠形式，大小写不敏感）。"""
    import re
    pattern = re.compile(
        re.escape(uuid_dashed(src)) + "|" + re.escape(uuid_undashed(src)),
        re.IGNORECASE)

    def _sub(m):
        return uuid_dashed(dst) if "-" in m.group(0) else uuid_undashed(dst)

    return pattern.sub(_sub, fname)


def _is_hex2(name: str) -> bool:
    """判断目录名是否为 2 位十六进制（模组常用 UUID 前两位做哈希子目录）。"""
    return (len(name) == 2
            and all(c in "0123456789abcdefABCDEF" for c in name))


def migrate_uuid_one_way(base_dir: str, src: str, dst: str, parts=None):
    """把 base_dir 存档中所有属于 src UUID 的文件迁移为 dst UUID。

    流程：搜索文件名含 src 的 .dat/.nbt/.snbt/.json（按 parts 范围过滤）→
    替换文件内容中的 UUID（NBT 树 / 文本）→ 重命名文件；若文件位于以 src
    前两位十六进制命名的哈希目录中，一并重命名该目录。返回操作日志。
    """
    src_u, dst_u = uuid_undashed(src), uuid_undashed(dst)
    log = []

    files = find_uuid_files(base_dir, src, parts)
    if not files:
        log.append(f"未找到文件名包含 {uuid_dashed(src)} 的文件（所选范围内），跳过")
        return log

    # 按目录分组：哈希目录只需重命名一次，之后再处理其中的文件
    by_dir = {}
    for f in files:
        by_dir.setdefault(os.path.dirname(f), []).append(f)

    for dir_path, paths in by_dir.items():
        cur_dir = dir_path
        dir_base = os.path.basename(dir_path)

        # 处理模组哈希目录（如 counter/6f/、cobblemonplayerdata/6f/）
        if (_is_hex2(dir_base) and dir_base.lower() == src_u[:2]
                and dir_base.lower() != dst_u[:2]):
            new_dir = os.path.join(os.path.dirname(dir_path), dst_u[:2])
            if os.path.isdir(new_dir):
                # 目标哈希目录已存在（交换场景），文件并入即可
                cur_dir = new_dir
            else:
                os.rename(dir_path, new_dir)
                cur_dir = new_dir
                log.append(f"重命名目录 {dir_path} -> {new_dir}")

        for p in paths:
            fname = os.path.basename(p)
            cur_p = p if cur_dir == dir_path else os.path.join(cur_dir, fname)

            # 1) 替换文件内容中的 UUID
            ext = os.path.splitext(fname)[1].lower()
            if ext in (".dat", ".nbt"):
                count = replace_uuid_in_nbt_file(cur_p, src, dst)
            else:  # .snbt / .json 作为文本处理
                count = replace_uuid_in_text_file(cur_p, src, dst)

            # 2) 重命名文件
            new_fname = _replace_uuid_in_name(fname, src, dst)
            new_p = os.path.join(cur_dir, new_fname)
            if os.path.exists(new_p):
                raise RuntimeError(f"重命名冲突：{new_p} 已存在，迁移中止")
            os.rename(cur_p, new_p)
            log.append(f"{os.path.relpath(new_p, base_dir)}"
                       f"（内容替换 {count} 处）")

    return log


# ---------------------------------------------------------------------------
# 操作管理器
# ---------------------------------------------------------------------------

class OperationManager:
    """管理待操作队列、撤销/重做游标，并在保存时执行操作。"""

    def __init__(self, save_manager):
        self.sm = save_manager   # SaveManager，提供基础玩家数据
        self.ops = []            # 全部待操作（含被撤销但未重做的）
        self.cursor = 0          # 生效中的操作数 = ops[:cursor]

    # ---------------- 队列管理 ----------------
    def add(self, op) -> None:
        """追加一个待操作，丢弃游标之后的重做历史。"""
        self.ops = self.ops[:self.cursor] + [op]
        self.cursor += 1

    def undo(self) -> bool:
        if self.cursor > 0:
            self.cursor -= 1
            return True
        return False

    def redo(self) -> bool:
        if self.cursor < len(self.ops):
            self.cursor += 1
            return True
        return False

    def reset(self) -> None:
        self.ops.clear()
        self.cursor = 0

    def active_ops(self):
        return self.ops[:self.cursor]

    def has_pending(self) -> bool:
        return self.cursor > 0

    def clear_after_save(self) -> None:
        """保存成功后清空队列（操作已落盘）。"""
        self.reset()

    # ---------------- 显示状态推导 ----------------
    def display_rows(self):
        """根据基础玩家列表 + 生效中的操作，推导左侧列表应显示的状态。"""
        rows = [DisplayRow(e.uuid, e.name, e.avatar_png, e.online)
                for e in self.sm.players]
        for op in self.active_ops():
            if isinstance(op, MigrateUuidOp):
                self._apply_migrate_display(rows, op)
        return rows

    def display_host_uuid(self):
        """当前显示状态下的房主 UUID（最近一次生效的 SetHostOp），无则 None。"""
        host = None
        for op in self.active_ops():
            if isinstance(op, SetHostOp):
                host = op.uuid
        return host

    @staticmethod
    def _apply_migrate_display(rows, op: MigrateUuidOp) -> None:
        """在显示行上应用一次迁移：src 与 dst 均存在则交换，否则直接改名。"""
        src_row = next((r for r in rows if r.uuid == op.src), None)
        dst_row = next((r for r in rows if r.uuid == op.dst), None)
        if src_row and dst_row:
            src_row.uuid, dst_row.uuid = dst_row.uuid, src_row.uuid
        elif src_row:
            src_row.uuid = op.dst

    # ---------------- 显示 uuid 与文件 uuid 的映射 ----------------
    def _display_map(self, upto: int = None):
        """构建 文件uuid → 显示uuid 的正向映射。

        以基础玩家列表（文件中的真实 uuid）为起点，按顺序应用
        ops[:upto]（默认全部生效操作）中的迁移，与 _apply_migrate_display
        的交换/改名语义保持一致。
        """
        ops = self.ops[:self.cursor] if upto is None else self.ops[:upto]
        m = {e.uuid: e.uuid for e in self.sm.players}
        for op in ops:
            if isinstance(op, MigrateUuidOp):
                srcs = [k for k, v in m.items() if v == op.src]
                dsts = [k for k, v in m.items() if v == op.dst]
                if srcs and dsts:
                    m[srcs[0]], m[dsts[0]] = m[dsts[0]], m[srcs[0]]
                elif srcs:
                    m[srcs[0]] = op.dst
        return m

    def file_uuid_for_display(self, display_uuid: str) -> str:
        """显示 uuid → 文件中当前的真实 uuid。

        待保存的迁移只改显示不改文件，读取玩家数据等文件操作
        必须用本方法换算回文件 uuid。找不到映射时原样返回。
        """
        for file_uuid, disp in self._display_map().items():
            if disp == display_uuid:
                return file_uuid
        return display_uuid

    def file_uuid_for_op(self, op_index: int, recorded_display_uuid: str) -> str:
        """某待操作确认时记录的显示 uuid → 文件 uuid。

        按该操作入队时的队列前缀（ops[:op_index]）做映射，
        用于把历史操作与当前显示行在文件空间中对齐。
        """
        for file_uuid, disp in self._display_map(op_index).items():
            if disp == recorded_display_uuid:
                return file_uuid
        return recorded_display_uuid

    # ---------------- 执行引擎 ----------------
    def execute_on(self, target_dir: str):
        """按顺序把生效中的操作应用到 target_dir，返回完整日志。"""
        log = []
        for op in self.active_ops():
            log.append(f"== {op.describe()} ==")
            if isinstance(op, SetHostOp):
                p_path = playerdata_path(target_dir, op.uuid)
                if not os.path.isfile(p_path):
                    raise RuntimeError(
                        f"找不到玩家数据 {p_path}，无法修改房主")
                # 按存档布局自动处理：旧版克隆到 Data/Player（缺失则创建），
                # 新版写入 Data/singleplayer_uuid（缺失则创建）
                set_host_in_level(target_dir, op.uuid)
                log.append(f"已将房主设为 {op.uuid}（按存档版本写入 level.dat）")
            elif isinstance(op, MigrateUuidOp):
                log.extend(self._execute_migrate(target_dir, op))
            elif isinstance(op, SetWorldOp):
                write_world_settings(target_dir, op.settings)
                log.append("已写入 level.dat 的 Data 标签")
            elif isinstance(op, EditPlayerOp):
                p_path = playerdata_path(target_dir, op.uuid)
                if not os.path.isfile(p_path):
                    raise RuntimeError(
                        f"找不到玩家数据 {p_path}，无法修改玩家参数")
                also_level = edit_player_data(target_dir, op.uuid, op.changes)
                log.append(f"已修改 {os.path.relpath(p_path, target_dir)}")
                if also_level:
                    log.append("该玩家是房主，已同步修改 level.dat 的 Data/Player")
        return log

    def _execute_migrate(self, target_dir: str, op: MigrateUuidOp):
        """执行 UUID 迁移；若两个 UUID 的文件都存在则通过临时 UUID 交换。"""
        src_files = find_uuid_files(target_dir, op.src, op.parts)
        dst_files = find_uuid_files(target_dir, op.dst, op.parts)
        log = []

        if src_files and dst_files:
            # 交换：src -> 临时，dst -> src，临时 -> dst
            log.append(f"检测到双方均有存档文件（{len(src_files)} / {len(dst_files)} 个），执行交换")
            log += migrate_uuid_one_way(target_dir, op.src, TEMP_SWAP_UUID, op.parts)
            log += migrate_uuid_one_way(target_dir, op.dst, op.src, op.parts)
            log += migrate_uuid_one_way(target_dir, TEMP_SWAP_UUID, op.dst, op.parts)
        elif src_files:
            log.append(f"仅源 UUID 有存档文件（{len(src_files)} 个），执行单向迁移")
            log += migrate_uuid_one_way(target_dir, op.src, op.dst, op.parts)
        else:
            log.append(f"警告：存档中所选范围内未找到 {op.src} 的文件，此操作未执行")
        return log

    # ---------------- 备份 / 另存为 ----------------
    def backup_save(self, backups_root: str):
        """把当前存档完整复制到 backups_root 下带时间戳的目录，返回路径。"""
        name = os.path.basename(self.sm.save_dir)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(backups_root, f"{name}_{stamp}")
        shutil.copytree(self.sm.save_dir, dest)
        return dest

    def save_as(self, dest_dir: str):
        """把存档完整复制到 dest_dir，并在副本上执行全部待操作，返回日志。"""
        if os.path.exists(dest_dir):
            if os.listdir(dest_dir):
                raise RuntimeError("目标目录非空，请换一个目录")
        else:
            os.makedirs(dest_dir)
        target = os.path.join(dest_dir, os.path.basename(self.sm.save_dir))
        shutil.copytree(self.sm.save_dir, target)
        return self.execute_on(target)
