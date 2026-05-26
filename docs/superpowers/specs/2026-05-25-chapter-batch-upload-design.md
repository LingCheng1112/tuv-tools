<!-- /autoplan restore point: C:\Users\Admin\.gstack\projects\LingCheng1112-tuv-tools\main-autoplan-restore-20260525-174740.md -->

# Design: Chapter Batch Upload Workspace

**日期**: 2026-05-25
**状态**: 已确认

## 概述

本设计将现有“条款批量导入”工作台重整为“条款批量上传”工作台。

目标不是推翻现有 `chapter_batch` 模块，而是在保留现有本地持久化、拆分、条款上传骨架的前提下，统一业务语义、状态机和交互流程，使工作台更符合用户实际操作路径：

`导入文档 -> 自动预处理 -> 自动拆分 -> 双击核对参数 -> 保存(可选) -> 上传`

这次重整明确约束如下：

- 页面、按钮、提示文案统一改为“上传”语义
- 文档导入后自动触发预处理和拆分，不再要求用户额外手动启动
- 拆分完成后本地自动生成一版参数和条款草稿
- 用户双击文档进入右侧抽屉核对参数
- 未修改参数时允许直接上传；修改后需要先保存，再上传
- “创建 chapter”降级为上传流程内部动作，不再作为显式业务状态暴露
- 抽屉必须从右侧滑入和滑出，不能再瞬间显示或消失

## 设计范围

### 本次包含

- 将侧边栏入口、页面标题和操作文案从“批量导入”统一为“批量上传”
- 重构 `chapter_batch` 的文档级和条款级显式状态
- 将上传前重复检查改为最终参数驱动，并支持逐条覆盖/跳过
- 将抽屉交互改为右侧滑入/滑出动画
- 保持现有本地 repository、service、executor、drawer 分层，不另起新模块

### 本次不包含

- 不修改现有 splitter 的拆分规则和清洗效果
- 不重做 SQLite 表结构主体，只在现有字段语义上重整
- 不引入新的后端接口
- 不在“覆盖重复条款”时同步修改后端已有条款字段
- 不将批量上传工作台改成多文档标签抽屉

## 信息架构与页面命名

### 页面命名

- 侧边栏入口：`条款批量上传`
- 页面标题：`条款批量上传`
- 抽屉主操作：`保存`、`上传`

所有用户可见提示文案统一改为“上传”语义，不再出现“待创建”“创建中”“开始执行”等旧表达。

### 主页面角色

主页面是“上传工作台”，不是“执行控制台”。

主列表只承担三类职责：

- 展示文档当前所处阶段
- 允许筛选、删除和批量上传
- 双击打开抽屉核对详情

### 主页面操作区

保留以下主操作：

- `导入文件`
- `导入文件夹`
- `批量上传`
- `删除记录`

移除或替换以下旧语义：

- `开始执行`
- 任何显式“创建”按钮
- 任何以“待创建/创建中”为中心的操作提示

## 业务主流程

### 自动流水线

用户导入文档后，系统自动执行：

1. 文档进入预处理
2. 预处理完成后自动继续拆分
3. 拆分完成后自动生成本地条款 docx 和参数默认值
4. 文档进入待确认阶段

### 用户核对与上传

用户双击文档后进入右侧抽屉核对信息：

- 如果参数无需修改，可直接上传
- 如果修改了参数，先点保存，再上传

这里“保存”和“上传”必须解耦：

- `保存` 只负责把抽屉中的修改落到本地
- `上传` 使用当前本地参数执行上传链路

## 新状态机

## 文档级显式状态

文档级只保留以下显式状态：

- `预处理中`
- `拆分中`
- `待确认`
- `待上传`
- `上传中`
- `已完成`
- `部分完成`
- `失败`

约束：

- 删除显式 `待创建`
- 删除显式 `创建中`
- 不保留独立的文档级 `已跳过`

### 状态含义

- `待确认`：系统已经自动匹配出一版参数，但还没经过用户显式保存确认
- `待上传`：用户已经确认并保存过当前参数版本，或经历过一次“全部重复跳过”后的可重试回退
- `上传中`：对用户只表示上传链路正在进行，不再拆出“创建中”
- `部分完成`：同一文档下，部分条款上传成功，部分条款失败或被跳过
- `失败`：真实异常导致上传未成功，例如接口失败、上传失败、预处理失败或拆分失败

### 特殊回退规则

如果一个文档在一次上传尝试中，全部条款都因为“重复且用户选择不覆盖”而未实际上传，则文档状态回退到 `待上传`，而不是记为“已跳过”或“失败”。

## 条款级显式状态

条款级只保留以下显式状态：

- `待上传`
- `上传中`
- `上传成功`
- `上传失败`
- `重复跳过`

约束：

- 不再暴露 `待创建`
- 不再暴露 `创建中`
- 不再暴露 `创建失败`

### 内部动作与显式状态分离

当某条没有重复且也没有 `chapterId` 时，上传流程内部仍然需要：

1. 创建 chapter
2. 上传 docx

但对用户只显示一个连续的 `上传中` 阶段，不额外暴露“创建中”。

## 重复判重与覆盖流程

### 判重时机

重复检查放在“点击上传”之后、真正执行上传之前。

原因：

- 用户可能在抽屉中修改 `term`
- 用户可能修改 `test_content`
- 用户可能修改 `specific_product`

只有在上传前用最终参数重新判定，结果才可信。

### 判重字段

重复仅在同一个 `folder_id` 下判断。

判重键为：

- `folder_id`
- `term`
- `test_content`
- `specific_product`

### `specific_product` 判定规则

`specific_product` 的比较规则为：

- 两边都为空：重复
- 一边为空一边非空：不重复
- 两边都非空且相同：重复
- 两边都非空且不同：不重复

这意味着 `specific_product` 是判重键的一部分，但空值只与空值相等。

### 逐条弹窗

命中重复时，采用逐条弹窗，而不是批量总弹窗。

弹窗至少展示：

- 条款号
- 测试内容
- 具体产品
- 归属文件夹
- “检测到已存在相同条款，是否覆盖原文档”的提示

按钮语义：

- `覆盖`
- `跳过`
- `取消本次上传`

### 用户选择行为

#### 覆盖

当用户选择 `覆盖`：

- 复用已存在条款的 `chapterId`
- 仅覆盖上传当前拆分出的 docx
- 不修改后端已有条款的字段内容
- 不创建新的 chapter

#### 跳过

当用户选择 `跳过`：

- 当前条款记为 `重复跳过`
- 继续处理当前文档的后续条款
- 不中止当前文档
- 不中止整批任务

#### 取消本次上传

当用户选择 `取消本次上传`：

- 中止当前文档本次上传
- 不影响其他尚未开始的文档

### 重复结果的长期语义

允许保留 `duplicate_flag` / `duplicate_reason` 作为辅助展示，但它们不是长期可信状态。

原因：

- 判重依赖最终编辑后的参数
- 判重依赖上传时刻的后端实时数据

因此应把：

- `duplicate_flag`
- `duplicate_reason`

视为本次上传前检查得到的临时结果；真正稳定的条款结果仍以 `上传成功`、`上传失败`、`重复跳过` 为准。

## 抽屉交互与滑动动画

### 打开方式

用户双击文档行后，抽屉必须从右侧滑入，不允许瞬间出现。

交互要求：

- 抽屉面板起始位置位于父容器右外侧
- 打开时从右侧平滑滑入
- 左侧主列表保留，并显示半透明遮罩
- 动画完成后再进入稳定交互态

### 关闭方式

抽屉关闭时必须滑出，不允许直接 `hide()`。

支持以下关闭入口：

- 点击左侧遮罩区
- 点击右上角关闭按钮
- 按 `Esc`

关闭行为：

- 面板向右滑出
- 动画结束后整个抽屉容器再隐藏

### 动画节奏建议

- 打开：180ms 到 220ms
- 关闭：150ms 到 180ms
- 缓动：`OutCubic / InCubic`

### 抽屉角色

抽屉是“单文档核对与上传面板”，不是多标签切换容器。

因此：

- 一次只服务一个文档
- 双击哪个文档，就打开哪个文档
- 批量上传入口继续放在主列表，而不是抽屉顶部切换多文档

### 抽屉顶部信息

保留以下状态信息用于核对：

- 文档名
- 当前文档状态
- 当前拆分方式
- 当前标准号

### 抽屉底部主操作

抽屉底部只保留两个主操作：

- `保存`
- `上传`

语义如下：

- `保存`：用户修改参数后，将当前抽屉内容落到本地
- `上传`：使用当前本地参数执行上传；如果用户没有修改，也允许直接上传

建议交互：

- 没有编辑变更时，`保存` 可禁用
- 文档处于 `预处理中 / 拆分中 / 上传中` 时，禁止编辑和上传

### 条款表格区

条款表继续承担核对和上传准备职责：

- 支持勾选上传
- 支持单条右键上传
- 支持查看重复和错误详情

重复原因和错误原因不再塞进主表格中，而是通过右键详情或辅助弹窗查看，保持表格信息密度可控。

## 参数确认语义

拆分完成后，本地已经自动匹配出一版参数。

用户打开抽屉时的心智模型应为：

- 系统已经先帮我填了一版
- 我先核对
- 不改就直接上传
- 改了就先保存，再上传

因此：

- 不能继续沿用“保存后再问是否上传”的旧交互
- `待确认` 不等于“禁止上传”
- 只有发生编辑修改时，`保存` 才成为必须动作

## 代码改造落点

### `src/tuv_tools/ui/main_window.py`

- 侧边栏入口文案改为 `条款批量上传`

### `src/tuv_tools/core/chapter_batch/models.py`

- 重定义文档级和条款级状态枚举
- 删除显式 `待创建 / 创建中`
- 重新定义可上传状态和运行态判断

### `src/tuv_tools/core/chapter_batch/service.py`

- 接入“导入后自动预处理 -> 自动拆分”
- 拆分完成后默认进入 `待确认`
- 上传前按最终参数执行重复判定
- 用新的 `specific_product` 规则替换旧判重逻辑

### `src/tuv_tools/core/chapter_batch/executor.py`

- 改为上传导向执行器
- 对外只暴露“上传中”语义
- 内部按三种路径执行：
  - 非重复：创建后上传
  - 重复覆盖：复用已有 `chapterId` 覆盖 docx
  - 重复跳过：记录为 `重复跳过` 并继续下一条

### `src/tuv_tools/core/chapter_batch/repository.py`

- 调整聚合规则
- 删除基于 `待创建` 的文档聚合分支
- 加入“全部重复跳过则回退待上传”的分支

### `src/tuv_tools/ui/views/chapter_batch_view.py`

- 页面和按钮文案统一改为“上传”语义
- 移除旧的“开始执行”语义
- 上传前统一收集最终参数、校验必填项并做逐条重复检查
- 支持 `待确认` 文档直接上传

### `src/tuv_tools/ui/widgets/chapter_batch_drawer.py`

- 为抽屉增加右侧滑入/滑出动画
- 关闭逻辑改为动画结束后再隐藏
- 增加脏状态检测，仅在有修改时启用保存

### `src/tuv_tools/ui/widgets/chapter_batch_clause_table.py`

- 调整条款状态展示文案
- 保留勾选上传和单条上传能力
- 继续通过右键详情查看重复和错误原因

## 测试策略

本次重整应先更新测试，再修改实现。

### `tests/test_chapter_batch_models.py`

- 验证新的显式状态集合
- 验证 `待确认` 允许直接上传
- 验证 `上传中` 属于运行态

### `tests/test_chapter_batch_service.py`

- 验证导入后自动预处理和自动拆分的状态流
- 验证拆分后自动参数回填
- 验证 `specific_product` 的四种判重场景
- 验证上传前最终判重而不是早判重

### `tests/test_chapter_batch_executor.py`

- 非重复条款：创建后上传
- 重复覆盖：复用已有 `chapterId`，不创建，只上传
- 重复跳过：当前条跳过，后续继续
- 全部重复跳过：文档回退 `待上传`
- 部分成功部分跳过：文档为 `部分完成`
- 异常失败和取消时的文档聚合规则

### `tests/test_chapter_batch_view.py`

- 入口标题和按钮文案改为“批量上传”
- 双击后抽屉进入打开动画，而不是直接显示
- 点击遮罩、点击关闭按钮、按 `Esc` 触发关闭动画
- 未修改参数可直接上传
- 修改后保存才真正落库
- 上传前逐条重复弹窗流程

## 风险与约束

### 主要风险

- 现有 view / repository / executor 中存在大量 `待创建 / 创建中` 分支，清理不完整会留下状态残影
- 抽屉动画会改变 `isVisible()`、`show()`、`hide()` 的时序，需同步更新视图测试
- 自动预处理接入后，批量上传工作台将正式依赖 preparing 流水线，必须复用现有稳定实现，不能再引入第二套线程语义

### 约束

- 不改变现有拆分和清洗结果
- 不覆盖后端已有条款的元数据字段
- 不把重复判断前置到拆分完成时刻

## 推荐实施顺序

1. 先更新设计文档与状态约束
2. 先改状态相关测试
3. 再改 `models / repository / executor`
4. 再改 `view / drawer / clause_table`
5. 最后接自动预处理流水线
6. 执行 `pytest tests/test_chapter_batch_* -q`

## 自检结论

本设计已完成以下一致性约束：

- 已移除显式 `待创建 / 创建中`
- 已明确 `待确认` 可直接上传
- 已明确“修改后才需要保存”
- 已明确重复覆盖只覆盖 docx，不覆盖条款字段
- 已明确逐条重复弹窗
- 已明确“全部重复跳过”回退 `待上传`
- 已明确抽屉必须滑入/滑出

当前设计没有保留占位符、待定项或相互冲突的流程定义。

<!-- AUTONOMOUS DECISION LOG -->
## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|-----------|-----------|----------|----------|
| 1 | Phase 0 | 审查对象固定为当前批量上传 spec，而不是回退到 2026-05-24 的批量导入设计 | AUTO_DECIDE | P6 | 用户已明确以 `2026-05-25-chapter-batch-upload-design.md` 为当前方案，并在该基础上触发 `/autoplan`，所以审查必须围绕最新业务语义重整展开 | 旧的批量导入设计稿 |
| 2 | Phase 0 | UI scope = yes，进入 Design Review | AUTO_DECIDE | P6 | 当前方案明确覆盖页面命名、抽屉动效、状态展示、按钮语义、表格交互和双击查看流程，属于实质性 UI/UX 范围 | 跳过设计评审 |
| 3 | Phase 0 | DX scope = no，Phase 3.5 预设跳过 | AUTO_DECIDE | P5 | 该方案面向桌面端操作人员的业务上传流程，不是开发者产品、SDK、CLI、开放 API 或文档平台，Developer Experience 不是主问题域 | 运行完整 DX review |

## Phase 1 CEO Review

### Review Mode

`SELECTIVE EXPANSION`

理由：当前方案的主目标不是扩大产品边界，而是把已经确认的业务重心收紧、澄清并补齐风险。允许吸收少量高价值增强，但不引入新的业务面。

### System Audit

- 当前不是从零设计，而是在既有 `chapter_batch` 骨架上重写语义。
- 现状代码仍以“批量导入 + 创建/上传两阶段外显状态”为核心：
  - `models.py` 仍保留 `PENDING_CREATE / CREATING / SKIPPED / CREATE_FAILED`
  - `service.py` 仍在保存阶段判重，且 `save_confirmed_documents()` 保存后会回到 `PENDING_CREATE`
  - `executor.py` 仍显式执行 `CREATING -> UPLOADING`
  - `repository.py` 聚合规则仍以 `PENDING_CREATE` 为关键分支
  - `chapter_batch_view.py` 仍是“条款批量导入”，按钮仍有“批量确认 / 开始执行”，上传前会强制保存并触发旧判重
  - `chapter_batch_drawer.py` 仍是直接 `show()/hide()`，没有右侧滑动开闭
- `preparing` 流水线已在仓库内存在，但当前 `chapter_batch` 尚未真正与其打通；这不是现成能力切换，而是一次真实的新接线。

### Step 0 / Premise Challenge

- 该方案最容易被误判成“文案替换 + 状态名替换 + 动效优化”。这是假前提。
- 真问题是：当前模块的业务中心仍然是“创建条款后上传文档”，而用户已把心智模型改成“导入后自动处理，用户核对后上传，创建只是上传内部细节”。
- 如果只改文案而不改状态机、判重时机、抽屉交互和聚合规则，最终会得到一个表面叫“批量上传”、内部仍按“批量导入”运转的伪重构。

### What Already Exists

- 已有本地 repository、service、executor、view、drawer、clause table 五层骨架，不需要新建模块。
- 已有条款级 docx 拆分与本地参数落库能力，可承接“先自动匹配，再人工核对”的目标。
- 已有后端查询条款列表和 docx 上传接口基础，可承接“上传前判重”和“命中重复后覆盖 docx”。
- 已有 `preparing` 子系统，可被复用为自动预处理阶段。

### Dream State Delta

从 CEO 视角，这份 spec 距离“10 分版本”的差距不在功能多少，而在“有没有把同一条业务主线讲透”：

- 现在的理想产品描述已经正确：`导入 -> 预处理 -> 拆分 -> 核对 -> 上传`
- 但实现风险仍集中在 4 个地方：
  - 预处理接入仍是净新增链路，不是轻量开关
  - 上传前判重与本地自动参数之间的主次关系，还需要明确谁是最终真相
  - 抽屉动画和业务状态重构同时推进，耦合过深，容易让交互问题掩盖业务回归
  - 旧 SQLite 状态值仍然存在，本地旧数据如何过渡没有写清楚

### NOT in Scope

- 不改 splitter 的拆分规则和清洗结果
- 不改后端接口契约
- 不改覆盖重复时的后端条款元数据
- 不把“重复判定”前置到拆分完成时
- 不把本轮扩展成新的批量工作台或新存储模型

### Error & Rescue Registry

| Surface | Failure | Current Gap | Required Rescue |
|---|---|---|---|
| 自动预处理接入 | `preparing` 失败或中断 | spec 只描述了 happy path，没有明确文档级失败落点 | 文档需进入 `失败`，并保留可重试或重新导入入口 |
| 上传前判重 | 后端查询失败或返回不全 | 旧逻辑把判重当保存前流程，错误语义偏旧 | 本轮应把它定义为上传前阻断错误，不能把失败误判成无重复 |
| 重复覆盖 | 找到重复条款但缺失可复用 `chapterId` | spec 已要求复用已有条款，但未写异常兜底 | 必须显式落入 `上传失败`，不能静默退化为新建 |
| 用户取消重复弹窗 | 当前文档上传中止 | 旧逻辑没有“中止当前文档但不影响其他文档”的统一语义 | 本轮需固定为文档级取消，不波及其他待处理文档 |
| 全部重复跳过 | 没有任何条款实际上传 | 旧聚合只有 `SKIPPED/PENDING_CREATE` 语义 | 必须回退 `待上传`，避免误标完成或失败 |

### Failure Modes Registry

| Codepath | Failure Mode | Rescued? | Tested? | User Sees? | Logged? |
|---|---|---:|---:|---|---:|
| `service.import_and_split_documents()` | 预处理接入失败 | N | N | 当前 spec 未明示 | N |
| `service.save_confirmed_documents()` | 保存后错误回到 `待创建` | N | 现有测试锁定旧语义 | 状态语义错乱 | N |
| `view._on_upload_requested()` | 上传前被强制保存 | N | 现有视图测试锁定旧逻辑 | 用户无法“未修改直接上传” | N |
| `view._resolve_duplicate_candidates()` | 判重时机仍在保存期 | N | 现有测试锁定旧逻辑 | 用户看到过早冲突结果 | N |
| `executor.run_documents()` | 继续外显 `创建中` | N | 现有执行器测试锁定旧语义 | 状态不符合上传心智 | N |
| `repository.reaggregate_document()` | 全重复跳过后无法回退 `待上传` | N | N | 文档终态错误 | N |
| `drawer.hide()` | 抽屉瞬时关闭破坏动效预期 | N | 现有控件测试锁定旧逻辑 | 交互割裂 | N |

### Opinionated CEO Call

- 这份方案值得继续，不需要回炉重写。
- 但它本质上是“模块级语义重整”，不是小范围 UI polish。
- 最关键的风险不是 scope 太大，而是把多个互相关联的语义改动误当成“逐个小修”。如果这样执行，状态、上传、判重、抽屉四条线会出现半新半旧的杂交状态。

### CEO Consensus Table

| Topic | 本地审查 | Outside Voice: Codex | Outside Voice: Claude | Consensus |
|---|---|---|---|---|
| 这是否只是轻量改动 | 否，是模块级语义重整 | 否 | 否 | 一致 |
| 自动预处理是否是净新增 | 是 | 是 | 间接同意 | 一致 |
| 抽屉动画是否应视为单独 taste decision | 是 | 是 | 是 | 一致 |
| 是否需要重新定义旧状态兼容 | 是 | 隐含提出 | 明确提出 | 一致 |
| `specific_product` 第四判重维度是否已充分论证 | 已被用户业务明确锁定，不再争论规则 | 未重点质疑 | 明确质疑收益 | 视为已定前提，不再改规则 |

### Completion Summary

+--------------------------------------------------------------+
|                  PHASE 1 CEO REVIEW SUMMARY                  |
| Review mode          | SELECTIVE EXPANSION                  |
| System Audit         | 现状仍是批量导入语义                 |
| Premise challenge    | 不是文案替换，而是状态机重心迁移     |
| Scope proposals      | 3 proposed, 0 accepted as new scope  |
| Error/rescue registry| 5 surfaces, 5 gaps                   |
| Failure modes        | 7 total, 7 critical gaps             |
| Unresolved decisions | 3                                    |
| Recommendation       | 保持 scope，优先收紧执行顺序         |
+--------------------------------------------------------------+

### Phase 1 Decisions Added

| 4 | Phase 1 | CEO 模式采用 `SELECTIVE EXPANSION`，不新增业务 scope，只暴露实现风险和 taste decisions | AUTO_DECIDE | P5 | 用户已经锁定核心规则，本轮 `/autoplan` 目标是评审和收紧，而不是扩容 | `SCOPE EXPANSION` |
| 5 | Phase 1 | 将“自动预处理接入是 net-new 链路”标记为高风险，而不是既有能力切换 | AUTO_DECIDE | P1 | 当前 `chapter_batch` 仅同步导入后拆分，尚未真正接通 `preparing` 子系统 | 将其视作低风险接线 |
| 6 | Phase 1 | 将“抽屉动画是否独立拆批”保留为 taste decision，不在 CEO 阶段强制改 scope | AUTO_DECIDE | P3 | 动画与业务状态可拆可不拆，影响的是交付节奏，不改变产品语义 | 在 CEO 阶段直接强制拆成两个方案 |
| 7 | Phase 1 | 将旧状态兼容和本地历史数据过渡列为必须在 Eng 阶段落明的风险点 | AUTO_DECIDE | P2 | 当前 spec 没有写旧 SQLite 状态如何映射，会直接影响可执行性 | 忽略历史数据兼容 |

## Phase 2 Design Review

### Design Scorecard

| Dimension | Score | What Keeps It From 10 |
|---|---:|---|
| 信息架构清晰度 | 8/10 | 主流程已清晰，但“保存”和“上传”的节拍仍需在页面动作上彻底解耦 |
| 交互节奏 | 6/10 | 现状代码仍是保存时判重、上传前强制保存，和设计目标正面冲突 |
| 状态可理解性 | 7/10 | 新状态机定义清楚，但旧状态兼容、取消语义、全部重复跳过回退仍未落到同一叙事里 |
| 视觉一致性 | 7/10 | 右侧抽屉滑入滑出方向已明确，但遮罩、关闭和稳定态时序还没写成明确的 UI contract |
| 错误表达 | 6/10 | 重复、失败、取消、覆盖 4 种结果已定义，但界面呈现层次还不够具体 |
| 可恢复性 | 7/10 | “待上传”回退语义正确，但预处理失败、判重失败、覆盖失败后的重试入口未明确 |
| 认知负担 | 8/10 | 用户主线已经比旧版更自然，但如果继续保留旧按钮语义，认知负担会反弹 |

### Litmus Scorecard

- 用户是否一眼能看出当前主线是“上传”而不是“创建条款”：NO
- 用户是否能在未修改参数时直接上传：YES（设计目标），NO（现状实现）
- 用户是否能理解“保存”和“上传”是两个独立动作：YES（设计文本），NO（现状实现）
- 用户是否能在重复冲突里明确知道自己是在“覆盖文档”而不是“覆盖条款元数据”：YES
- 用户是否能通过状态理解一个文档为什么没有完成：PARTIAL
- 抽屉是否符合“从右侧实体滑入的核对面板”预期：YES（设计目标），NO（现状实现）
- 是否存在明显把业务语义和动效耦在一起的风险：YES

### Design Findings

1. 最大结构问题不是视觉，而是操作节奏。只要 `_on_upload_requested()` 仍先触发 `_save_documents()`，整个“未修改可直接上传”的设计就只是文本承诺。
2. 抽屉动画是对的，但它不应背负业务语义修正责任。动画应表达“进入核对上下文”，而不是补偿保存/上传流程混乱。
3. 条款表保留右键查看重复和错误原因是合理的；如果把重复原因继续压进主表，会再次让表格承担过多解释负担。

### Design Recommendations

- 在设计层把按钮语义固定为：
  - `保存`：仅对 dirty 参数落本地
  - `上传`：基于当前本地值直接执行，dirty 时先阻止并提示先保存，未 dirty 时可直传
- 抽屉开闭 contract 需要最少包含：
  - 打开：从右向左滑入
  - 关闭：遮罩 / X / Esc 三入口统一进入滑出动画
  - 结束：动画完成后再真正隐藏容器
- 文档行和条款行状态展示要共享同一上传叙事，避免文档说“待上传”，条款却还说“待创建”。

### Design Taste Decisions

- `Taste Decision A`：抽屉动画是否与状态机重构同一批交付
  - 结论：允许同批实施，但设计上必须把它标成可拆分关注点，不得与业务语义互相依赖
- `Taste Decision B`：重复冲突是否保留逐条弹窗而不是聚合弹窗
  - 结论：保持逐条弹窗，因为这是用户已明确锁定的业务交互，不再替换

### Design Completion Summary

| Item | Result |
|---|---|
| Overall design score | 7/10 |
| Biggest gap | 操作节奏与实现现状冲突 |
| Confirmed strengths | 主流程顺序、状态目标、重复覆盖语义 |
| Confirmed weaknesses | 保存/上传耦合、抽屉 contract 未固化、失败恢复层次不足 |
| Unresolved design decisions | 1 taste decision, 0 product-direction blockers |

### Phase 2 Decisions Added

| 8 | Phase 2 | 设计总评定为 `7/10`，主缺口为操作节奏而非视觉样式 | AUTO_DECIDE | P1 | 当前 spec 已有正确业务顺序，但尚未把动作边界写成可执行 UI contract | 把设计问题归因为纯视觉 |
| 9 | Phase 2 | “抽屉动画是否拆批”保留为 taste decision，不作为阻断方案通过的前置条件 | AUTO_DECIDE | P3 | 该问题影响交付组织方式，不影响业务规则正确性 | 把动画拆批列为强制要求 |

## Phase 3 Engineering Review

### Architecture

当前最合理的工程落点仍然是保留 `chapter_batch` 分层，但按“上传优先”重写状态流，而不是重建模块。

```text
User
  |
  v
chapter_batch_view
  |  import / open drawer / save / upload
  v
chapter_batch_service
  |  import -> preparing -> split -> autofill local params
  v
chapter_batch_repository
  |  persist docs/clauses/status/duplicate temp fields
  ^
  |
chapter_batch_executor
  |  upload orchestration
  |-- non-duplicate -> create chapter -> upload docx
  |-- duplicate+overwrite -> reuse chapterId -> upload docx
  `-- duplicate+skip -> mark clause skipped, continue
```

### What Already Exists

- `models.py` 已具备状态枚举与 dataclass 载体
- `service.py` 已具备导入、拆分、自动参数落库主链路
- `executor.py` 已具备文档级串行执行、条款级顺序处理框架
- `repository.py` 已具备文档/条款聚合入口
- `view/drawer/clause_table` 已具备页面、抽屉、条款表交互骨架

### NOT in Scope

- 不引入新的 repository 或新的数据库表
- 不重写 splitter / preparing 本体
- 不新增后台接口
- 不在本轮把逐条弹窗重构成批量冲突中心

### Main Engineering Risks

1. 旧状态枚举是横切关注点。`models/service/executor/repository/view/tests` 都受影响，不能局部替换。
2. `service.save_confirmed_documents()` 与 `view._on_upload_requested()` 当前共同锁定旧保存节奏，是本轮最大行为冲突点。
3. `repository.reaggregate_document()` 决定了所有终态，若不先改这里，任何上层语义都可能被旧聚合回滚。
4. 预处理接线会引入线程/状态回调问题，必须复用已有 `preparing` 能力，而不是复制第二套 worker 语义。

### Recommended Implementation Order

1. 先改测试目标，移除对 `PENDING_CREATE / CREATING` 的依赖
2. 再改 `models.py`，统一新状态枚举和 helper
3. 再改 `repository.py`，重写聚合和“全部重复跳过回退待上传”
4. 再改 `service.py`，修正保存语义、上传前判重、`specific_product` 比较
5. 再改 `executor.py`，把创建动作降为上传内部步骤
6. 最后改 `view/drawer/clause_table`，对齐上传语义和滑动抽屉
7. 最后接入自动预处理流水线并做全链路回归

### Error & Rescue Coverage

| Area | Needed Test |
|---|---|
| 状态机 | 保存后不再回 `待创建`；`待确认` 可直接上传；`上传中` 为唯一运行态外显语义 |
| 判重 | `specific_product` 四种组合；上传前最终判重；重复覆盖复用 `chapterId`；重复跳过继续后续条款 |
| 聚合 | 全重复跳过回 `待上传`；部分成功部分跳过为 `部分完成`；失败与取消终态正确 |
| 抽屉 | 打开/关闭动画 contract；遮罩/X/Esc 三入口；dirty 保存启用条件 |
| 预处理 | 导入后自动进入预处理；预处理成功后自动拆分；预处理失败终态正确 |

### ASCII Test Coverage Diagram

```text
Document import
  -> preparing start
  -> preparing success
  -> split success
  -> autofill params
  -> pending_confirm
        |
        +-> no edit -> upload directly
        |
        +-> edit -> save -> pending_upload -> upload

Upload branch
  -> duplicate check
        |
        +-> no duplicate -> create -> upload -> success
        +-> duplicate overwrite -> reuse chapterId -> upload -> success
        +-> duplicate skip -> skipped -> continue next clause
        +-> duplicate dialog cancel -> cancel current doc upload

Document aggregation
  -> all clause success -> completed
  -> mixed success/skip/fail -> partial_complete
  -> all skip this round -> pending_upload
  -> any real failure without success -> failed
```

```text
COVERAGE TARGET

Code paths:
  1. save without edits is no-op
  2. upload from pending_confirm without save
  3. upload after saved edits
  4. duplicate overwrite path
  5. duplicate skip path
  6. duplicate dialog cancel path
  7. all-skipped document reaggregate path
  8. preparing failure path
  9. upload failure path

User flows:
  A. import one doc and upload unchanged
  B. import one doc, edit, save, upload
  C. duplicate overwrite one clause
  D. skip duplicate and continue later clauses
  E. all clauses skipped then doc returns pending_upload
  F. close drawer via mask/X/Esc
```

### Failure Modes

| Failure Mode | Planned Handling |
|---|---|
| 保存后仍回旧状态 | 先改测试，再改状态 helper，阻断回归 |
| 上传前强制保存 | 拆开 save 与 upload 入口，dirty 才要求保存 |
| 旧状态污染历史文档 | 定义 repository 读取时的兼容映射或一次性迁移策略 |
| 预处理线程语义分叉 | 复用现有 `preparing` 基础设施，不复制 worker |
| 判重依赖字段不一致 | 明确 `folder_id + term + test_content + specific_product` 为唯一判重键 |
| 覆盖路径错误修改条款元数据 | executor 中将覆盖路径限制为 docx 上传，不调用 metadata update |

### Parallelization

Sequential implementation, no parallelization opportunity.

原因：绝大多数改动都落在同一条 `chapter_batch` 状态主链路上，`models/repository/service/executor/view/tests` 彼此强依赖，先后顺序比并行更重要。

### Engineering Completion Summary

+--------------------------------------------------------------+
|                 PHASE 3 ENGINEERING SUMMARY                  |
| Architecture review   | 状态主线需保留单模块重写            |
| Code quality risk     | 旧状态横切 6+ 文件                  |
| Test gaps             | 预处理、判重时机、聚合回退、动画    |
| Performance risk      | 低，主要是流程正确性风险            |
| Issues found          | 6                                    |
| Parallelization       | Sequential only                      |
+--------------------------------------------------------------+

### Phase 3 Decisions Added

| 10 | Phase 3 | 工程实施顺序固定为 `tests -> models -> repository -> service -> executor -> ui -> preparing integration` | AUTO_DECIDE | P2 | 本轮最大风险是旧状态横切污染，必须从最底层约束和聚合先收口 | 先改 UI 再回填底层 |
| 11 | Phase 3 | `repository.reaggregate_document()` 列为优先级最高的状态收口点 | AUTO_DECIDE | P1 | 所有文档终态最终都要回到聚合规则，若此处不先改，上层行为会被旧分支吞回 | 只改 view/service/executor |
| 12 | Phase 3 | 本轮实施按顺序推进，不建议并行拆 lane | AUTO_DECIDE | P5 | 同一模块跨层语义重整，边界不适合多人并行或多 lane 同步 | 并行拆分 UI/状态机/预处理 |

## Phase 3.5 DX Review

Phase 3.5 skipped — no developer-facing scope detected.

## Phase 4 Final Approval Gate

### Plan Summary

这份 spec 可以继续推进，但必须按“模块级语义重整”执行，而不是按零散 UI 修改执行。真正需要落地的不是更多规则，而是让现有已确认规则在状态机、判重时机、抽屉交互和聚合逻辑上保持一致。

### Decisions Made

- 评审模式采用 `SELECTIVE EXPANSION`
- 保持当前业务 scope，不新增功能面
- 认定自动预处理接入是 net-new 高风险链路
- 认定抽屉动画属于 taste decision，不阻断方案通过
- 认定旧状态兼容必须在工程实现前写清
- 认定实施顺序必须串行，不建议并行拆 lane

### User Challenges

无。当前 CEO / Design / Eng 结论没有要求用户改变已锁定业务规则，只要求在实现时严格遵守这些规则。

### Your Choices

- `Choice A`: 抽屉动画与状态机重构是否同批交付
  - 当前建议：可以同批，但在实现计划中保持关注点分离
- `Choice B`: 是否把历史 SQLite 状态兼容写成即时映射还是一次性迁移
  - 当前建议：优先即时兼容映射，减少一次性迁移风险

### Review Scores

| Review | Score / Verdict |
|---|---|
| CEO Review | Pass with risk tightening |
| Design Review | 7/10 |
| Engineering Review | Pass with execution-order constraints |
| DX Review | Skipped |

### Cross-Phase Themes

- 当前最大问题是“新文案覆盖旧语义”
- 保存、上传、判重三者必须彻底解耦
- 旧状态兼容是隐藏成本，不处理会直接反噬新流程
- 抽屉动效是交互质量问题，但不能替代业务逻辑修正

### Deferred Items

- 是否未来把逐条重复弹窗升级为聚合冲突工作流
- 是否未来把抽屉动画单独沉淀为通用侧栏组件
- 是否未来为旧状态做一次性数据迁移脚本

### Final Gate Verdict

Approved for implementation planning, with constraints:

1. 不改变既定业务规则和清洗/拆分效果。
2. 先修正测试与底层状态语义，再进入 UI 和预处理接线。
3. 明确历史状态兼容策略后，才适合进入真实重构执行。
