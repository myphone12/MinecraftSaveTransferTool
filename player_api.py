# -*- coding: utf-8 -*-
"""player_api.py — 通过在线 API 获取玩家名称与头像。

  - 名称：Mojang 官方 api.minecraftservices.com（主通道）
          / sessionserver.mojang.com（备用通道），正版玩家可查到
  - 头像：Crafatar 第三方渲染服务

获取失败（离线玩家 / 无网络 / API 异常）时，名称显示"离线玩家"，
头像由 UI 层使用内置的史蒂夫像素画兜底。所有请求均在后台线程执行。
"""

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# Mojang profile 接口（主/备），传入无横杠 UUID，返回含 "name" 字段的 JSON
MOJANG_PROFILE_URLS = [
    "https://api.minecraftservices.com/minecraft/profile/lookup/{uuid}",
    "https://sessionserver.mojang.com/profile/{uuid}",
]
# 头像渲染服务（按顺序兜底）：部分账号 Crafatar 会返回 500，
# 此时改用 Minotar。均返回 PNG 字节。
AVATAR_URLS = [
    "https://crafatar.com/avatars/{uuid}?size=64&overlay",
    "https://minotar.net/avatar/{uuid}/64",
]

OFFLINE_NAME = "离线玩家"
REQUEST_TIMEOUT = 8   # 单个请求超时秒数


def _http_get(url: str):
    """发起 GET 请求，返回 bytes；任何异常（超时/404/无网络）返回 None。"""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "MinecraftSaveTransferTool/1.0"})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            return resp.read()
    except Exception:
        return None


def fetch_name(uuid_undashed: str):
    """通过 Mojang API 获取玩家名；失败返回 None（视为离线玩家）。

    依次尝试主/备两个官方接口，任一成功即返回。
    """
    for url_tpl in MOJANG_PROFILE_URLS:
        data = _http_get(url_tpl.format(uuid=uuid_undashed))
        if not data:
            continue
        try:
            name = json.loads(data.decode("utf-8")).get("name")
            if isinstance(name, str) and name:
                return name
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return None


def fetch_avatar(uuid_dashed: str):
    """获取玩家头像 PNG 字节；依次尝试各渲染服务，全部失败返回 None。"""
    for url_tpl in AVATAR_URLS:
        data = _http_get(url_tpl.format(uuid=uuid_dashed))
        # 校验 PNG 魔数，防止把错误页当作图片
        if data and data[:4] == b"\x89PNG":
            return data
    return None


def fetch_player_info(entry) -> None:
    """填充一个 PlayerEntry 的名称与头像（就地修改，供线程池调用）。"""
    undashed = entry.uuid.replace("-", "")

    name = fetch_name(undashed)
    if name:
        entry.name = name
        entry.online = True
        # 正版玩家才尝试拉取真实头像，离线玩家直接用史蒂夫兜底
        entry.avatar_png = fetch_avatar(entry.uuid)


def fetch_all_players(players, on_player_done) -> ThreadPoolExecutor:
    """并发获取所有玩家信息。

    每个玩家完成后在子线程回调 on_player_done(entry)，
    回调实现方需自行把 UI 更新调度回主线程（tkinter 要求）。
    返回线程池对象，便于关闭窗口时 shutdown。
    """
    pool = ThreadPoolExecutor(max_workers=min(8, max(1, len(players))))
    for entry in players:
        pool.submit(_worker, entry, on_player_done)
    return pool


def _worker(entry, on_player_done):
    """线程池任务：获取信息后回调通知。"""
    try:
        fetch_player_info(entry)
    finally:
        on_player_done(entry)
