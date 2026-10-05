# -*- coding: utf-8 -*-
"""ui.py — tkinter 主界面。

布局：
  顶部菜单栏：文件（选择存档/保存全部修改到存档/备份存档/另存为修改存档）
              操作（撤销上次修改/重做修改/重置全部修改）
  左侧：当前存档玩家列表（头像 + 玩家名 + UUID）
  右上：修改房主（下拉选择玩家 + 确认）
  右下：UUID 迁移/交换（两个下拉 + 确认）
  底部：状态栏

所有确认操作先进入待操作队列并即时刷新左侧显示，
菜单中选择保存后才真正写入文件。
"""

import base64
import os
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import player_api
from nbt_ops import UUID_RE, uuid_dashed
from operations import MigrateUuidOp, OperationManager, SetHostOp
from save_manager import SaveManager

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
AVATAR_SIZE = 32      # 头像显示边长（像素）

# 史蒂夫头像 8x8 像素画配色（离线玩家兜底，程序内绘制、无需外部资源）
STEVE_COLORS = {
    "H": "#412d1d",   # 头发
    "S": "#c68b5e",   # 皮肤
    "D": "#a9714b",   # 阴影（鼻子等）
    "W": "#ffffff",   # 眼白
    "P": "#4a3f9e",   # 瞳孔
    "M": "#7a4a2b",   # 嘴/胡须
}
STEVE_PIXELS = [
    "HHHHHHHH",
    "HHHHHHHH",
    "SSSSSSSS",
    "SWPSSPWS",
    "SSSDDSSS",
    "SSSMMSSS",
    "SSMMMMSS",
    "SDSSSSDS",
]


def make_steve_image() -> tk.PhotoImage:
    """程序内绘制史蒂夫头像并放大到 AVATAR_SIZE。"""
    img = tk.PhotoImage(width=8, height=8)
    for y, row in enumerate(STEVE_PIXELS):
        for x, ch in enumerate(row):
            img.put(STEVE_COLORS[ch], (x, y, x + 1, y + 1))
    scale = AVATAR_SIZE // 8
    return img.zoom(scale, scale)


class App:
    """应用主窗口。"""

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Minecraft 存档玩家数据迁移工具")
        root.geometry("920x560")
        root.minsize(760, 460)

        self.sm = SaveManager()
        self.om = OperationManager(self.sm)
        self._fetch_pool = None          # 玩家信息获取线程池
        self._avatar_cache = {}          # uuid -> PhotoImage（避免重复解码与 GC）
        self.steve_img = make_steve_image()

        self._build_menu()
        self._build_layout()
        self._refresh_all()

    # ------------------------------------------------------------------
    # 界面搭建
    # ------------------------------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="选择存档…", command=self.on_choose_save)
        file_menu.add_separator()
        file_menu.add_command(label="保存全部修改到存档", command=self.on_save_all)
        file_menu.add_command(label="备份存档", command=self.on_backup)
        file_menu.add_command(label="另存为修改存档…", command=self.on_save_as)
        menubar.add_cascade(label="文件", menu=file_menu)

        op_menu = tk.Menu(menubar, tearoff=0)
        op_menu.add_command(label="撤销上次修改", accelerator="Ctrl+Z",
                            command=self.on_undo)
        op_menu.add_command(label="重做修改", accelerator="Ctrl+Y",
                            command=self.on_redo)
        op_menu.add_separator()
        op_menu.add_command(label="重置全部修改", command=self.on_reset)
        menubar.add_cascade(label="操作", menu=op_menu)

        self.root.config(menu=menubar)
        self.file_menu = file_menu
        self.op_menu = op_menu

        # 快捷键
        self.root.bind_all("<Control-z>", lambda e: self.on_undo())
        self.root.bind_all("<Control-y>", lambda e: self.on_redo())

    def _build_layout(self):
        # 主分栏：左侧玩家列表 | 右侧功能面板
        main = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))

        # ---------- 左侧：玩家列表（Canvas 滚动容器） ----------
        left = ttk.LabelFrame(main, text="当前存档玩家列表")
        main.add(left, weight=3)

        self.canvas = tk.Canvas(left, highlightthickness=0)
        vsb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.canvas.yview)
        self.rows_frame = ttk.Frame(self.canvas)
        self.rows_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0),
                                                       window=self.rows_frame,
                                                       anchor="nw")
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        # 内部 frame 宽度跟随 canvas，并绑定鼠标滚轮
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self.canvas_window, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # ---------- 右侧：上下两个功能面板 ----------
        right = ttk.Frame(main)
        main.add(right, weight=2)
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # 右上：修改房主
        host_frame = ttk.LabelFrame(right, text="修改存档房主")
        host_frame.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=(0, 4))
        ttk.Label(host_frame, text="选择要设为房主的玩家：").pack(
            anchor="w", padx=10, pady=(10, 2))
        self.host_combo = ttk.Combobox(host_frame, state="readonly")
        self.host_combo.pack(fill=tk.X, padx=10)
        self.host_btn = ttk.Button(host_frame, text="确认", command=self.on_set_host)
        self.host_btn.pack(pady=10)
        ttk.Label(host_frame, foreground="#666", wraplength=320, justify="left",
                  text="说明：确认后仅记录为待操作（左侧列表以 ★ 标记），"
                       "需在菜单中选择“保存全部修改到存档”才会写入 level.dat。"
                  ).pack(anchor="w", padx=10, pady=(0, 8))

        # 右下：UUID 迁移/交换
        mig_frame = ttk.LabelFrame(right, text="UUID 迁移 / 交换")
        mig_frame.grid(row=1, column=0, sticky="nsew", padx=(6, 0), pady=(4, 0))
        ttk.Label(mig_frame, text="目标 UUID（被迁移的玩家）：").pack(
            anchor="w", padx=10, pady=(10, 2))
        self.src_combo = ttk.Combobox(mig_frame, state="readonly")
        self.src_combo.pack(fill=tk.X, padx=10)
        ttk.Label(mig_frame, text="要修改成的 UUID（可从列表选择或手动输入）：").pack(
            anchor="w", padx=10, pady=(8, 2))
        self.dst_combo = ttk.Combobox(mig_frame)   # 可编辑，允许输入新 UUID
        self.dst_combo.pack(fill=tk.X, padx=10)
        self.mig_btn = ttk.Button(mig_frame, text="确认", command=self.on_migrate)
        self.mig_btn.pack(pady=10)
        ttk.Label(mig_frame, foreground="#666", wraplength=320, justify="left",
                  text="说明：搜索存档中文件名含目标 UUID 的 .dat/.nbt/.snbt/.json，"
                       "替换文件内容与文件名；若双方均有文件则自动交换。"
                  ).pack(anchor="w", padx=10, pady=(0, 8))

        # ---------- 底部状态栏 ----------
        status = ttk.Frame(self.root)
        status.pack(fill=tk.X, side=tk.BOTTOM, padx=8, pady=4)
        self.status_var = tk.StringVar(value="未选择存档")
        ttk.Label(status, textvariable=self.status_var, anchor="w").pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        self.pending_var = tk.StringVar(value="")
        ttk.Label(status, textvariable=self.pending_var, foreground="#a33",
                  anchor="e").pack(side=tk.RIGHT)

    def _on_mousewheel(self, event):
        # Windows 滚轮：delta 为正向上、为负向下
        if event.num == 4 or event.delta > 0:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:
            self.canvas.yview_scroll(1, "units")

    # ------------------------------------------------------------------
    # 刷新
    # ------------------------------------------------------------------
    def _refresh_all(self):
        self._refresh_player_list()
        self._refresh_combos()
        self._refresh_menus()
        self._refresh_pending_label()

    def _refresh_player_list(self):
        """重建左侧玩家列表。"""
        for w in self.rows_frame.winfo_children():
            w.destroy()

        loaded = self.sm.is_loaded()
        if not loaded:
            ttk.Label(self.rows_frame, foreground="#888",
                      text="尚未选择存档。\n请通过菜单 文件 → 选择存档 打开一个存档目录。"
                  ).pack(padx=20, pady=30)
            return

        rows = self.om.display_rows()
        host_uuid = self.om.display_host_uuid()
        if not rows:
            ttk.Label(self.rows_frame, foreground="#888",
                      text="该存档的 playerdata 中没有找到玩家。").pack(padx=20, pady=20)

        for row in rows:
            self._build_player_row(row, row.uuid == host_uuid)

    def _build_player_row(self, row, is_host: bool):
        """创建一行玩家显示：头像 + 名称 + UUID（+ 房主标记）。"""
        frame = ttk.Frame(self.rows_frame)
        frame.pack(fill=tk.X, padx=6, pady=3)

        img = self._get_avatar(row)
        img_label = ttk.Label(frame, image=img)
        img_label.image = img          # 保持引用防止被垃圾回收
        img_label.pack(side=tk.LEFT, padx=(0, 8))

        text = ttk.Frame(frame)
        text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        name = row.display_name() + ("  ★房主(待保存)" if is_host else "")
        ttk.Label(text, text=name, font=("Microsoft YaHei UI", 10, "bold")).pack(
            anchor="w")
        ttk.Label(text, text=row.uuid, foreground="#666",
                  font=("Consolas", 9)).pack(anchor="w")

        ttk.Separator(self.rows_frame, orient=tk.HORIZONTAL).pack(fill=tk.X)

    def _get_avatar(self, row) -> tk.PhotoImage:
        """返回玩家头像图片：有 PNG 数据则解码缓存，否则用史蒂夫兜底。"""
        if not row.avatar_png:
            return self.steve_img
        if row.uuid not in self._avatar_cache:
            try:
                img = tk.PhotoImage(data=base64.b64encode(row.avatar_png))
                # 64px 缩到 32px（tkinter 只支持整数倍缩放）
                img = img.subsample(max(1, img.width() // AVATAR_SIZE),
                                    max(1, img.height() // AVATAR_SIZE))
                self._avatar_cache[row.uuid] = img
            except tk.TclError:
                return self.steve_img
        return self._avatar_cache[row.uuid]

    def _refresh_combos(self):
        """刷新右侧两个功能面板的下拉选项（显示名 + UUID）。"""
        rows = self.om.display_rows() if self.sm.is_loaded() else []
        values = [f"{r.display_name()}  ({r.uuid})" for r in rows]
        self._combo_rows = rows

        for combo, state in ((self.host_combo, "readonly"),
                             (self.src_combo, "readonly")):
            combo["values"] = values
            combo.set("")
        self.dst_combo["values"] = values
        self.dst_combo.set("")

    def _refresh_menus(self):
        """根据存档/待操作状态启用或禁用菜单项。

        注意：entryconfigure 的索引包含分隔线。
        文件菜单：0 选择存档 | 1 分隔线 | 2 保存 | 3 备份 | 4 另存为
        操作菜单：0 撤销 | 1 重做 | 2 分隔线 | 3 重置
        """
        loaded = self.sm.is_loaded()
        pending = self.om.has_pending()
        self.file_menu.entryconfigure(2, state="normal" if loaded and pending
                                      else "disabled")
        self.file_menu.entryconfigure(3, state="normal" if loaded else "disabled")
        self.file_menu.entryconfigure(4, state="normal" if loaded else "disabled")

        has_undo = loaded and self.om.cursor > 0
        has_redo = loaded and self.om.cursor < len(self.om.ops)
        self.op_menu.entryconfigure(0, state="normal" if has_undo else "disabled")
        self.op_menu.entryconfigure(1, state="normal" if has_redo else "disabled")
        self.op_menu.entryconfigure(3, state="normal" if loaded and pending
                                    else "disabled")

        for widget in (self.host_combo, self.host_btn,
                       self.src_combo, self.dst_combo, self.mig_btn):
            widget.configure(state="normal" if loaded else "disabled")
        if loaded:
            # 恢复只读下拉的状态
            self.host_combo.configure(state="readonly")
            self.src_combo.configure(state="readonly")
        else:
            self.host_combo.configure(state="disabled")
            self.src_combo.configure(state="disabled")

    def _refresh_pending_label(self):
        ops = self.om.active_ops()
        self.pending_var.set(f"待保存操作：{len(ops)} 个" if ops else "")

    def _set_status(self, text: str):
        self.status_var.set(text)

    # ------------------------------------------------------------------
    # 菜单动作
    # ------------------------------------------------------------------
    def on_choose_save(self):
        path = filedialog.askdirectory(title="选择存档目录（含 level.dat）")
        if not path:
            return
        try:
            self.sm.load(path)
        except ValueError as e:
            messagebox.showerror("无法打开存档", str(e))
            return

        # 关闭旧的获取线程池，重置待操作与头像缓存
        if self._fetch_pool:
            self._fetch_pool.shutdown(wait=False)
        self.om.reset()
        self._avatar_cache.clear()

        self._set_status(f"已加载存档：{path}，共 {len(self.sm.players)} 名玩家，"
                         f"正在获取在线信息…")
        self._refresh_all()

        # 后台线程获取玩家名与头像，完成后调度回主线程刷新
        def on_done(_entry):
            self.root.after(0, self._on_fetch_progress)

        self._fetch_count = 0
        self._fetch_pool = player_api.fetch_all_players(self.sm.players, on_done)

    def _on_fetch_progress(self):
        self._fetch_count += 1
        total = len(self.sm.players)
        if self._fetch_count >= total:
            self._set_status(f"存档：{self.sm.save_dir}（在线信息获取完成）")
        self._refresh_player_list()
        self._refresh_combos()

    def on_save_all(self):
        if not self.om.has_pending():
            messagebox.showinfo("无待保存修改", "当前没有已确认的待操作。")
            return
        ops_desc = "\n".join("· " + op.describe() for op in self.om.active_ops())
        if not messagebox.askyesno(
                "保存全部修改到存档",
                f"即将把以下 {self.om.cursor} 个操作写入存档：\n\n{ops_desc}\n\n"
                f"存档目录：{self.sm.save_dir}\n\n建议先执行“备份存档”。是否继续？"):
            return
        try:
            log = self.om.execute_on(self.sm.save_dir)
        except Exception as e:
            messagebox.showerror("保存失败", f"执行操作时出错：\n{e}\n\n"
                                             f"存档可能已被部分修改，建议从备份恢复。")
            return
        self.om.clear_after_save()
        # 保存后重新扫描存档（UUID 可能已变化）
        try:
            players = self.sm.players
            self.sm.load(self.sm.save_dir)
            # 沿用已获取的名称/头像（UUID 相同的条目）
            old = {e.uuid: e for e in players}
            for e in self.sm.players:
                if e.uuid in old:
                    src = old[e.uuid]
                    e.name, e.online, e.avatar_png = src.name, src.online, src.avatar_png
        except ValueError:
            pass
        self._refresh_all()
        self._set_status("已保存全部修改到存档")
        self._show_log("保存完成", log)

    def on_backup(self):
        try:
            dest = self.om.backup_save(os.path.join(PROJECT_ROOT, "backups"))
        except Exception as e:
            messagebox.showerror("备份失败", str(e))
            return
        self._set_status(f"已备份存档到：{dest}")
        messagebox.showinfo("备份完成", f"存档已完整复制到：\n{dest}")

    def on_save_as(self):
        if not self.om.has_pending():
            messagebox.showinfo("无待保存修改",
                                "当前没有已确认的待操作，"
                                "另存为将只是复制一份原始存档。仍要继续吗？")
        path = filedialog.askdirectory(title="选择另存为的目标目录（将为空目录）")
        if not path:
            return
        try:
            log = self.om.save_as(path)
        except Exception as e:
            messagebox.showerror("另存为失败", str(e))
            return
        self._set_status(f"已另存为：{path}")
        self._show_log("另存为完成（原存档未修改）", log)

    def on_undo(self):
        if self.om.undo():
            self._set_status("已撤销上次修改")
            self._refresh_all()

    def on_redo(self):
        if self.om.redo():
            self._set_status("已重做修改")
            self._refresh_all()

    def on_reset(self):
        if not self.om.has_pending() and not self.om.ops:
            return
        if messagebox.askyesno("重置全部修改",
                               "将清空所有待操作（含已撤销的），左侧列表恢复原状。"
                               "是否继续？"):
            self.om.reset()
            self._set_status("已重置全部修改")
            self._refresh_all()

    # ------------------------------------------------------------------
    # 功能面板动作
    # ------------------------------------------------------------------
    def on_set_host(self):
        idx = self.host_combo.current()
        if idx < 0 or idx >= len(self._combo_rows):
            messagebox.showwarning("未选择玩家", "请先在下拉列表中选择玩家。")
            return
        row = self._combo_rows[idx]
        self.om.add(SetHostOp(row.uuid))
        self._set_status(f"已记录待操作：修改房主为 {row.display_name()} ({row.uuid})")
        self._refresh_all()

    def on_migrate(self):
        idx = self.src_combo.current()
        if idx < 0 or idx >= len(self._combo_rows):
            messagebox.showwarning("未选择目标 UUID",
                                   "请先在“目标 UUID”下拉列表中选择玩家。")
            return
        src = self._combo_rows[idx].uuid

        dst_text = self.dst_combo.get().strip()
        # 支持从下拉选择（格式为 "名称 (uuid)"），提取括号中的 UUID
        if "(" in dst_text and dst_text.endswith(")"):
            dst_text = dst_text.rsplit("(", 1)[1][:-1].strip()
        if not UUID_RE.fullmatch(dst_text):
            # 也接受无横杠形式
            if UUID_RE.fullmatch(uuid_dashed(dst_text) if
                                 len(dst_text.replace("-", "")) == 32 else ""):
                dst_text = uuid_dashed(dst_text)
            else:
                messagebox.showwarning(
                    "UUID 格式无效",
                    "“要修改成的 UUID”必须是标准 UUID 格式，例如：\n"
                    "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
                return
        dst = uuid_dashed(dst_text)

        if src == dst:
            messagebox.showwarning("UUID 相同", "目标 UUID 与要修改成的 UUID 相同。")
            return
        if not self.sm.find_uuid_files(dst):
            # 目标不存在文件 → 单向迁移，提示用户确认
            if not messagebox.askyesno(
                    "单向迁移确认",
                    f"存档中没有找到 UUID {dst} 的任何文件，"
                    f"将执行单向迁移（{src} → {dst}）。是否继续？"):
                return

        self.om.add(MigrateUuidOp(src, dst))
        self._set_status(f"已记录待操作：UUID 迁移 {src} → {dst}")
        self._refresh_all()

    # ------------------------------------------------------------------
    def _show_log(self, title: str, log):
        """弹出日志窗口展示操作明细。"""
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("640x420")
        text = scrolledtext.ScrolledText(win, wrap=tk.NONE, font=("Consolas", 9))
        text.pack(fill=tk.BOTH, expand=True)
        text.insert(tk.END, "\n".join(log))
        text.configure(state=tk.DISABLED)
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=6)

    def on_close(self):
        if self.om.has_pending():
            if not messagebox.askyesno(
                    "退出", "还有未保存的待操作，退出将丢失这些修改。确定退出吗？"):
                return
        if self._fetch_pool:
            self._fetch_pool.shutdown(wait=False)
        self.root.destroy()
