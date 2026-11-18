#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 留言机器人（GitHub Actions 轮询版）

留言者发消息 -> 转发到"主人"会话（主人 = 第一个给 bot 发 /start 的人）
主人发 /reply <chat_id> <内容> -> 机器人代你回复
纯标准库，无第三方依赖；不往仓库写留言内容，只写 data/owner.txt（主人 id）

环境变量：
  BOT_TOKEN       必填
  TARGET_CHAT_ID  可选：预先固定主人/频道 id，填了就跳过认领流程
  RUN_SECONDS     可选，单轮运行秒数，默认 270
  ACK             可选，1 = 给留言者回一句"已收到"
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
TARGET = os.environ.get("TARGET_CHAT_ID", "").strip()
RUN_SECONDS = int(os.environ.get("RUN_SECONDS", "270"))
ACK = os.environ.get("ACK", "0").strip() == "1"
ACK_TEXT = os.environ.get("ACK_TEXT", "已收到你的留言，我会尽快查看并回复。")

OWNER_FILE = os.path.join("data", "owner.txt")
BIZ_FILE = os.path.join("data", "bizmap.json")
API_BASE = "https://api.telegram.org/bot{token}/{method}"
_FAKE_CALL = None


def log(*args):
    print(f"[{time.strftime('%H:%M:%S')}]", *args, flush=True)


def call(method, **params):
    if _FAKE_CALL is not None:
        return _FAKE_CALL(method, **params)
    url = API_BASE.format(token=TOKEN, method=method)
    data = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=70) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            log(f"HTTP {e.code} {method}: {body[:200]}")
            if e.code in (400, 401, 403):
                return {"ok": False, "error": body}
            time.sleep(2)
        except Exception as e:
            log(f"网络异常 {method}: {e}")
            time.sleep(2)
    return {"ok": False, "error": "request failed"}


def load_owner():
    if TARGET:
        return TARGET
    try:
        with open(OWNER_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def save_owner(chat_id):
    os.makedirs("data", exist_ok=True)
    with open(OWNER_FILE, "w", encoding="utf-8") as f:
        f.write(f"{chat_id}\n")
    log(f"已绑定主人：{chat_id}")


# ---- 业务连接映射：客户 chat_id -> business_connection_id ----
def load_biz():
    try:
        with open(BIZ_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_biz(mapping):
    if not mapping:
        return
    os.makedirs("data", exist_ok=True)
    with open(BIZ_FILE, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=1)


def display_name(user):
    if not user:
        return "未知用户"
    name = " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x)
    if user.get("username"):
        name += f" (@{user['username']})"
    return (name or f"id{user.get('id')}").strip()


def extract(msg):
    text = msg.get("text") or msg.get("caption") or ""
    if msg.get("photo"):
        kind = "图片"
    elif msg.get("video"):
        kind = "视频"
    elif msg.get("video_note"):
        kind = "圆视频"
    elif msg.get("voice"):
        kind = "语音"
    elif msg.get("audio"):
        kind = "音频"
    elif msg.get("document"):
        kind = f"文件 {msg['document'].get('file_name','')}".strip()
    elif msg.get("sticker"):
        kind = "贴纸"
    elif msg.get("animation"):
        kind = "动图"
    elif msg.get("location"):
        kind = "位置"
        loc = msg["location"]
        text = text or f"https://maps.google.com/?q={loc['latitude']},{loc['longitude']}"
    elif msg.get("contact"):
        c = msg["contact"]
        kind = "联系人"
        text = text or f"{c.get('first_name','')} {c.get('phone_number','')}"
    else:
        kind = "消息"
    return kind, text


MEDIA_KEYS = ("photo", "video", "video_note", "voice", "audio",
              "document", "sticker", "animation")


def handle_message(msg, update_id, biz_id=None):
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    sender = msg.get("from", {})
    text = msg.get("text") or ""
    if sender.get("is_bot"):
        return

    owner = load_owner()

    # 业务会话（秘书模式）：记录 chat_id -> business_connection_id，供 /reply 使用
    if biz_id and chat_id:
        biz = load_biz()
        if biz.get(str(chat_id)) != biz_id:
            biz[str(chat_id)] = biz_id
            save_biz(biz)
            log(f"登记业务会话 {chat_id} -> {biz_id}")

    # 还没有主人：只接受 /start 认领
    if not owner:
        if text.strip() == "/start":
            save_owner(chat_id)
            call("sendMessage", chat_id=chat_id, text=(
                "已把你设为留言接收人。\n"
                "之后别人给这个 bot 发的消息都会转发到这里。\n"
                "回复对方：/reply <chat_id> <内容>\n"
                "查自己的 id：/id"
            ))
        else:
            call("sendMessage", chat_id=chat_id, text="机器人尚未绑定主人，请先发送 /start 完成绑定。")
        return

    # 主人在业务会话里自己打的字，不用再转给自己
    if biz_id and str(sender.get("id")) == str(owner):
        return

    # 主人指令
    if str(chat_id) == str(owner) and text.startswith("/"):
        cmd, _, rest = text.partition(" ")
        if cmd in ("/start", "/help"):
            call("sendMessage", chat_id=chat_id, text=(
                "留言机器人在线。\n"
                "/id  查看 chat id\n"
                "/reply <chat_id> <内容>  回复留言者\n"
                "/whoami  查看当前绑定\n"
                "/sessions  已登记的业务会话数"
            ))
            return
        if cmd == "/id":
            call("sendMessage", chat_id=chat_id, text=f"当前 chat_id：{chat_id}")
            return
        if cmd == "/whoami":
            call("sendMessage", chat_id=chat_id, text=f"留言接收人：{owner}")
            return
        if cmd == "/sessions":
            call("sendMessage", chat_id=chat_id, text=f"已登记业务会话：{len(load_biz())} 个")
            return
        if cmd == "/reply":
            target_id, _, body = rest.partition(" ")
            if not target_id.lstrip("-").isdigit() or not body.strip():
                call("sendMessage", chat_id=chat_id, text="用法：/reply <chat_id> <内容>")
                return
            target_id = target_id.strip()
            params = {"chat_id": target_id, "text": body.strip()}
            biz_id_for_target = load_biz().get(target_id)
            if biz_id_for_target:
                params["business_connection_id"] = biz_id_for_target
            r = call("sendMessage", **params)
            via = "（业务会话）" if biz_id_for_target else ""
            call("sendMessage", chat_id=chat_id,
                 text=(f"已发送{via}。" if r.get("ok") else f"发送失败{via}：{r.get('error','未知')}"))
            return

    # 留言 -> 转发存档
    kind, body = extract(msg)
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(msg.get("date", int(time.time()))))
    header = (f"📩 新留言 #{update_id}\n"
              f"来自：{display_name(sender)}\n"
              f"chat_id：{chat_id}\n"
              f"时间(UTC)：{ts}\n"
              f"类型：{kind}"
              + ("\n通道：业务账号（秘书模式）" if biz_id else ""))
    call("sendMessage", chat_id=owner, text=(header + ("\n\n" + body if body.strip() else ""))[:4000],
         disable_web_page_preview="true")
    if any(k in msg for k in MEDIA_KEYS):
        call("copyMessage", chat_id=owner, from_chat_id=chat_id, message_id=msg.get("message_id"))
    if ACK and chat_id and not biz_id:
        call("sendMessage", chat_id=chat_id, text=ACK_TEXT)
    log(f"已转发 #{update_id} 来自 {display_name(sender)}")


def run():
    if not TOKEN:
        log("缺少 BOT_TOKEN")
        sys.exit(1)

    me = call("getMe")
    if me.get("ok"):
        log(f"机器人身份：@{me['result'].get('username')}")
        log(f"链接：https://t.me/{me['result'].get('username')}")
    else:
        log(f"getMe 失败：{me.get('error')}")
        sys.exit(1)

    log(f"当前主人：{load_owner() or '未绑定（等 /start）'}")

    deadline = time.time() + RUN_SECONDS
    offset, last_id = 0, None
    allowed = json.dumps(["message", "channel_post",
                          "business_connection", "business_message",
                          "edited_business_message"])
    while time.time() < deadline:
        wait = max(1, min(30, int(deadline - time.time())))
        r = call("getUpdates", offset=offset, timeout=wait, allowed_updates=allowed)
        if not r.get("ok"):
            log(f"getUpdates 失败：{r.get('error')}")
            time.sleep(3)
            continue
        for u in r.get("result") or []:
            last_id = u["update_id"]
            try:
                if "business_connection" in u:
                    bc = u["business_connection"]
                    log(f"业务连接：id={bc.get('id')} user={bc.get('user',{}).get('id')} 已启用={bc.get('is_enabled')}")
                elif u.get("business_message"):
                    handle_message(u["business_message"], last_id,
                                   biz_id=u["business_message"].get("business_connection_id"))
                elif u.get("message") or u.get("channel_post"):
                    handle_message(u.get("message") or u.get("channel_post"), last_id)
            except Exception as e:
                log(f"处理 {last_id} 出错：{e}")
            offset = last_id + 1

    if last_id is not None:
        call("getUpdates", offset=last_id + 1, timeout=0, limit=1)
        log(f"本轮结束，已确认到 update {last_id}")
    else:
        log("本轮无新留言")


def selftest():
    global _FAKE_CALL, TARGET, TOKEN
    import shutil, tempfile
    tmp = tempfile.mkdtemp()
    os.chdir(tmp)
    TOKEN, TARGET = "T:T", ""
    sent = []

    def fake(method, **params):
        sent.append((method, params))
        return {"ok": True}

    _FAKE_CALL = fake

    # 未绑定时的普通消息
    handle_message({"chat": {"id": 555}, "from": {"id": 555, "first_name": "路人"},
                    "text": "hi", "date": 1700000000}, 1)
    assert "尚未绑定主人" in json.dumps(sent, ensure_ascii=False)

    # /start 认领
    handle_message({"chat": {"id": 999}, "from": {"id": 999, "first_name": "我"},
                    "text": "/start", "date": 1700000001}, 2)
    assert load_owner() == "999"

    # 文字留言
    handle_message({"chat": {"id": 555}, "from": {"id": 555, "first_name": "小明",
                    "username": "ming"}, "text": "想问问片源", "date": 1700000002}, 3)
    # 图片留言
    handle_message({"chat": {"id": 556}, "from": {"id": 556, "first_name": "小红"},
                    "photo": [{"file_id": "x"}], "caption": "报错截图", "date": 1700000003}, 4)
    # 主人 /reply
    handle_message({"chat": {"id": 999}, "from": {"id": 999, "first_name": "我"},
                    "text": "/reply 555 收到啦", "date": 1700000004}, 5)
    # bot 消息忽略
    handle_message({"chat": {"id": 557}, "from": {"id": 557, "is_bot": True}, "text": "x"}, 6)

    dumped = json.dumps(sent, ensure_ascii=False)
    assert "小明" in dumped and "小红" in dumped
    assert "copyMessage" in dumped
    assert "收到啦" in dumped
    assert '"chat_id": "557"' not in dumped and '"chat_id": 557' not in dumped
    shutil.rmtree(tmp)
    print(f"自检通过，共 {len(sent)} 次 API 调用")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        run()
