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

### 1.1 上游源码 → Hermes 对齐矩阵

| 上游文件 | 官方职责 | Hermes 对应文件 | 对齐结果 | 备注 |
|---|---|---|---|---|
| `src/card/streaming-card-controller.ts` | CardKit-first 生命周期、状态机、flush、终态收尾 | `streaming.py` + `runtime_state.py` + `flush_controller.py` | 已对齐 | Hermes 没有 OpenClaw 那套 dispatcher factory，因此改为 patch `GatewayStreamConsumer` 实现同职责 |
| `src/card/reply-dispatcher.ts` | 统一 reply 分发、Typing、stream/static 分流 | `patches.py` + `streaming.py` | 已对齐 | Hermes 通过 runtime patch 接管 Feishu send/edit/typing/approval，而不是重写 reply dispatcher 工厂 |
| `src/card/reply-dispatcher-types.ts` | CardKit 状态、阶段常量、节流常量 | `runtime_state.py` + `models.py` + `streaming.py` | 已对齐 | Python 侧保留 `card_id / original_card_id / sequence / phase / message_id` |
| `src/card/builder.ts` | 预答复卡、流式区、终态卡、思考面板 | `card_builder.py` | 已对齐 | 保留 `STREAMING_ELEMENT_ID`、等待工具面板、思考折叠面板、终态 footer |
| `src/card/cardkit.ts` | `card.create / send by card_id / content / settings / update` | `cardkit.py` | 已对齐 | 直接对接 Python `lark_oapi.cardkit.v1` |
| `src/card/flush-controller.ts` | 更新节流、合并 flush | `flush_controller.py` | 已对齐 | CardKit 100ms / patch 1500ms 级别节流 |
| `src/card/tool-use-display.ts` | 结构化工具步骤展示 | `tool_display.py` | 已对齐 | 保留 step status / title / detail / result / error block |
| `src/channel/monitor.ts` | 单消息监控与生命周期观测 | `runtime_state.py` | 语义对齐 | Hermes 无同名模块，改为 chat 级 runtime state 承担 |
| `src/channel/event-handlers.ts` | 飞书事件入口与 action 回调 | `patches.py` | 已对齐 | 重点补上 `card.action.trigger` |
| `src/tools/ask-user-question.ts` | Ask User 按钮交互回调 | `patches.py` | 部分对齐 | 当前优先保证审批/卡片回调链路；Hermes 没有 OpenClaw 全量 ask-user 工具族 |

### 1.2 必须承认的架构差异

- OpenClaw 是原生 Lark channel 插件，Hermes 是通过插件 patch 已有 gateway。
- 因此本次追求的是 **实现行为对齐**，不是把 TypeScript 源码逐行翻译成 Python。
- 不能 1:1 照搬的部分，已按下面四层做等价对齐：
  - 传输模型：CardKit-first + IM patch fallback
  - 卡片模型：预答复卡 / 流式元素 / 终态卡
  - 交互模型：Typing / reply-to / action callback / approval callback
  - 故障回退模型：限流跳帧 / 表格超限降级 / 单消息不分裂

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

- [x] 新增 Python 版 CardKit 封装
  - `card.create`
  - `cardElement.content`
  - `card.update`
  - `card.settings`
- [x] 建立单 chat 会话态
  - `card_id`
  - `original_card_id`
  - `card_sequence`
  - `card_message_id`
  - `phase`
- [x] 让 Feishu 流式主路径切换为 **CardKit-first**
- [x] 让失败路径回退为 **IM patch**
- [x] 终态统一走
  - 关闭 streaming mode
  - 更新终态卡
- [x] 保留 reply-to 单消息模型，继续引用用户原消息回复
- [x] 维护与官方一致的状态字段
  - `card_id`
  - `original_card_id`
  - `card_message_id`
  - `card_sequence`
  - `phase`
- [x] 让终态收尾优先使用 CardKit `settings(false)` + `update`
- [x] CardKit 中途失败时不再新发第二条消息，而是切回原单消息补丁链路

## B. 卡片结构

- [x] 预答复卡对齐官方
  - 空正文 `streaming_content`
  - loading icon
  - `等待工具执行` 折叠面板
- [x] 工具执行中的预答复卡对齐官方
  - active tool-use panel
  - 按步骤展示工具状态
- [x] 正文流式区域改为官方式 `STREAMING_ELEMENT_ID`
- [x] 终态卡对齐官方
  - 工具面板
  - 可折叠思考面板
  - 正式答案主体
  - footer 与 summary
- [x] `STREAMING_ELEMENT_ID` 固定为独立流式区域，不再把正文和状态提示混在一起
- [x] reasoning 与 answer 拆分，避免把 `<think>`/`Reasoning:` 直接泄漏到最终答案区
- [x] 清理当前非官方式附加文本
  - “⌨️ 处理中...”
  - 自定义 footer 噪声
  - 原始工具字符串堆叠

## C. 工具进度

- [x] 新增结构化工具 trace 存储
- [x] 用 `pre_tool_call/post_tool_call` 记录步骤
- [x] 将工具展示从“文本解析”升级为“结构化步骤”
- [x] 保留状态文本解析作为兼容兜底
- [x] 子代理/委托工具活动继续汇总到同一张卡
- [x] 结果块与错误块支持结构化 code block 展示
- [x] 运行时长附着到步骤标题，尽量贴近官方展示节奏

## D. 交互与回调

- [x] 保留并强化 `card.action.trigger` 回调补丁
- [x] 确保审批按钮走 callback 返回而不是丢帧
- [x] 审批卡继续本地化
- [x] 保留官方式 typing reaction
- [x] 彻底禁止旧 ACK “OK” 持久 reaction
- [x] 发送消息时继续以用户消息为 reply target，保持单线程对话体验
- [x] 不再额外发送“OK”“正在处理中...”普通消息作为假进度

## E. 稳定性与风控

- [x] 新增官方式节流常量
  - CardKit：100ms
  - Patch：1500ms
  - reasoning/tool status：1500ms
- [x] 引入 flush controller
- [x] 处理 `230020` 频率限制
- [x] 处理 `230099 / 11310` 表格超限
- [x] 失败时禁止重复发送多条消息
- [x] 保持单消息更新体验
- [x] CardKit 创建失败后自动回退到 IM interactive card
- [x] CardKit 中间帧失败但已有 `original_card_id` 时，保留终态 CardKit 收尾机会
- [x] patch/card 更新失败时不重复刷屏，只记录日志并尽量保住最终回复

## F. 本地化与体验

- [x] 系统固定文案继续跟随系统语言
- [x] 卡片标题/按钮/提示尽量中英双语 i18n
- [x] 保持与 OpenClaw 官方插件一致的视觉节奏

## G. 验证与交付

- [x] `py_compile` 语法检查
- [x] WSL 内实际安装插件
- [x] 重启 5 个 gateway
- [x] 运行态 patch 状态冒烟
  - `feishu_ws_card_callbacks`
  - `feishu_typing_reaction`
  - `feishu_disable_ack_reaction`
  - `feishu_suppress_status_messages`
  - `feishu_exec_approval_localization`
  - `feishu_streaming_cards`
- [ ] 验证
  - 单消息回复
  - Typing reaction
  - CardKit 真流式
  - 工具步骤面板
  - 审批按钮点击
  - 终态收尾

> 说明：代码级、导入级、WSL 服务级验证已完成；最后这一组属于“真人 Feishu 端交互联调”，需要你从飞书真实发一条消息/触发一次审批来最终收口。

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

## 五、当前尚未声称“100%完成”的唯一部分

- 代码级对齐已经落地。
- 服务级加载已经落地。
- 还差的只有 **真人飞书端端到端联调**：
  - 真实发一条普通消息，确认是单条 reply 卡片持续更新
  - 真实触发一次审批按钮，确认 `card.action.trigger` 回调闭环
  - 若你希望做到“和官方截图完全一致”的最终验收，这一步必须经过真实飞书客户端验证
