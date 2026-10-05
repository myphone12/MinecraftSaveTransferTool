# -*- coding: utf-8 -*-
"""player_dialog.py — 玩家参数编辑弹窗与游戏风格可点击状态条。

状态条使用 res/ 中的心形与鸡腿图标（bg/full/half 三态），
点击图标右半设为整颗值、左半设为半颗值（数值以"半点"为单位，0~20）。
"""

import os
import tkinter as tk
from tkinter import messagebox, ttk

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
RES_DIR = os.path.join(PROJECT_ROOT, "res")

ICON_ZOOM = 3           # 9x9 图标放大 3 倍显示（27x27）
MAX_VALUE = 20          # 生命值/饥饿值上限（半点单位）

# 图标缓存：(名称, 缩放) -> PhotoImage（保持引用防止被垃圾回收）
_IMG_CACHE = {}


def _load_icon(name: str) -> tk.PhotoImage:
    key = (name, ICON_ZOOM)
    if key not in _IMG_CACHE:
        base = tk.PhotoImage(file=os.path.join(RES_DIR, f"{name}.png"))
        _IMG_CACHE[key] = base.zoom(ICON_ZOOM, ICON_ZOOM)
    return _IMG_CACHE[key]


GAME_MODES = ["生存", "创造", "冒险", "旁观"]


class IconStatusBar(ttk.Frame):
    """游戏风格的可点击图标状态条（10 颗心 / 10 个鸡腿）。

    value 以半点为单位（0~20），与 Health / foodLevel 的取值一致。
    点击图标右半 = 整颗（2n），左半 = 半颗（2n-1）。
    """

    def __init__(self, master, kind: str, value: int = MAX_VALUE,
                 on_change=None):
        super().__init__(master)
        self.kind = kind                    # 'heart' 或 'hunger'
        self.on_change = on_change
        self._value = max(0, min(MAX_VALUE, int(round(value))))
        self.slot_size = 9 * ICON_ZOOM

        self.slots = []
        for i in range(10):
            cv = tk.Canvas(self, width=self.slot_size, height=self.slot_size,
                           highlightthickness=0, bd=0)
            cv.grid(row=0, column=i, padx=1)
            # 背景图标常驻，状态图标按当前值重绘
            cv.create_image(0, 0, anchor="nw", image=_load_icon(f"{kind}_bg"))
            cv.bind("<Button-1>", lambda e, idx=i: self._on_click(idx, e))
            self.slots.append(cv)

        self.num_var = tk.StringVar()
        ttk.Label(self, textvariable=self.num_var, width=9,
                  font=("Consolas", 10, "bold")).grid(row=0, column=10,
                                                      padx=(6, 0))
        self._redraw()

    @property
    def value(self) -> int:
        return self._value

    def set_value(self, value: int):
        self._value = max(0, min(MAX_VALUE, int(round(value))))
        self._redraw()

    def _redraw(self):
        for i, cv in enumerate(self.slots):
            cv.delete("state")
            if self._value >= 2 * (i + 1):
                icon = _load_icon(f"{self.kind}_full")
            elif self._value == 2 * i + 1:
                icon = _load_icon(f"{self.kind}_half")
            else:
                continue
            cv.create_image(0, 0, anchor="nw", image=icon, tags="state")
        self.num_var.set(f"{self._value / 2:g} / {MAX_VALUE // 2}")

    def _on_click(self, index: int, event):
        # 图标左半 → 半颗；右半 → 整颗
        half = event.x < self.slot_size // 2
        self.set_value(2 * index + 1 if half else 2 * (index + 1))
        if self.on_change:
            self.on_change(self._value)


class PlayerEditDialog(tk.Toplevel):
    """玩家参数编辑弹窗。确认时通过 on_confirm(changes) 回传修改的字段。"""

    def __init__(self, master, uuid: str, name: str, fields: dict,
                 on_confirm):
        super().__init__(master)
        self.title(f"编辑玩家参数 — {name} ({uuid})")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.fields = fields          # 文件中的当前值
        self.on_confirm = on_confirm
        self.uuid = uuid

        body = ttk.Frame(self, padding=14)
        body.pack(fill=tk.BOTH, expand=True)

        # ---- 游戏模式 ----
        ttk.Label(body, text="游戏模式：").grid(row=0, column=0, sticky="w",
                                                pady=4)
        self.mode_combo = ttk.Combobox(body, values=GAME_MODES,
                                       state="readonly", width=10)
        mode = int(fields.get("playerGameType", 0))
        self.mode_combo.current(mode if 0 <= mode < 4 else 0)
        self.mode_combo.grid(row=0, column=1, sticky="w", pady=4)

        # ---- 生命值（可点击心形条） ----
        ttk.Label(body, text="生命值：").grid(row=1, column=0, sticky="nw",
                                              pady=6)
        self.health_bar = IconStatusBar(body, "heart",
                                        int(round(fields.get("Health", 20.0))))
        self.health_bar.grid(row=1, column=1, sticky="w", pady=6)

        # ---- 饥饿值（可点击鸡腿条） ----
        ttk.Label(body, text="饥饿值：").grid(row=2, column=0, sticky="nw",
                                              pady=6)
        self.hunger_bar = IconStatusBar(body, "hunger",
                                        int(fields.get("foodLevel", 20)))
        self.hunger_bar.grid(row=2, column=1, sticky="w", pady=6)

        # ---- 饱和度 ----
        ttk.Label(body, text="饱和度：").grid(row=3, column=0, sticky="w",
                                              pady=4)
        self.sat_spin = ttk.Spinbox(body, from_=0.0, to=20.0, increment=0.5,
                                    width=8)
        self.sat_spin.set(float(fields.get("foodSaturationLevel", 0.0)))
        self.sat_spin.grid(row=3, column=1, sticky="w", pady=4)

        # ---- 经验等级 ----
        ttk.Label(body, text="经验等级：").grid(row=4, column=0, sticky="w",
                                                pady=4)
        self.xp_spin = ttk.Spinbox(body, from_=0, to=2000, increment=1,
                                   width=8)
        self.xp_spin.set(int(fields.get("XpLevel", 0)))
        self.xp_spin.grid(row=4, column=1, sticky="w", pady=4)
        ttk.Label(body, foreground="#666",
                  text="提示：点击图标左半设半颗、右半设整颗；"
                       "保存时经验累计值将按原版公式自动重算。").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # ---- 按钮 ----
        btns = ttk.Frame(body)
        btns.grid(row=6, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btns, text="确认", command=self._on_ok).pack(
            side=tk.LEFT, padx=8)
        ttk.Button(btns, text="取消", command=self.destroy).pack(
            side=tk.LEFT, padx=8)

    def _on_ok(self):
        # 收集与文件当前值不同的字段
        changes = {}
        mode = self.mode_combo.current()
        if mode != int(self.fields.get("playerGameType", 0)):
            changes["playerGameType"] = mode

        health = self.health_bar.value / 2.0     # 半点 → 生命值
        if abs(health - float(self.fields.get("Health", 20.0))) > 1e-6:
            changes["Health"] = health

        food = self.hunger_bar.value
        if food != int(self.fields.get("foodLevel", 20)):
            changes["foodLevel"] = food

        try:
            sat = float(self.sat_spin.get())
        except ValueError:
            messagebox.showwarning("数值无效", "饱和度必须是数字。", parent=self)
            return
        if abs(sat - float(self.fields.get("foodSaturationLevel", 0.0))) > 1e-6:
            changes["foodSaturationLevel"] = sat

        try:
            xp = int(self.xp_spin.get())
        except ValueError:
            messagebox.showwarning("数值无效", "经验等级必须是整数。", parent=self)
            return
        if xp != int(self.fields.get("XpLevel", 0)):
            changes["XpLevel"] = xp

        if not changes:
            messagebox.showinfo("无修改", "没有检测到任何参数变化。", parent=self)
            return

        self.on_confirm(self.uuid, changes)
        self.destroy()
