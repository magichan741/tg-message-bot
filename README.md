# TG 留言机器人（GitHub Actions 托管）

有人在 Telegram 里给机器人发消息，机器人把留言转发到**你自己的账号或私密频道**；
你在 Telegram 里用 `/reply` 就能直接回复留言者，全程不用电脑。
不用服务器、不用域名、不用公网 IP，靠 GitHub Actions 免费跑。GitHub 的机器在海外，能直连 Telegram API。

## 它是怎么跑的

```
留言者 --发消息--> Telegram --getUpdates--> GitHub Actions(每5分钟一轮,每轮约4.5分钟) --转发--> 你
```

- 无状态设计：不存数据库、不往仓库写任何东西（仓库设为公开也不泄露留言内容）
- 靠 getUpdates 的 offset 在 Telegram 服务端"已读确认"，退出前再确认一次，不会重复转发
- 已处理：文字 / 图片 / 视频 / 语音 / 文件 / 贴纸 / 位置 / 联系人，媒体原样复制一份给你
- 已知代价：不是秒回，延迟大约 5～20 分钟（GitHub cron 本身会被排队延迟）

## 一、拿到 Bot Token（2 分钟）

1. Telegram 里搜 `@BotFather`，发 `/newbot`
2. 起名字（显示名随便），再起一个以 `bot` 结尾的用户名，如 `my_msg_123_bot`
3. 它回你一串 `123456789:AAH-xxxxxxxx`，这就是 **BOT_TOKEN**，别外泄

## 二、拿到你自己的 chat_id

两种办法，任选：

- 办法 A：先把 bot 拉进一个只有你的**私密频道**（新建 Channel，设为 Private），把 bot 设成管理员（发消息权限就够了）。
  然后随便发条消息，用 `https://api.telegram.org/bot<TOKEN>/getUpdates` 看返回里的 `chat.id`，频道一般是 `-100` 开头。
- 办法 B：先用你自己的号给 bot 发一句 `hi`，同样看 `getUpdates`，里面 `chat.id` 就是你的数字 id。

这个 id 后面填成 **TARGET_CHAT_ID**。

> 频道比个人号更好：留言集中在一处，还能置顶、搜索，不会和自己的聊天混在一起。

## 三、建仓库

1. 在 GitHub 新建仓库，例如 `tg-message-bot`
2. **建议设为 Public**：公开仓库的 Actions 分钟数不限；私有仓库免费只有 2000 分钟/月，24 小时轮询根本不够（约需要 8000+ 分钟/月）。仓库里没有你的 token（token 放 Secrets），公开是安全的。
3. 把本目录文件推上去：
   ```bash
   git init
   git add .
   git commit -m "init tg message bot"
   git branch -M main
   git remote add origin https://github.com/<你的用户名>/tg-message-bot.git
   git push -u origin main
   ```

## 四、配 Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret：

| Name | Value |
|---|---|
| `BOT_TOKEN` | BotFather 给的 token |
| `TARGET_CHAT_ID` | 你的 chat id 或频道 id（`-100...`） |

## 五、开跑

1. 仓库 → Actions 标签页 → 如果提示 workflow 被禁用，点 **I understand my workflows, go ahead and enable them**
2. 选 `TG Message Bot` → **Run workflow** 手动跑一次，看日志出现 `机器人身份：@xxx` 就通了
3. 之后它每 5 分钟自动跑一次，不用管

> 仓库 60 天没有任何提交活动，GitHub 会自动暂停定时任务，去 Actions 页面点一下 "Enable" 或随便提交一次即可恢复。

## 六、怎么用

- 别人给 bot 发消息 → 你立刻（5 分钟内）在目标会话里看到 `📩 新留言` + 原文/媒体
- 你看完想回：复制留言里的 `chat_id`，在目标会话里发
  ```
  /reply 555 收到啦，稍后发你
  ```
  对方会直接收到你这句话（看起来是机器人发的）
- `/id` 查当前会话 id
- 想给留言者自动回一句"已收到"：Actions 里把 `ACK: "0"` 改成 `"1"`，或用 secret 覆盖

## 文件说明

| 文件 | 作用 |
|---|---|
| `poll_bot.py` | 机器人主程序，纯标准库，可 `python3 poll_bot.py --selftest` 本地自测 |
| `.github/workflows/bot.yml` | 定时任务：每 5 分钟一轮，单轮 280 秒 |

## 想要"秒回"怎么办

Actions 轮询天生有 5～20 分钟延迟。如果收留言必须实时，换成 **Cloudflare Worker + Webhook**：
免费、常驻、毫秒级响应，留言还能存进 KV / D1 数据库。需要的话告诉我，我直接把 Worker 版代码写好。

## 排错

| 现象 | 原因 |
|---|---|
| 日志 `getMe 失败` / 401 | token 错、被 BotFather `/revoke` 过 |
| 日志 `缺少 secret: BOT_TOKEN` | Secrets 名字拼错，或没在 Actions 里启用 |
| 转发失败 `chat not found` | TARGET_CHAT_ID 错；频道要把 bot 设为管理员，个人号要先给 bot 发过消息 |
| 完全没跑 | Actions 被禁用 / 仓库不活跃被暂停 / cron 排队延迟 |
| 同一条留言重复出现 | 上一轮被 timeout 强杀没确认 offset，正常情况下一轮内会自愈 |
