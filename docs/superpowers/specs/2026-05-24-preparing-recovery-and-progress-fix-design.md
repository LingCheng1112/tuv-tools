# Design: Preparing Recovery and Progress Fix

**日期**: 2026-05-24
**状态**: 待审阅

## 概述

本设计覆盖三个已确认的修复目标：

1. 修正 `PreparingWorker.stop()` 的停止语义，使关闭窗口时只完成当前文档，未开始的预处理队列项不再继续执行。
2. 修正拆分进度在多表文档中的回退问题，并保证 UI 进度百分比单调不下降。
3. 将 `pywin32` 调整为平台条件依赖，避免非 Windows 环境在安装阶段直接失败。

同时补上预处理恢复交互：应用启动时若发现残留的 `preparing` 文档，必须弹窗询问用户是否继续后台预处理；若用户拒绝，这些文档进入新的专属状态，并只能通过显式单文档动作继续推进。

## 背景与问题

当前实现存在两个明确缺陷：

- `PreparingWorker.stop()` 只是把 `_STOP` 哨兵压到队尾，若队列里已经有多个文档，关闭窗口后后台仍会继续处理剩余项。这与“处理完当前文档后退出”的注释和用户预期不一致。
- `build_sections()` 在每张表内分别发送 `splitting_tables` 进度事件，`SplitProgressMapper` 又默认同一 phase 的 `current/total` 单调递增，因此多表文档会出现整体百分比回退。

此外，预处理状态目前只覆盖“进行中/成功/失败”，没有表达“上次退出后残留，且用户本次拒绝恢复”的专属语义，导致后续列表行为和拆分入口无法清晰约束。

## 目标

### 功能目标

- 启动时识别残留 `preparing` 文档，并在进入正常交互前弹窗确认是否继续后台预处理。
- 用户拒绝恢复时，文档进入新的专属状态 `prepare_paused`。
- `prepare_paused` 默认不能参与批量拆分，但允许用户对单个文档执行：
  - `继续预处理`
  - `跳过预处理并拆分`
- 关闭窗口时，正在执行的预处理文档可以完成，尚未开始的队列项不再继续。
- 多表文档的拆分进度在 UI 上必须保持单调不下降。

### 非目标

- 本次不引入新的数据库表，也不实现通用的持久化任务队列。
- 本次不增加“全局手动停止预处理”独立按钮；只覆盖关闭窗口后的退出语义和启动恢复语义。
- 本次不改变 DOCX 预处理本身的替换逻辑。

## 方案比较

### 方案 A：扩展现有状态机并在 UI 层恢复队列（推荐）

在现有 `imported_documents.status` 上新增 `prepare_paused`，启动时扫描残留 `preparing`，通过确认框决定恢复还是暂停。关闭窗口时通过 worker 内部停止标记让未开始项留在数据库中，等待下次恢复。

优点：

- 与现有 `DatabaseManager`、`SplitterView`、`DocumentTable` 结构兼容。
- 不需要数据库迁移新表，改动面集中且可回归测试。
- 能完整表达“恢复被拒绝”的语义。

缺点：

- 状态枚举比当前略复杂。
- 启动恢复逻辑必须写清楚，避免 UI 初始化阶段重复触发。

### 方案 B：新增预处理任务表并持久化队列

为预处理建立独立任务表，记录排队顺序、是否已开始、是否恢复、是否跳过。

优点：

- 状态表达最完整，后续扩展空间大。

缺点：

- 对当前问题明显偏重。
- 需要额外迁移、更多测试和更多 UI/数据同步代码。

### 方案 C：复用现有状态并把恢复拒绝原因写入 `error_message`

优点：

- 实现最省。

缺点：

- 语义混乱，无法区分真正失败与用户拒绝恢复。
- 列表可选中规则和“跳过预处理并拆分”入口都会变得不清晰。

推荐采用 **方案 A**。

## 设计

### 1. 状态机设计

保留现有状态：

- `pending`
- `preparing`
- `processing`
- `completed`
- `failed`
- `cancelled`

新增状态：

- `prepare_paused`

状态语义：

- `preparing`：文档已导入，正在或应当进入后台预处理。
- `prepare_paused`：启动恢复时用户拒绝继续后台预处理的残留文档。
- `pending`：预处理完成后可正常参与拆分。

关键迁移：

- 导入文档：`pending -> preparing`
- 预处理成功：`preparing -> pending`
- 预处理失败：`preparing -> failed`
- 启动恢复时用户拒绝：`preparing -> prepare_paused`
- 用户选择继续预处理：`prepare_paused -> preparing`
- 用户选择跳过预处理并拆分：状态不先改成 `pending`，而是以显式单文档入口直接放行进入本次拆分流程
- 跳过后拆分成功：`prepare_paused -> completed`
- 跳过后拆分失败：`prepare_paused -> failed`

### 2. PreparingWorker 停止语义

`PreparingWorker` 需要从“哨兵排队”改成“显式停止标记 + 当前任务后退出”。

建议调整：

- 新增 `_stop_requested: bool = False`
- `stop()` 只设置 `_stop_requested = True`
- `run()` 主循环在每次准备取新任务前检查 `_stop_requested`
- 如果已经开始处理某个文档，则允许当前文档执行到结束；当前文档完成后若 `_stop_requested` 为真，立即退出，不再消费下一个队列项

这意味着：

- 关闭窗口时不会强杀当前 Word 操作
- 但不会再继续消耗剩余队列

### 3. 残留预处理恢复流程

触发时机放在 `SplitterView` 初始化加载文档之后，并确保每次视图初始化只触发一次。

流程：

1. 查询所有 `status == preparing` 的文档
2. 若无残留，直接返回
3. 若有残留，弹出模态确认框：
   - 标题：`检测到未完成的预处理任务`
   - 文案说明这些文档来自上次退出时未完成的后台预处理
   - 显示数量；文件名列表只展示前若干项，避免弹窗过长
   - 按钮：`继续处理` / `暂不处理`
4. 用户选择：
   - `继续处理`：保持这些文档为 `preparing`，重建恢复队列，重新交给 `PreparingWorker`
   - `暂不处理`：统一更新为 `prepare_paused`
5. 恢复时若发现源文件已不存在：
   - 不入恢复队列
   - 直接更新为 `failed`
   - `error_message` 写入明确原因

### 4. DocumentTable 交互设计

#### 4.1 状态显示

`STATUS_LABELS` 新增：

- `prepare_paused`: `已暂停预处理`

#### 4.2 选择规则

不可参与普通选择/批量拆分的状态：

- `preparing`
- `processing`
- `prepare_paused`

因此 `is_selectable_document_status()` 需要把 `prepare_paused` 也纳入不可选集合。

#### 4.3 右键菜单

对 `prepare_paused` 文档新增两个显式动作：

- `继续预处理`
- `跳过预处理并拆分`

普通“拆分此文档”入口不对 `prepare_paused` 显示，避免用户误把它当成已完成预处理文档。

### 5. SplitterView 行为设计

#### 5.1 启动恢复

新增一个初始化阶段方法，例如 `_resume_preparing_if_needed()`，在 `_load_documents()` 之后调用。

#### 5.2 继续预处理

当用户从右键菜单选择 `继续预处理`：

- 更新该文档状态为 `preparing`
- 就地刷新行状态
- 确保 `PreparingWorker` 已启动
- 将该文档加入后台预处理队列

#### 5.3 跳过预处理并拆分

这是单文档显式入口，必须二次确认。

确认框文案应明确说明：

- 该文档尚未完成预处理
- 继续拆分可能导致复选框未统一
- 此操作仅对当前文档本次拆分放行

确认后行为：

- 不先把数据库状态改成 `pending`
- 直接构造仅包含该文档的拆分任务，允许其进入 `SplitWorker`
- `SplitWorker` 开始时该文档状态照常更新为 `processing`
- 完成/失败后按正常拆分结果回写

为避免污染普通批量拆分路径，建议为 `SplitterView` 增加一个单独的显式入口方法，而不是在 `checked_ids()` 批量逻辑里塞条件分支。

### 6. 进度修复设计

根因在于 `splitting_tables` 事件是“每张表局部计数”，但 UI 把它当“全文件同 phase 全局计数”来映射。

推荐双层修复：

#### 6.1 Core 侧修正事件语义

在 `build_sections()` 开始处理表格前，先统计所有参与 `splitting_tables` 的表格总行数；然后在逐表处理时发送“全文件累计已处理表格行数 / 总行数”。

实现方式可以是：

- `build_sections()` 预扫描 table blocks，累计总行数
- `_split_table_into_sections()` 接收一个累计偏移量或 progress context
- 对外发送的 `CoreProgressEvent("splitting_tables", ...)` 使用全局累计值，而不是表内局部值

这样 `SplitProgressMapper` 看到的 `current/total` 就重新具有单调语义。

#### 6.2 UI 侧防御性单调保护

`SplitProgressMapper` 额外保存上一次发出的 `overall_percent`，若新值更小，则返回上一次值。

这层保护不是主修，只是兜底，避免未来新增 phase 或异常事件再次导致进度条倒退。

### 7. 依赖声明设计

`pyproject.toml` 中的 `pywin32` 依赖改为平台条件依赖：

```toml
"pywin32>=305; platform_system == 'Windows'"
```

这样可以保证：

- Windows 下安装行为保持不变
- 非 Windows 环境可以安装并运行纯逻辑测试、代码审查、静态检查

该改动依赖于现有懒导入设计继续成立，即：

- 导入 `tuv_tools.core.preparing` 不能在模块加载时触发 `win32com.client`
- 非 Windows 环境仅在真正运行 Word 自动化时才会受限

## 文件变更范围

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/tuv_tools/core/preparing/worker.py` | 修改 | 修正 stop 语义 |
| `src/tuv_tools/ui/views/splitter_view.py` | 修改 | 启动恢复、继续预处理、跳过预处理拆分、恢复弹窗 |
| `src/tuv_tools/ui/widgets/document_list.py` | 修改 | `prepare_paused` 状态显示、选择规则、右键菜单 |
| `src/tuv_tools/core/splitter/parsing.py` | 修改 | `splitting_tables` 进度改为全局累计 |
| `src/tuv_tools/ui/views/splitter_progress.py` | 修改 | 进度百分比单调保护 |
| `src/tuv_tools/core/splitter/ui_helpers.py` | 修改 | 状态标签、可选中规则 |
| `src/tuv_tools/config/database.py` | 可能修改 | 若需要新增轻量查询 helper，可集中放在这里 |
| `tests/test_preparing_worker.py` | 修改 | stop 语义回归 |
| `tests/test_document_table.py` | 修改 | `prepare_paused` 行为回归 |
| `tests/test_splitter_view.py` | 修改 | 恢复弹窗与显式单文档动作回归 |
| `tests/test_splitter_progress.py` | 修改 | 多表进度单调不下降 |
| `pyproject.toml` | 修改 | 平台条件依赖 |

## 测试计划

### 单元测试

- `test_preparing_worker.py`
  - stop 后仅允许当前文档完成
  - stop 后剩余未开始项不再触发 `doc_prepared`
- `test_document_table.py`
  - `prepare_paused` 状态标签存在
  - `prepare_paused` checkbox 禁用
  - `prepare_paused` 不参与全选
- `test_splitter_progress.py`
  - 多表 `splitting_tables` 事件映射后整体百分比单调不下降
  - `completed` 仍然收敛到 100%

### 视图级回归

- `test_splitter_view.py`
  - 启动时无残留 `preparing` 不弹窗
  - 启动时有残留，用户选择继续处理时会恢复队列
  - 用户拒绝时状态变为 `prepare_paused`
  - `跳过预处理并拆分` 需要确认框

### 集成验证

- `pytest -q`
- 手工验证建议：
  - 导入多份文档后立即关闭窗口，重启时验证恢复弹窗
  - 验证拒绝恢复后列表状态与右键菜单
  - 用多表文档观察进度条不再倒退

## 风险与约束

- `prepare_paused` 是新的状态分支，所有基于 `status` 的筛选和文案映射都要检查，避免遗漏。
- 启动恢复弹窗必须避免重复触发，否则会影响视图初始化体验。
- “跳过预处理并拆分”是高意图操作，必须保持显式确认，不应被批量入口复用。
- `pywin32` 平台条件依赖只解决安装问题，不改变运行时仅支持 Windows 的事实。

## 验收标准

- 关闭窗口时，预处理只完成当前文档，不会继续消耗剩余队列。
- 应用重启后，残留 `preparing` 文档会弹窗询问是否恢复。
- 用户拒绝恢复后，文档进入 `prepare_paused`，默认不参与批量拆分。
- 用户可对单个 `prepare_paused` 文档显式执行“继续预处理”或“跳过预处理并拆分”。
- 多表文档拆分时，进度条不再回退。
- 非 Windows 环境安装项目时不会因 `pywin32` 被无条件安装而失败。
