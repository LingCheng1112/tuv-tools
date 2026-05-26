# Chapter Batch Progress And Reupload Implementation Plan

> **For agentic workers:** 推荐按 `tests -> models/repository -> executor -> view/widgets -> regression` 顺序执行；这次不是从零做新模块，而是在现有脏工作树基础上收口语义，禁止回退用户已有未提交修改。

**Goal:** 在不改变现有 DOCX 拆分规则和清洗效果的前提下，完成条款批量上传工作台的两项增量重构：一是为 `上传成功` 条款增加 `重新上传`；二是把文档导入后的 `预处理 + 拆分` 和上传阶段都升级为用户可理解的进度语义，并把进度嵌入文档列表“状态”单元格，而不是新增独立进度列。  
**Architecture:** 保持现有 `chapter_batch` 分层，不新增后端接口，不引入新的持久化事件表。重复弹窗仍由 UI 主线程负责，执行器只负责消费已确认的上传意图、发出运行时进度事件、执行创建/上传/重新上传、以及在“本次不覆盖”分支恢复条款原稳定状态。  
**Tech Stack:** Python 3.10+, PySide6, SQLite (`sqlite3`), requests, pytest

---

## Reviewed Inputs

- 设计稿：`O:\tuv-tools\docs\superpowers\specs\2026-05-26-chapter-batch-progress-and-reupload-design.md`
- 现有旧计划：`O:\tuv-tools\docs\superpowers\plans\2026-05-25-chapter-batch-upload-implementation-plan.md`
- 当前实现落点：
  - `O:\tuv-tools\src\tuv_tools\core\chapter_batch\models.py`
  - `O:\tuv-tools\src\tuv_tools\core\chapter_batch\repository.py`
  - `O:\tuv-tools\src\tuv_tools\core\chapter_batch\executor.py`
  - `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
  - `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_clause_table.py`
  - `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_drawer.py`

## Current-State Findings

1. `models.py` 的文档状态已经基本收敛到 `处理中/待确认/待上传/上传中/已完成/部分完成/失败`，但条款状态仍保留 `重复跳过`，与最新业务口径冲突。
2. `repository.py` 仍把 `重复跳过` 当成稳定状态参与聚合，`reaggregate_document()` 里存在“全部重复跳过 -> 待上传”的分支，说明“重复拒绝”尚未被还原成一次性决策。
3. `executor.py` 只具备“创建 chapter -> 上传 docx”的普通路径，没有显式的文档处理/上传进度事件，也没有 `上传成功 -> 重新上传` 的专门分支。
4. `chapter_batch_view.py` 已经更名为“批量上传”并具备脏数据保存拦截，但导入后记录是否即时出现、状态格环形进度、重复弹窗三按钮语义、逐文档剩余条款“后续重复全部跳过”等约束还没收口。
5. `chapter_batch_clause_table.py` 目前对 `上传成功` 只给查看动作，没有 `重新上传`；同时仍对 `重复跳过` 暴露 `恢复跳过` 等旧语义。
6. `chapter_batch_drawer.py` 已有保存/上传按钮和 dirty cache，当前应保持布局不大改，只补充当前文档上传进度显示。

## Fixed Business Constraints

- 文档导入后，列表记录必须立刻出现，不能等预处理和拆分结束。
- 不新增“真实进度”列；进度只显示在文档列表的“状态”单元格里。
- `预处理 + 拆分` 对用户只显示一个 `处理中` 的 0-100%。
- `上传中` 作为单独的 0-100% 阶段显示。
- 稳定态 `待确认 / 待上传 / 已完成 / 部分完成 / 失败` 不显示环形图。
- `上传成功` 条款右键支持 `重新上传`。
- `重新上传` 固定为：复用现有 `chapterId`、上传当前 `source_docx_path`、不做重复检查、不重新创建 chapter。
- 重复命中且用户不覆盖时，不再落 `重复跳过` 稳定状态；条款恢复到“本次上传开始前”的原状态。
- 重复弹窗按钮固定为：`覆盖`、`跳过当前条款`、`后续重复全部跳过`。
- `后续重复全部跳过` 的作用域只限当前文档剩余条款。
- 一边 `specific_product` 为空、一边非空时不算重复；只有两边都空或两边相等时才算重复。
- 不修改 splitter 的拆分规则和清洗效果。

---

## File Structure

### Primary Files To Modify

- `O:\tuv-tools\src\tuv_tools\core\chapter_batch\models.py`
  - 移除 `ClauseStatus.DUPLICATE_SKIPPED`
  - 新增运行时进度事件和上传意图的数据模型
- `O:\tuv-tools\src\tuv_tools\core\chapter_batch\repository.py`
  - 去掉对 `重复跳过` 稳定聚合的依赖
  - 保留旧状态读兼容，但新写路径不再写入该状态
- `O:\tuv-tools\src\tuv_tools\core\chapter_batch\executor.py`
  - 增加 `processing/uploading` 进度事件
  - 增加 `重新上传` 执行分支
  - 增加“本次不覆盖 -> 恢复原状态”的执行语义
- `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
  - 导入即落记录
  - 文档状态格环形进度
  - 重复弹窗按钮与逐文档作用域
  - 批量/单条上传时的进度接线
- `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_clause_table.py`
  - 为 `上传成功` 增加 `重新上传`
  - 删除围绕 `重复跳过` 的旧菜单语义
- `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_drawer.py`
  - 保持现有布局
  - 补当前文档上传进度展示

### Test Files To Modify

- `O:\tuv-tools\tests\test_chapter_batch_models.py`
- `O:\tuv-tools\tests\test_chapter_batch_repository.py`
- `O:\tuv-tools\tests\test_chapter_batch_executor.py`
- `O:\tuv-tools\tests\test_chapter_batch_view.py`
- 如需联动导入流程：`O:\tuv-tools\tests\test_chapter_batch_service.py`

### Files To Inspect But Not Semantically Rewrite

- `O:\tuv-tools\src\tuv_tools\core\chapter_batch\service.py`
- `O:\tuv-tools\src\tuv_tools\core\preparing\worker.py`
- `O:\tuv-tools\src\tuv_tools\ui\main_window.py`

---

## Task 1: Lock The New Semantics With Failing Tests First

**Files:**
- Modify: `O:\tuv-tools\tests\test_chapter_batch_models.py`
- Modify: `O:\tuv-tools\tests\test_chapter_batch_repository.py`
- Modify: `O:\tuv-tools\tests\test_chapter_batch_executor.py`
- Modify: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] 覆盖条款稳定状态集合，明确不再暴露 `重复跳过`
- [ ] 覆盖 `上传成功` 条款支持 `重新上传`
- [ ] 覆盖重复命中但选择 `跳过当前条款 / 后续重复全部跳过` 后，条款恢复到上传前原状态
- [ ] 覆盖文档列表不新增进度列，只在状态格显示运行态进度
- [ ] 覆盖导入后列表立刻出现记录，初始状态为 `处理中`
- [ ] 覆盖 `处理中` 与 `上传中` 才显示环形图，稳定态不显示

**Suggested commands**

```powershell
pytest tests/test_chapter_batch_models.py tests/test_chapter_batch_repository.py tests/test_chapter_batch_executor.py tests/test_chapter_batch_view.py -q
```

**Expected initial result:** FAIL，且失败点集中在 `DUPLICATE_SKIPPED`、`重新上传`、进度视图和导入即显示。

---

## Task 2: 收敛状态模型，移除 `重复跳过` 作为稳定状态

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\models.py`
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\repository.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_models.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_repository.py`

- [ ] 从 `ClauseStatus` 中删除 `DUPLICATE_SKIPPED`
- [ ] 保留 `duplicate_flag / duplicate_reason / user_decision` 作为辅助手段，但不再驱动稳定状态聚合
- [ ] 为老数据保留读兼容：
  - 旧 `用户跳过` 读入时可规范化为 `待上传` 或由调用方按上传前快照恢复
  - 新写路径禁止再写入 `重复跳过`
- [ ] 重写 `reaggregate_document()`：
  - 只根据 `待上传 / 上传中 / 上传成功 / 上传失败` 聚合
  - 不再出现“全部重复跳过”这种稳定聚合真相
- [ ] 明确 `DocumentStatus.PENDING_UPLOAD` 是重复不覆盖后的回退目标，而不是新中间态

**Implementation note**

推荐在 `models.py` 中新增一个轻量上传意图枚举，例如：

```python
class ClauseUploadMode(StrEnum):
    NORMAL = "normal"
    REUPLOAD_EXISTING = "reupload_existing"
```

该模式是一次执行意图，不是持久化状态。

---

## Task 3: 为执行链引入运行时进度事件，而不是新增数据库进度表

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\models.py`
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\executor.py`
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_executor.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] 定义统一的运行时进度事件 dataclass，例如：

```python
@dataclass(slots=True)
class ChapterBatchProgressEvent:
    document_id: int
    phase: Literal["processing", "uploading"]
    percent: int
    message: str = ""
    current_index: int = 0
    total_count: int = 0
    current_clause_term: str = ""
    action: str = ""
```

- [ ] `executor.py` 在上传阶段发出 `uploading` 事件，至少覆盖：
  - `duplicate_check`
  - `create`
  - `upload`
  - `reupload`
- [ ] `chapter_batch_view.py` 消费该事件并刷新当前文档状态格
- [ ] 不把运行时进度落库；页面刷新仍以数据库稳定状态为真相，进度只存在于 view 的内存态缓存

**Why this shape**

- 避免为了 UI 进度引入新的持久化模型
- 允许 `处理中` 与 `上传中` 在 UI 侧自由映射为环形图
- 不污染现有 repository 聚合职责

---

## Task 4: 导入即落记录，并把“预处理 + 拆分”合成为一个 `处理中` 100%

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\service.py`
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Inspect: `O:\tuv-tools\src\tuv_tools\core\preparing\worker.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_service.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] 在用户选择文件/文件夹后，先创建本地文档记录，再启动后台预处理与拆分
- [ ] 记录创建后立即刷新列表，状态显示为 `处理中`
- [ ] 视图侧维护 `processing progress` 的组合映射：
  - 预处理阶段映射到 0-50%
  - 拆分阶段映射到 50-100%
  - 用户只看到一个 `处理中`
- [ ] 完成后按现有规则进入 `待确认` 或 `待上传`
- [ ] 处理中状态格展示环形图；完成后环形图立即消失

**Important constraint**

这里不要把 `预处理中` 和 `拆分中` 暴露成两个用户可见状态文案。底层可保留细分信号，UI 只暴露 `处理中`。

---

## Task 5: 重写上传执行语义，补 `重新上传` 路径和“恢复原状态”语义

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\executor.py`
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_executor.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] 为每个本次上传的条款记录“进入本次上传前的原稳定状态”，仅保存在内存执行上下文中
- [ ] 普通上传路径：
  - 重复检查
  - 需要时创建 chapter
  - 上传 docx
- [ ] `重新上传` 路径：
  - 跳过重复检查
  - 跳过创建
  - 必须要求 `chapter_id` 已存在
  - 直接上传当前 `source_docx_path`
- [ ] 用户在重复弹窗选择：
  - `覆盖`：复用已有 `chapterId`，只覆盖文档
  - `跳过当前条款`：条款恢复到上传前原状态
  - `后续重复全部跳过`：当前文档后续重复条款全部恢复原状态
- [ ] 若一个文档本轮无任何条款真正进入上传完成态，文档回退到上传前的整体稳定状态，通常为 `待上传` 或原有 `上传成功/上传失败`

**Implementation note**

不要再把“本次不覆盖”编码成一个新的稳定状态。  
这次计划推荐把“跳过决定”建模为执行上下文，而不是数据库状态。

---

## Task 6: 重构重复弹窗交互，但不把它塞进后台线程

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Modify if helpful: `O:\tuv-tools\src\tuv_tools\core\chapter_batch\service.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] 替换现有 `Yes / No / Cancel` 风格交互
- [ ] 使用明确业务按钮：
  - `覆盖`
  - `跳过当前条款`
  - `后续重复全部跳过`
- [ ] 弹窗至少展示：
  - 条款号
  - 测试内容
  - 具体产品
  - 归属文件夹
- [ ] `后续重复全部跳过` 只作用于当前文档剩余条款，不影响后续其他文档
- [ ] 一边空一边非空的 `specific_product` 不算重复；两边都空或两边相等才算重复

**Engineering choice**

这一步优先保持重复弹窗在 UI 主线程，避免把模态交互塞进 `QThread`。  
如果当前批量路径已经是后台串行上传，则由 view 在每个文档正式入队前先完成该文档的重复决策收集，或者通过同步回调桥接，不要引入第二套状态真相。

---

## Task 7: 把文档列表的“状态格”升级为运行态环形进度视图

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] 不新增列，继续复用 `COL_STATUS`
- [ ] 在 `处理中 / 上传中` 渲染一个紧凑的环形进度控件或自绘 delegate
- [ ] 在 `待确认 / 待上传 / 已完成 / 部分完成 / 失败` 只显示纯文本状态
- [ ] 运行态状态格要同时能表达：
  - 文案（处理中/上传中）
  - 百分比
  - 必要时 tooltip 里的详细消息
- [ ] 刷新节流要谨慎，避免高频 repaint 抖动

**Preferred implementation**

- 若当前 `QTableWidget` 已足够，可用 `setCellWidget()` 放入轻量状态组件
- 若频繁全表重建导致抖动，则把进度缓存和局部刷新拆开，只更新命中文档所在行

---

## Task 8: 保持抽屉布局不变，只补当前文档上传进度信息

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_drawer.py`
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] 不推翻现有抽屉结构
- [ ] 在抽屉顶部摘要区或按钮区附近补一块轻量上传进度信息
- [ ] 至少展示：
  - 当前文档状态
  - 当前第几条 / 总条数
  - 当前条款号
  - 当前动作（判重/创建/上传/重新上传）
- [ ] 文档未处于上传阶段时，该进度信息可隐藏或清空
- [ ] dirty-save 规则继续保留：用户改过参数但未保存时，不能直接上传

---

## Task 9: 更新条款右键菜单，新增 `重新上传`

**Files:**
- Modify: `O:\tuv-tools\src\tuv_tools\ui\widgets\chapter_batch_clause_table.py`
- Modify: `O:\tuv-tools\src\tuv_tools\ui\views\chapter_batch_view.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`

- [ ] `上传成功` 条款右键菜单新增 `重新上传`
- [ ] `上传失败` 与 `待上传` 继续保留 `上传` / `重试上传`
- [ ] 删除 `重复跳过 -> 恢复跳过` 这组旧菜单语义
- [ ] 保留只读动作：
  - `打开本地 docx`
  - `打开后端 chapter 记录`
  - `查看错误信息`

**Expected mapping**

```text
待上传      -> 上传 / 打开本地 docx / 打开后端 chapter 记录
上传失败    -> 重试上传 / 上传 / 打开本地 docx / 打开后端 chapter 记录 / 查看错误信息
上传成功    -> 重新上传 / 打开本地 docx / 打开后端 chapter 记录
上传中      -> 打开本地 docx / 打开后端 chapter 记录
```

---

## Task 10: Regression Sweep And Manual QA

**Files:**
- Test: `O:\tuv-tools\tests\test_chapter_batch_models.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_repository.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_service.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_executor.py`
- Test: `O:\tuv-tools\tests\test_chapter_batch_view.py`
- Safety net: `O:\tuv-tools\tests\test_preparing.py`
- Safety net: `O:\tuv-tools\tests\test_preparing_worker.py`

- [ ] 跑完整 `chapter_batch` 回归
- [ ] 跑 `preparing` 相关安全网，确认这轮没有破坏自动预处理接线
- [ ] 如有改到共享工具，再补 `tests/test_splitter.py` 的最小 smoke

**Suggested commands**

```powershell
pytest tests/test_chapter_batch_models.py tests/test_chapter_batch_repository.py tests/test_chapter_batch_service.py tests/test_chapter_batch_executor.py tests/test_chapter_batch_view.py -q
pytest tests/test_preparing.py tests/test_preparing_worker.py -q
```

**Manual QA checklist**

1. 导入文档后，列表立即出现新记录，状态为 `处理中`，状态格带环形图。
2. 预处理和拆分过程中，用户只看到一个 `处理中` 百分比从 0 到 100。
3. 处理完成后，状态切到 `待确认` 或 `待上传`，环形图消失。
4. 双击进入抽屉后，不修改参数可以直接上传；修改后必须先保存。
5. 上传时状态格显示 `上传中` 环形图，抽屉中能看到当前条款与当前动作。
6. `上传成功` 条款右键可以 `重新上传`。
7. 重复弹窗按钮为 `覆盖 / 跳过当前条款 / 后续重复全部跳过`，不再出现 `Yes / No / Cancel`。
8. 选择不覆盖后，条款恢复到本次上传开始前的原状态。
9. “后续重复全部跳过”只影响当前文档剩余条款，不影响后续其他文档。
10. 不新增“真实进度”列。

---

## Execution Guardrails

- 本轮是现有 `chapter_batch` 模块的语义收口，不是重做整页。
- 不回退当前工作树里的既有未提交修改。
- 不新增后端 API 契约；继续复用已有 chapter 创建与 `chapter-doc/import` 上传接口。
- 不修改 splitter 的解析、拆分和清洗规则。
- 不为了进度显示引入新的数据库表或长期持久化结构。

## Spec Coverage Check

- `上传成功` 条款支持 `重新上传`
  - Task 5, Task 9
- 导入即出记录
  - Task 4
- `预处理 + 拆分 = 处理中 100%`
  - Task 3, Task 4, Task 7
- `上传中` 进度单独展示
  - Task 3, Task 5, Task 7, Task 8
- 不新增“真实进度”列
  - Task 7
- 重复不覆盖恢复原状态
  - Task 2, Task 5, Task 6
- `后续重复全部跳过` 仅限当前文档剩余条款
  - Task 5, Task 6
- 抽屉布局保持现状，只补上传进度
  - Task 8
- 不改变拆分和清洗效果
  - Guardrails, Task 10

## Handoff

该计划用于替代上一版只覆盖“批量上传语义重整”的实现计划，新增的核心增量是：
- 去掉 `重复跳过` 作为稳定状态
- 把运行态进度变成状态格环形视图
- 补齐 `上传成功 -> 重新上传`

如果直接进入实现，推荐从 **Task 1 -> Task 2 -> Task 5 -> Task 4 -> Task 7 -> Task 8 -> Task 9 -> Task 10** 执行，先锁住状态真相和执行语义，再上 UI。
