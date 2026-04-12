# Hermes 飞书插件 × OpenClaw 官方插件对齐清单

> 目标：不是继续做“看起来像”的补丁，而是在 Hermes 当前插件体系内，尽量按 OpenClaw 官方 `openclaw-lark` 的传输模型、卡片模型、交互模型和故障回退模型做同构实现。

## 一、源码分析结论

### 1. 官方实现的核心事实

- 官方主链路不是 `im.message.patch` 伪流式，而是 **CardKit-first**
  - 先 `card.create`
  - 再通过 `card_id` 发送一条 `interactive` 消息
  - 流式正文走 `cardElement.content`
  - 终态通过 `card.settings(streaming_mode=false)` + `card.update`
- 官方并不是“只用 CardKit”，而是 **CardKit 优先，IM patch 回退**
  - `CardKit` 正常：100ms 级流式节流
  - `im.message.patch` 回退：1500ms 级节流，规避 `230020`
- 官方工具进度不是原始文本拼接，而是 **结构化工具步骤面板**
  - 有 `pending / running / success / error`
  - 有图标、标题、详情、结果块、错误块
- 官方预答复阶段和终态阶段是 **不同卡片结构**
  - 预答复：等待工具 / 动态 loading icon / 空正文元素
  - 终态：工具面板 + 折叠思考面板 + 正式答案 + footer
- 官方交互事件依赖 **`card.action.trigger` 正常回调**
  - 包括 Ask User、Auth、审批等
- 官方视觉体验关键点
  - 回复后先出现 **Typing** reaction
  - 单条回复消息持续更新
  - 不额外发送“OK”“处理中...”之类噪声消息

### 2. 当前 Hermes 插件与官方的主要差距

- 当前主链路仍是 `im.message.patch` 主导，**不是真正 CardKit 流式**
- 当前卡片 `streaming_mode` 只是 JSON 标志位，**不是官方 CardKit 生命周期**
- 当前工具显示基于文本猜测，**不是结构化 trace**
- 当前卡片正文/工具区/footer 结构与官方仍有明显差异
- 当前没有官方级别的：
  - `card_id / sequence / original_card_id`
  - `CardKit -> IM patch` 分级回退
  - `230020 / 230099 / 11310` 官方式处理
  - 预答复专用卡
  - 终态关流 + 更新卡片的完整闭环

### 3. Hermes 侧可复用挂点

- `gateway.stream_consumer.GatewayStreamConsumer`
  - 可接管流式内容发送
- `gateway.platforms.feishu.FeishuAdapter`
  - 可接管 Feishu send/edit/typing/approval/card action
- Hermes 插件 hooks
  - `pre_tool_call`
  - `post_tool_call`
  - `pre_llm_call`
- Python `lark_oapi`
  - 已内置 `cardkit.v1`
  - 可直接调用 `card.create / cardElement.content / card.update / card.settings`

## 二、实施对齐清单

## A. 传输与生命周期

- [ ] 新增 Python 版 CardKit 封装
  - `card.create`
  - `cardElement.content`
  - `card.update`
  - `card.settings`
- [ ] 建立单 chat 会话态
  - `card_id`
  - `original_card_id`
  - `card_sequence`
  - `card_message_id`
  - `phase`
- [ ] 让 Feishu 流式主路径切换为 **CardKit-first**
- [ ] 让失败路径回退为 **IM patch**
- [ ] 终态统一走
  - 关闭 streaming mode
  - 更新终态卡
- [ ] 保留 reply-to 单消息模型，继续引用用户原消息回复

## B. 卡片结构

- [ ] 预答复卡对齐官方
  - 空正文 `streaming_content`
  - loading icon
  - `等待工具执行` 折叠面板
- [ ] 工具执行中的预答复卡对齐官方
  - active tool-use panel
  - 按步骤展示工具状态
- [ ] 正文流式区域改为官方式 `STREAMING_ELEMENT_ID`
- [ ] 终态卡对齐官方
  - 工具面板
  - 可折叠思考面板
  - 正式答案主体
  - footer 与 summary
- [ ] 清理当前非官方式附加文本
  - “⌨️ 处理中...”
  - 自定义 footer 噪声
  - 原始工具字符串堆叠

## C. 工具进度

- [ ] 新增结构化工具 trace 存储
- [ ] 用 `pre_tool_call/post_tool_call` 记录步骤
- [ ] 将工具展示从“文本解析”升级为“结构化步骤”
- [ ] 保留状态文本解析作为兼容兜底
- [ ] 子代理/委托工具活动继续汇总到同一张卡

## D. 交互与回调

- [ ] 保留并强化 `card.action.trigger` 回调补丁
- [ ] 确保审批按钮走 callback 返回而不是丢帧
- [ ] 审批卡继续本地化
- [ ] 保留官方式 typing reaction
- [ ] 彻底禁止旧 ACK “OK” 持久 reaction

## E. 稳定性与风控

- [ ] 新增官方式节流常量
  - CardKit：100ms
  - Patch：1500ms
  - reasoning/tool status：1500ms
- [ ] 引入 flush controller
- [ ] 处理 `230020` 频率限制
- [ ] 处理 `230099 / 11310` 表格超限
- [ ] 失败时禁止重复发送多条消息
- [ ] 保持单消息更新体验

## F. 本地化与体验

- [ ] 系统固定文案继续跟随系统语言
- [ ] 卡片标题/按钮/提示尽量中英双语 i18n
- [ ] 保持与 OpenClaw 官方插件一致的视觉节奏

## G. 验证与交付

- [ ] `py_compile` 语法检查
- [ ] WSL 内实际安装插件
- [ ] 重启 5 个 gateway
- [ ] 验证
  - 单消息回复
  - Typing reaction
  - CardKit 真流式
  - 工具步骤面板
  - 审批按钮点击
  - 终态收尾

## 三、实施策略

### 第一阶段：建立对齐骨架

- 引入 `CardKit` 封装
- 引入会话状态机
- 引入官方式卡片 builder
- 引入 flush controller

### 第二阶段：切换主链路

- 改造 `GatewayStreamConsumer` 的 Feishu 分支
- 从 `IM patch 主路径` 切换到 `CardKit-first`
- 保留 patch fallback

### 第三阶段：对齐工具与交互

- 用 hook 构建工具 trace
- 接管工具面板渲染
- 保留并修复 `card.action.trigger`

### 第四阶段：WSL 实装验证

- 安装插件
- 重启网关
- 验证真实 Feishu 行为

## 四、范围说明

- 本次对齐目标是 **Hermes 飞书插件与 OpenClaw 官方飞书插件的“交互与传输实现”对齐**
- 不会把 OpenClaw 的 doc/wiki/task/calendar 全量工具族移植进 Hermes
- 但会把最关键、最影响体验的以下部分做到同构：
  - CardKit 真流式
  - 单消息更新
  - typing reaction
  - 工具步骤面板
  - callback 交互
  - 本地化与噪声抑制
