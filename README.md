# Hermes 飞书插件

把官方 `@larksuite/openclaw-lark` 的飞书交互体验，按 **Hermes 官方支持的插件形态** 适配到 Hermes。

## 目标

- 对齐 OpenClaw 官方插件的飞书默认交互语义
- 保持 Hermes 官方推荐的 **Python 目录插件** 形态
- 同时提供 Hermes 官方支持的 **pip entry point** 分发能力
- 不修改 Hermes 核心源码，只通过插件与运行时补丁完成接入

## 为什么不是直接搬 OpenClaw 的 Node 插件

OpenClaw 官方飞书插件本身是 Node 技术栈，但 Hermes 当前官方推荐与稳定支持的加载方式是：

- `plugin.yaml` + `__init__.py` 的目录插件
- `hermes_agent.plugins` entry point 的 Python 包分发

因此本仓库采用的是：

- **交互语义对齐**
- **仓库结构对齐**
- **Hermes 官方插件生态对齐**

而不是强行把 Node 插件塞进 Hermes 的非官方加载链路。

## 当前对齐的核心行为

- 使用飞书 `Typing` 反应表示“正在处理”
- 关闭并清理 Hermes 默认的 `OK` 回执反应
- 使用单条 `reply_to` 卡片承载流式过程与最终答案
- 工具执行过程尽量折叠进同一张卡片
- 优先走 `CardKit 2.0` 形态与 `im.message.patch` 更新路径
- 抑制上下文压缩、fallback、原始工具状态等噪音消息
- 委托/子代理过程继续汇总到同一条飞书回复
- 回复模式对齐 OpenClaw 默认语义：`auto` 下私聊流式、群聊静态
- 本地化按钮、审批文案与系统提示

## 仓库结构

```text
hermes-feishu-plugin/
├─ plugin.yaml
├─ __init__.py
├─ install.py
├─ pyproject.toml
├─ src/hermes_feishu_plugin/
│  ├─ plugin.py
│  ├─ core/
│  ├─ channel/
│  ├─ card/
│  └─ tools/
└─ tests/
```

结构含义：

- 根目录保留 Hermes 目录插件入口
- `src/hermes_feishu_plugin/` 承载真实实现
- `pyproject.toml` 提供 `hermes_agent.plugins` entry point
- `tests/` 提供可重复的本地验收

## 安装方式

### 方式一：目录插件

在仓库根目录执行：

```bash
python3 install.py
```

它会把插件软链接到：

- `~/.hermes/plugins/hermes_feishu_plugin`
- `~/.hermes/profiles/*/plugins/hermes_feishu_plugin`

同时会自动清理旧版遗留的：

- `hermes-feishu-plugin` 旧命名软链
- `runtime_patches` 旧插件目录/软链

### 方式二：pip entry point

在 Hermes 运行环境中安装：

```bash
pip install -e .
```

适用于后续包分发、虚拟环境安装与自动化部署。

## 配置

可选环境变量：

- `HERMES_FEISHU_REPLY_MODE=auto|streaming|static`
- `HERMES_FEISHU_LOCALE=auto|zh_cn|en_us`

默认值：

- 私聊：`streaming`
- 群聊：`static`
- 语言：优先跟随系统与运行环境自动判断

## 开发与测试

```bash
pytest
```

## 隐私与开源

仓库按公开开源标准维护：

- 不提交 `app_id`、`app_secret`、`open_id`、API Key
- 不提交 `.env`、日志、缓存、`__pycache__`
- 不写死个人用户名、本地磁盘路径、Bot 绑定关系

若未来必须保存真实配置，仓库应改为私有仓库。

## 许可证

MIT
