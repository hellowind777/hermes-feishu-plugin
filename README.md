# Hermes 飞书插件

把官方 `@larksuite/openclaw-lark` 的飞书交互默认体验适配到 Hermes。

当前目标：

- 使用 `Typing` 反应表示“正在处理”
- 不再使用 Hermes 原生的 `OK` 回执反应
- 主动清理历史残留或异常出现的 `OK` 回执
- 使用单条 `reply_to` 交互卡片承载整次流式输出与最终答案
- 当工具先执行、答案后出来时，优先复用同一张卡片，不再额外冒出工具灰消息
- 交互卡片更新对齐 OpenClaw：使用 `im.message.patch` 而不是 `im.message.update`
- Feishu 流式阶段忽略 Hermes 原生的“工具边界后新开消息”逻辑，尽量保持全程单条回复更新
- 屏蔽 Feishu 聊天中的内部状态灰消息：重试、fallback、context compaction、原始 tool progress
- 子代理/委托任务的工具活动会实时透传到同一张卡片，并高亮当前阶段
- 卡片内容形态更接近 OpenClaw：`工具执行中 / 思考中 / 最终答案 / 完成 footer`
- 卡片 JSON 进一步对齐官方：改为 `CardKit 2.0` 风格的 `schema + body.elements`
- 回复模式对齐官方默认语义：`auto` 下私聊走流式卡片、群聊走静态回复
- 仓库按“可公开开源”标准整理，不包含 Bot 密钥、OpenID、本地账号路径等隐私信息

## 设计说明

Hermes 目前只能加载 Python 目录插件，不能直接加载 OpenClaw 的 Node 插件。
因此本仓库采用“**行为适配 + 官方交互语义对齐**”方案：

- 参考官方 `openclaw-lark` 的默认配置与交互语义
- 用 Hermes 官方插件系统进行运行时补丁
- 不直接修改 Hermes 核心源码

当前仍然是 **Hermes 侧 Python 适配实现**，不是把官方 Node 插件原样搬过来。
因此目标是“使用体验尽量贴近官方默认效果”，而不是声称已经 100% 字节级对齐。

## 隐私与开源

本仓库默认按公开仓库标准维护：

- 不提交任何 `app_id`、`app_secret`、`open_id`、API Key
- 不提交 `.env`、日志、缓存、`__pycache__`
- 不写死个人用户名、本地磁盘路径、Bot 绑定关系

如果未来确实需要保存真实配置，仓库必须改为私有仓库。

## 对齐的官方行为

参考官方包 `@larksuite/openclaw-lark`：

- `Typing` 反应作为处理中提示
- 单条交互卡片承载流式输出
- 回复原始用户消息而不是悬空发送
- 清除 Hermes 内置 `OK` 回执路径
- 在工具执行阶段尽量把进度折叠进同一张卡片
- `auto` 模式下私聊优先流式、群聊优先静态

## 当前配置

可选环境变量：

- `HERMES_FEISHU_REPLY_MODE=auto|streaming|static`
- `HERMES_FEISHU_LOCALE=auto|zh_cn|en_us`

默认值为 `auto`：

- 私聊：`streaming`
- 群聊：`static`
- 语言：优先跟随系统环境；也可以显式强制中文或英文

## 安装位置

开发仓库：

- 任意本地开发目录，例如 `hermes-feishu-plugin`

Hermes 插件加载位置：

- `~/.hermes/plugins/hermes_feishu_plugin`
- `~/.hermes/profiles/*/plugins/hermes_feishu_plugin`

## 安装

在插件仓库目录执行：

```bash
python3 install.py
```

它会把插件链接到 root 和各 profile 的 Hermes 插件目录。

## 许可证

MIT
