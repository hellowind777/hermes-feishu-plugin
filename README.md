# Hermes 飞书插件

面向 **Hermes** 的飞书 / Lark 通道插件，目标是尽量对齐官方 `@larksuite/openclaw-lark` 的默认交互体验，同时严格保持 **Hermes 官方支持的 Python 插件形态**。

本仓库适合以下场景：

- 你已经在使用 Hermes，希望把飞书侧交互体验尽可能调成接近 OpenClaw 官方语义
- 你希望保留 Hermes 官方推荐的 `plugin.yaml + __init__.py` 目录插件形态
- 你需要同时支持本地目录接入、`pip` 分发，以及面向公开仓库的 GitHub / npm 发布链路

## 项目定位

这个仓库做的是 **Hermes 飞书通道插件**，不是 Hermes 核心分叉，也不是把 OpenClaw 的 Node 插件直接硬塞进 Hermes。

设计原则：

- **交互语义对齐**：尽可能对齐 OpenClaw 官方飞书插件的用户感知
- **宿主生态对齐**：遵守 Hermes 官方稳定支持的 Python 插件加载方式
- **职责边界清晰**：只处理飞书通道、卡片、状态、本地化、审批与消息聚合
- **公开仓库可维护**：不提交个人路径、真实密钥、绑定关系和本地运行痕迹

## 核心能力

当前版本已经覆盖的核心行为包括：

- 使用飞书 `Typing` 反应表示“正在处理”
- 清理 Hermes 默认的 `OK` / 状态类噪音反应
- 使用单条 `reply_to` 卡片承载流式过程与最终答案
- 工具执行过程尽量折叠进同一张卡片，而不是频繁发多条消息
- 优先走 `CardKit 2.0` 与 `im.message.patch` 更新链路
- 抑制上下文压缩、fallback、原始工具状态等对终端用户无价值的噪音消息
- 静默 Hermes 忙碌中断确认，避免向飞书回落英文提示
- 合并同一轮快速到达的文字、图片、视频、文件、音频为一个 Hermes 输入
- 合并忙碌期间排队的后续消息，避免只消费最后一条
- 委托 / 子代理过程继续汇总到同一条飞书回复
- 在 `auto` 模式下对齐 OpenClaw 默认语义：私聊流式、群聊静态
- 本地化按钮、审批文案与系统提示
- 启动时发现同级共享目录中的非飞书插件并执行目录链接，不承载其业务逻辑

## 为什么不是直接复用 OpenClaw 的 Node 插件

OpenClaw 官方飞书插件使用的是 Node 技术栈，但 Hermes 当前更稳定、也更官方的插件接入方式是：

- 目录插件：`plugin.yaml` + `__init__.py`
- Python 包分发：`hermes_agent.plugins` entry point

所以这个仓库采用的是：

- **体验对齐**
- **接口语义对齐**
- **目录结构与分发方式对齐 Hermes**

而不是把 Node 运行时、Node 插件管理和 Hermes 的 Python 插件系统混杂在一起。

## 功能边界

### 本插件负责

- 飞书消息接收、消息合并、忙碌期排队消息归并
- 回复卡片构建、流式更新、状态补丁与心跳刷新
- `Typing` 反应、本地化提示、审批交互、工具面板展示
- 飞书通道相关的运行时补丁
- 同级插件目录 bootstrap 与安装联动

### 本插件不负责

- 用户真实 `.env`
- 机器人真实凭据、飞书 App 密钥、Open API 密钥
- 个人本地路径、用户名、Bot 绑定关系
- 与飞书通道无关的 Hermes 核心路由、业务策略、角色编排
- 生产环境部署平台逻辑

如果未来要引入非飞书通道的 Hermes 核心补丁，建议拆成独立插件维护。

## 仓库结构

```text
hermes-feishu-plugin/
├─ plugin.yaml
├─ __init__.py
├─ install.py
├─ pyproject.toml
├─ package.json
├─ .github/workflows/
│  ├─ release.yml
│  └─ npm-publish.yml
├─ src/hermes_feishu_plugin/
│  ├─ plugin.py
│  ├─ startup.py
│  ├─ core/
│  ├─ channel/
│  ├─ card/
│  └─ tools/
└─ tests/
```

结构说明：

- `plugin.yaml`：Hermes 目录插件元数据
- `__init__.py`：目录插件入口 shim
- `install.py`：本地目录安装入口
- `pyproject.toml`：Python 包与 `entry point` 分发配置
- `package.json`：npm 元数据与公开仓库发布配置
- `.github/workflows/`：GitHub Release 与 npm 发布工作流
- `src/hermes_feishu_plugin/`：真实实现
- `tests/`：回归测试

## 安装方式

### 方式一：作为 Hermes 目录插件安装

在仓库根目录执行：

```bash
python3 install.py
```

安装器会尝试把插件链接到：

- `~/.hermes/plugins/hermes_feishu_plugin`
- `~/.hermes/profiles/*/plugins/hermes_feishu_plugin`

同时安装早期启动加载器，确保网关在收到飞书消息前就能启用以下能力：

- `Typing` 反应替代 `OK`
- 噪音状态收敛到同一张卡片
- 飞书系统提示本地化

安装器还会清理旧版遗留路径，例如：

- `hermes-feishu-plugin`
- `runtime_patches`

### 方式二：作为 Python 包安装

在 Hermes 运行环境中执行：

```bash
python -m pip install -e .
```

或发布后通过版本安装：

```bash
python -m pip install hermes-feishu-plugin
```

该方式适合：

- 虚拟环境部署
- 自动化安装
- `hermes_agent.plugins` entry point 分发

### 方式三：通过 npm 获取公开发布包

安装 npm 包：

```bash
npm install hermes-feishu-plugin
```

如果你使用 `pnpm` 或 `yarn`，等价命令分别是：

```bash
pnpm add hermes-feishu-plugin
yarn add hermes-feishu-plugin
```

本仓库会提供 npm 包发布链路，便于：

- 在前端 / 全栈仓库中统一管理公开依赖元数据
- 通过 npm registry 分发仓库快照与发布版本
- 在 GitHub Release 和 npm 包之间建立对应关系

需要注意：

- **Hermes 运行时安装仍以目录插件或 Python 包为主**
- npm 包更适合作为 **公开分发与版本追踪入口**
- 不建议把 npm 安装当作 Hermes 运行时的唯一安装方式

如果你确实是先通过 npm 拉取源码，再交给 Hermes 运行环境使用，可以继续执行：

```bash
python -m pip install ./node_modules/hermes-feishu-plugin
```

或在仓库 / 解包目录内执行：

```bash
python install.py
```

## 运行配置

当前支持的环境变量：

- `HERMES_FEISHU_REPLY_MODE=auto|streaming|static`
- `HERMES_FEISHU_LOCALE=auto|zh_cn|en_us`

默认行为：

- 私聊：`streaming`
- 群聊：`static`
- 语言：优先跟随系统与运行环境自动判断

### 回复模式说明

- `auto`
  - 私聊走流式
  - 群聊走静态
- `streaming`
  - 所有会话尽量以流式单卡更新
- `static`
  - 优先输出静态结果卡片

## 交互行为说明

### 1. 单卡片回复策略

插件会尽量把同一轮回复的以下内容聚合到单条卡片中：

- 正在输入状态
- 流式正文
- 工具调用进度
- 最终结果
- 错误提示

这样做的目标是减少飞书聊天记录中的碎片消息。

### 2. 忙碌期消息合并

当 Hermes 尚未完成上一轮处理时，插件会尽量合并后续快速到达的文字与媒体消息，避免只处理最后一条。

### 3. 状态噪音抑制

插件会主动拦截或折叠以下高噪音信息：

- 默认 ACK / OK 反应
- 原始工具状态刷屏
- fallback 提示
- 压缩上下文提示
- 忙碌中断确认回落文本

### 4. 本地化与审批

插件会对按钮、审批文案和系统提示做本地化处理，提升中文飞书场景下的一致性。

## 开发与测试

### 安装测试依赖

```bash
python -m pip install -e .[test]
```

### 运行测试

```bash
python -m pytest
```

### 建议的本地检查

```bash
python -m build
npm pack
```

## 发布流程

### GitHub Release

仓库内置 `release.yml`，在推送 `v*` 标签后会自动：

- 构建 Python `sdist` / `wheel`
- 打包 npm 归档
- 创建 GitHub Release
- 上传构建产物到 Release 资源

### npm 发布

仓库内置 `npm-publish.yml`，在 GitHub Release 发布后会尝试执行：

```bash
npm publish --access public
```

该工作流依赖仓库 Secret：

- `NPM_TOKEN`

如果没有配置 `NPM_TOKEN`，工作流会跳过发布步骤。

## 公开仓库安全约束

本仓库按公开开源标准维护，默认遵守以下原则：

- 不提交 `app_id`、`app_secret`、`open_id`、Webhook、API Key
- 不提交 `.env`、日志、缓存、`__pycache__`
- 不写死个人用户名、本地磁盘路径、私有部署细节
- 不在示例中使用真实生产凭据

如果未来必须保存真实配置，请改用私有仓库或外部密钥管理系统。

## 常见问题

### 这个插件能直接替代 OpenClaw 官方 Node 插件吗？

不能直接替代运行时形态，但会尽量对齐飞书侧交互体验。

### 为什么同时保留 Python 和 npm 元数据？

因为运行时归 Hermes Python 插件生态，公开分发与版本可见性则可以通过 GitHub / npm 补齐。

### npm 安装后就能直接被 Hermes 加载吗？

不建议把 npm 包当作 Hermes 运行时的唯一安装来源。对 Hermes 来说，更稳妥的仍然是目录插件或 Python 包安装。

## 许可证

Apache License 2.0
