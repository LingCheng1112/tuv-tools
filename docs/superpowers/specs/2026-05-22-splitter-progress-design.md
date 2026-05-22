<!-- /autoplan restore point: C:\Users\Admin\.gstack\projects\LingCheng1112-tuv-tools\main-autoplan-restore-20260522-234625.md -->
# 文档拆分进度优化设计

日期: 2026-05-22
状态: 已设计，待实施

## 背景

当前文档拆分进度只按已处理文档数量推进。`SplitWorker` 在开始处理每个文件前就发出进度，随后 `build_sections()` 和 `export_docx_outputs()` 都是黑盒调用。对大 DOCX 或批量拆分来说，用户会看到进度条长时间停住，也无法判断是在解析、切分表格、导出条款文件，还是已经卡在异常边缘。

生产使用需要的是可解释、可取消、能反映真实耗时阶段的进度，而不是单纯的批次数字。

## 当前问题

1. `SplitWorker.progress` 只表达 `(current_doc, total_docs)`，没有当前文件、当前阶段、阶段计数和用户可读消息。
2. 进度在文档开始前推进，单个大文件处理期间进度条不动。
3. `build_sections()` 内部包含 ZIP 读取、XML 解析、段落扫描、表格逐行检测、Section 去重，但没有回调出口。
4. `export_docx_outputs()` 会按每个条款和每个主版本写 DOCX，实际耗时可能很高，但没有导出进度。
5. 取消只在文档之间检查，处理大文件时不能及时停止。
6. 列表已有 `processing` 状态文案，但拆分开始时没有设置为处理中。
7. 取消后仍走统一完成回调，容易显示“拆分完成”这类误导提示。

## 设计目标

1. 底部进度条显示批次整体进度，并附带当前文档和当前阶段说明。
2. 当前文件内部展示阶段进度，例如“解析表格行 120/846”或“导出条款文件 42/118”。
3. 大文件处理期间进度持续推进，避免长时间静止。
4. 取消请求能在解析块、表格行扫描、导出单个 DOCX 之间尽快生效。
5. 保持 splitter 核心函数的兼容性，现有调用不传回调时行为不变。
6. 测试覆盖进度事件顺序、取消行为、UI 状态变化和现有导出结果不回退。

## 非目标

1. 不做后台任务队列、任务历史页或断点续跑。
2. 不把高频过程进度持久化进 SQLite；数据库仍只保存最终状态、条款数、完成时间和错误。
3. 不改变 DOCX 拆分、条款识别、清洗和导出结果语义。
4. 不在本设计中处理导出文档的页眉页脚保留问题。

## 方案选择

推荐采用“阶段化真实进度 + 文档级输出完整性”方案。

轻量 UI 修补只增加阶段文字，不能解决大文件长时间不动和取消不及时的问题。完整任务系统虽然能力最强，但对当前桌面工具过重，会引入任务表、恢复策略和历史管理等额外复杂度。阶段化进度能覆盖当前生产痛点，同时把改动限制在 splitter 调用链和 UI 绑定层。

自动评审后补充一个关键边界：进度优化不能让输出目录变得不可信。导出必须具备文档级 staging 策略，取消或失败时不能把半套 `clauses_docx` / `versions_docx` 伪装成完整结果。

## 进度事件模型

新增两个轻量数据结构。core 层只发核心阶段事件，worker 再映射为 UI 批次事件，避免 `build_sections()` 和 `export_docx_outputs()` 知道 `doc_id`、批次数、UI 百分比等界面概念。

```python
@dataclass(frozen=True)
class CoreProgressEvent:
    phase: str
    phase_label: str
    current: int
    total: int
    message: str
```

`SplitProgressEvent` 用于从 worker 向 UI 传递细粒度进度。

```python
@dataclass(frozen=True)
class SplitProgressEvent:
    doc_id: int
    file_name: str
    doc_index: int
    doc_total: int
    phase: str
    phase_label: str
    phase_current: int
    phase_total: int
    overall_percent: int
    message: str
```

`phase` 使用稳定英文值，便于测试和后续维护：

| phase | 含义 |
| --- | --- |
| `queued` | 已进入批次 |
| `validating` | 校验文件存在性 |
| `reading` | 读取 DOCX ZIP 和 document.xml |
| `parsing_blocks` | 扫描段落和表格块 |
| `splitting_tables` | 表格逐行识别条款并切片 |
| `deduplicating` | Section 去重和过滤 |
| `exporting_clauses` | 导出单条款 DOCX |
| `exporting_versions` | 导出主版本合并 DOCX |
| `completed` | 当前文档完成 |
| `failed` | 当前文档失败 |
| `cancelled` | 当前批次取消 |

UI 不直接拼接内部英文 phase，而是使用 `phase_label` 和 `message`。

## 加权规则

整体进度仍以批次为单位，但第一版不承诺“真实耗时百分比”。进度条显示保守批次进度，当前阶段使用真实计数解释正在发生的工作。

阶段权重只作为 UI 平滑估算，不作为用户承诺。实现时必须记录每阶段耗时日志，后续至少用 3 类样本校准权重后再调优。

| 阶段 | 权重 |
| --- | --- |
| 文件校验和读取 | 10% |
| 解析块和表格切片 | 35% |
| Section 去重和统计 | 5% |
| 导出条款 DOCX | 35% |
| 导出版本 DOCX | 15% |

`overall_percent` 计算方式：

```text
已完成文档数 / 总文档数 * 100
+ 当前文档阶段进度 / 总文档数
```

如果某个阶段无法获得准确总量，先发送阶段开始事件，再在可获得总量后改用实际计数。这样用户至少能看到阶段变化。

进度事件必须节流：阶段切换、阶段完成和文档完成立即发送；行扫描、ZIP entry 复制和文件导出这类高频循环按“至少间隔 100-200ms 或每 N 项”发送，避免 Qt 信号队列成为新的性能瓶颈。

## 核心函数扩展

`build_sections()` 增加可选参数：

```python
def build_sections(
    docx_path: Path,
    progress: CoreProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> list[Section]:
```

`export_docx_outputs()` 增加可选参数：

```python
def export_docx_outputs(
    docx_path: Path,
    sections: list[Section],
    output_root: Path,
    inline_clean_patterns: CleanPatterns,
    progress: CoreProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    staging_root: Path | None = None,
) -> None:
```

兼容规则：

1. 不传回调时结果和现有行为一致。
2. 进度回调只汇报状态，不修改业务数据。
3. 取消回调返回 `True` 时抛出内部 `SplitCancelled` 异常，由 `SplitWorker` 捕获并转成取消状态。
4. `SplitCancelled` 不写入 `failed`，避免把用户主动取消记录成失败。
5. `_write_docx_from_template()` 内部复制 ZIP entry 前也检查 `should_cancel`，避免大媒体模板导致取消长时间无响应。

## 输出完整性

每个文档导出必须使用文档级临时目录：

```text
<output_root>/<base_name>.partial-<doc_id>/
<output_root>/<base_name>/
```

处理规则：

1. 当前文档开始导出前，清理同一 `doc_id` 的旧 partial 目录。
2. 条款文件和版本文件全部写入 partial 目录。
3. 当前文档全部成功后，将旧正式目录替换为 partial 目录。
4. 当前文档失败或取消时，删除本次 partial 目录，不覆盖上一次成功输出。
5. 如果正式目录替换失败，当前文档记为 `failed`，错误信息说明输出目录替换失败。

这样取消和失败不会留下半套新结果，也不会破坏上一次可信输出。第一版不需要持久化完整任务系统或历史页；如果需要诊断，可在 partial 目录内生成临时 manifest，成功移动后随目录保留为输出摘要。

## Worker 行为

`SplitWorker` 新增信号：

```python
progress_detail = Signal(object)
batch_cancelled = Signal()
```

处理流程：

1. 批次开始时重置 `_cancelled = False`。
2. 每个文档开始时，发出 `doc_started` 或进度事件；UI 主线程负责把数据库和表格行状态更新为 `processing`。
3. 文件不存在时立即发 `doc_error`，并继续下一文档。
4. 调用 `build_sections()` 时传入解析进度回调和取消检查。
5. sections 为空时仍发完成事件，条款数为 0。
6. 调用 `export_docx_outputs()` 时传入导出进度回调和取消检查。
7. 捕获 `SplitCancelled` 后停止批次，发 `batch_cancelled`。
8. 正常结束时发完成提示；取消结束时发取消提示。

取消按钮点击后：

1. 设置 `_cancelled = True`。
2. 按钮禁用，文案改为“正在取消...”。
3. 当前安全检查点退出后隐藏进度区。
4. 未开始的文档保持原状态；当前文档在 UI 中显示“已取消”，数据库状态恢复为 `pending`，同时清空本次 `error_message`。`last_split_at` 和 `last_section_count` 保留上一次成功结果，不写入新的完成时间。

## UI 展示

底部进度区由单个进度条扩展为两行信息：

```text
第 3/12 个文档 | IEC 60335-2-24.docx
导出条款文件 42/118
[====================      ] 58%    [取消]
```

实现上可新增两个 `QLabel`：

1. `_progress_title`: 当前批次位置和文件名。
2. `_progress_detail`: 当前阶段和计数。

`QProgressBar` 使用 0 到 100 的百分比，不再以文档数量为最大值。

列表状态：

1. 当前文档开始时显示 `processing`。
2. 成功后显示 `completed` 并更新条款数。
3. 失败后显示 `failed`。
4. 取消时当前文档恢复为 `pending`，已完成文档保持 `completed`。

Toast 文案：

| 场景 | 文案 |
| --- | --- |
| 全部成功 | `拆分完成：成功 N 个，失败 0 个` |
| 部分失败 | `拆分完成：成功 N 个，失败 M 个` |
| 用户取消 | `已取消拆分：完成 N 个，剩余 M 个` |
| 全部失败 | `拆分失败：M 个文档未完成` |

## 错误处理

1. 单个文档异常不终止整个批次，除非异常是用户取消。
2. 失败文档写入 `failed` 和错误信息。
3. 取消不写入错误信息。
4. 输出目录创建或写文件失败归入当前文档失败。
5. 进度回调自身不应抛出异常；如果 UI 更新失败，不应影响后台拆分。
6. 取消或失败必须清理本次 partial 目录；如果清理失败，只记录日志或错误信息，不把半成品标记为完成。

## 文件变更范围

| 文件 | 变更 |
| --- | --- |
| `src/tuv_tools/ui/views/splitter_view.py` | 扩展 `SplitWorker` 信号、取消语义、进度区 UI 和状态统计 |
| `src/tuv_tools/core/splitter/parsing.py` | 给解析流程增加可选进度和取消回调 |
| `src/tuv_tools/core/splitter/exporting.py` | 给导出流程增加可选进度和取消回调 |
| `src/tuv_tools/core/splitter/models.py` | 放置 `CoreProgressEvent`、`SplitProgressEvent` 和 `SplitCancelled`，保持 splitter 内聚 |
| `src/tuv_tools/ui/widgets/document_list.py` | 支持处理中状态即时刷新，必要时补充取消显示 |
| `tests/test_splitter.py` | 增加核心进度和取消测试 |
| `tests/test_database.py` | 如状态语义变化，补充文档状态测试 |

## 测试策略

1. `build_sections()` 不传回调时现有解析测试全部通过。
2. `build_sections()` 传入进度回调时至少发出读取、解析、表格切片和去重阶段。
3. `build_sections()` 在取消回调返回 `True` 时停止并抛出 `SplitCancelled`。
4. `export_docx_outputs()` 不传回调时现有导出测试全部通过。
5. `export_docx_outputs()` 传入进度回调时导出事件数与条款文件、版本文件数量一致。
6. `export_docx_outputs()` 在导出中取消时停止后续写入。
7. `SplitWorker` 处理成功、失败、取消三条路径时发出正确信号。
8. UI 层测试或轻量 helper 测试验证百分比计算不会超过 100，且取消不会提示“拆分完成”。
9. 取消和失败时 partial 目录被清理，正式输出目录仍保持上一次成功结果。
10. 高频进度事件被节流，阶段切换事件不丢失。
11. 进度回调抛出异常时不影响拆分结果，最多记录调试信息。

## 验收标准

1. 批量拆分时进度条显示 0 到 100 的整体百分比。
2. 当前文件名、文档序号、处理阶段和阶段计数可见。
3. 大文档解析和导出期间进度会持续变化。
4. 点击取消后，当前文档在安全检查点退出，未开始文档不被处理。
5. 用户取消不会记录为失败，也不会显示“拆分完成”。
6. 取消或失败不会留下半套新输出；上一次成功输出仍可信。
7. 现有 splitter 单元测试和导出集成测试通过。
8. 新增进度、取消、partial 清理和状态语义相关测试通过。

## GSTACK REVIEW REPORT

审查日期: 2026-05-22
审查方式: /autoplan
Base branch: main
计划文件: `docs/superpowers/specs/2026-05-22-splitter-progress-design.md`

### Plan Summary

本计划把文档拆分进度从“按文档数量跳动”升级为“阶段明确、可取消、能解释当前耗时”的批处理反馈。自动评审后，计划范围增加了文档级 partial 输出目录，避免取消或失败时留下半套输出结果。

### What Already Exists

| 子问题 | 现有代码 |
| --- | --- |
| 批量拆分入口 | `src/tuv_tools/ui/views/splitter_view.py` 中的 `SplitWorker` 和 `_start_batch_split()` |
| 解析 DOCX 并构建 Section | `src/tuv_tools/core/splitter/parsing.py::build_sections()` |
| 导出条款和版本 DOCX | `src/tuv_tools/core/splitter/exporting.py::export_docx_outputs()` |
| 文档状态展示 | `src/tuv_tools/ui/widgets/document_list.py::STATUS_LABELS` 和 `update_row_status()` |
| 最终状态持久化 | `src/tuv_tools/config/database.py::update_document_status()` |
| 核心 splitter 测试 | `tests/test_splitter.py` |

### NOT In Scope

| 项目 | 原因 |
| --- | --- |
| 后台任务队列和任务历史页 | 当前需求是单机桌面批处理反馈，不需要队列产品化 |
| 断点续跑 | 会引入持久任务模型和输出索引，超过本轮目标 |
| 页眉页脚保留 | 用户已确认导出文档不需要保留页眉页脚 |
| 新增 pytest-qt 依赖 | 当前测试栈只有 pytest，优先用纯 helper 和 worker 薄层测试 |

### CEO Review

Mode: SELECTIVE EXPANSION

Premise challenge:

| 前提 | 结论 | 处理 |
| --- | --- | --- |
| 用户痛点是进度不可解释 | 成立 | 保留阶段化进度 |
| 固定权重能代表真实耗时 | 不完全成立 | 改为保守百分比 + 阶段真实计数 + 后续耗时校准 |
| 取消可以简单恢复 pending | 不成立 | 增加 partial 输出目录和取消字段语义 |
| 完整任务系统太重 | 成立 | 不做队列/历史页，但接受轻量输出完整性机制 |

Implementation alternatives:

| 方案 | 决策 | 原因 |
| --- | --- | --- |
| 仅补 UI 文案 | 拒绝 | 不能解决大文件长时间静止和取消不及时 |
| 阶段化进度 | 接受 | 能覆盖核心体验问题，改动范围可控 |
| 阶段化进度 + partial 输出目录 | 接受 | 解决取消/失败后输出可信度，是生产必要条件 |
| 完整任务系统 | 拒绝 | 对当前桌面工具过重 |

Error & Rescue Registry:

| 触发点 | 异常/状态 | 捕获位置 | 用户看到 | 测试要求 |
| --- | --- | --- | --- | --- |
| DOCX 不存在 | `doc_error` | `SplitWorker.run()` | 单文档失败，批次继续 | 文件缺失测试 |
| DOCX 损坏 | `ValueError` | worker 单文档异常分支 | 单文档失败，批次继续 | 现有坏文件测试 + worker 失败测试 |
| 用户取消 | `SplitCancelled` | worker 取消分支 | 已取消拆分，显示完成/剩余统计 | 取消路径测试 |
| 导出写入失败 | `OSError` | worker 单文档异常分支 | 单文档失败 | 导出失败测试 |
| partial 替换失败 | `OSError` | 导出收尾分支 | 输出目录替换失败 | partial 失败测试 |
| 进度回调失败 | 回调异常 | progress wrapper | 不影响拆分结果 | 回调异常隔离测试 |

Failure Modes Registry:

| 失败模式 | 严重性 | 当前计划状态 | 决策 |
| --- | --- | --- | --- |
| 取消后留下半套输出 | Critical | 已补 partial 输出目录 | 必须实施 |
| 百分比假精确 | High | 已降级为保守百分比 + 阶段计数 | 必须实施 |
| Worker 直接改 DB/UI | High | 已明确 worker 只发事件，UI 主线程更新 | 必须实施 |
| 高频信号拖慢 UI | Medium | 已补 100-200ms 节流 | 必须实施 |
| ZIP entry 复制期间不可取消 | Medium | 已补 entry 级取消检查 | 必须实施 |
| UI 测试过重或缺失 | Medium | 已要求 helper 优先 + worker 薄层测试 | 必须实施 |

CEO dual voices consensus:

| Dimension | Local review | Codex voice | Subagent voice | Consensus |
| --- | --- | --- | --- | --- |
| Premises valid | 部分有效 | 部分有效 | 部分有效 | CONFIRMED |
| Right problem | 是，但缺输出一致性 | 是，但缺输出一致性 | 是，但缺输出一致性 | CONFIRMED |
| Scope calibration | 需小幅扩大 | 需 partial/staging | 需 partial/manifest | CONFIRMED |
| Alternatives explored | 需要补 profiling/staging | 需要补 profiling | 需要补 manifest | CONFIRMED |
| 6-month risk | 输出可信度 | 输出可信度 | 输出可信度 | CONFIRMED |

Phase 1 complete. Consensus: 5/5 confirmed, 0 disagreements. Passing to Design Review.

### Design Review

Design scope: yes. The plan changes visible progress UI, cancellation state, toast copy, and table status.

| Pass | Score Before | Score After Plan Updates | Findings |
| --- | --- | --- | --- |
| Information Architecture | 7/10 | 8/10 | Progress title/detail split is clear; add partial/cancel state copy |
| Interaction State Coverage | 6/10 | 9/10 | Added cancelled, partial failure, callback failure, mixed result states |
| User Journey | 7/10 | 8/10 | User sees current file, current stage, and final trustworthy result |
| AI Slop Risk | 8/10 | 8/10 | Operational UI, no decorative redesign |
| Design System Alignment | 8/10 | 8/10 | Reuses QLabel/QProgressBar/QPushButton patterns |
| Responsive & Accessibility | 6/10 | 7/10 | Needs tooltip or elided filename handling during implementation |
| Unresolved Decisions | 2 open | 0 blocking | Percent semantics and cancel status now defined |

Design litmus scorecard:

| Dimension | Result |
| --- | --- |
| User can tell what is happening | Pass |
| User can trust cancel result | Pass after partial output addition |
| Mixed success/failure is visible | Pass |
| Text can fit compact desktop UI | Implementation must elide long filename |
| No new visual system invented | Pass |

Phase 2 complete. No taste decisions remain. Passing to Engineering Review.

### Engineering Review

Scope challenge: accepted with mandatory output consistency addition. Complexity remains moderate: `splitter_view.py`, `parsing.py`, `exporting.py`, `models.py`, `document_list.py`, plus focused tests.

Architecture diagram:

```text
SplitterView
  | starts/cancels
  v
SplitWorker (QThread, no direct UI writes)
  | passes callbacks
  v
build_sections() ---- emits CoreProgressEvent ----+
  |                                             |
  v                                             v
export_docx_outputs(staging_root) ---- emits CoreProgressEvent
  | writes partial dir, then replaces final dir
  v
output/<base_name>/

SplitWorker maps core events -> SplitProgressEvent
  |
  v
SplitterView updates QLabels, QProgressBar, DB status, DocumentTable
```

Test diagram:

| Codepath | Test type | Required coverage |
| --- | --- | --- |
| `build_sections()` no callbacks | Existing unit/integration | Existing tests still pass |
| `build_sections()` progress callbacks | Unit | Emits reading/parsing/splitting/deduplicating |
| `build_sections()` cancel | Unit | Raises `SplitCancelled` and stops |
| `export_docx_outputs()` no callbacks | Existing integration | Existing output tests still pass |
| `export_docx_outputs()` progress | Unit/integration | Clause and version export counts reported |
| Partial output success | Integration | Partial dir moved to final dir |
| Partial output cancel/failure | Integration | Partial dir removed, final dir unchanged |
| `_write_docx_from_template()` cancel | Unit | Checks cancellation between ZIP entries |
| Progress throttling | Unit | High-frequency events are reduced; phase events preserved |
| Worker success | Worker/helper | Emits started/progress/done and updates UI via slots |
| Worker failure | Worker/helper | Emits error, batch continues |
| Worker cancel | Worker/helper | Does not emit misleading all-done message |
| Toast copy | Pure helper | Success, partial failure, cancel, all failed |

Performance review:

The plan should not claim speed improvement. It improves observability and trust. Implementation should record coarse phase durations so a later pass can decide whether repeated ZIP reads need optimization.

Security review:

No new network/auth surface. Main safety issue is filesystem overwrite semantics; partial output directory reduces accidental corruption of previous successful exports.

Engineering completion summary:

| Section | Result |
| --- | --- |
| Architecture | 2 required boundary fixes accepted |
| Tests | 12 codepaths mapped |
| Performance | No speed claim; stage timing required |
| Error handling | 6 error/rescue paths mapped |
| Failure modes | 6 total, 1 critical, now addressed in plan |

Phase 3 complete. Passing to DX Review.

### DX Review

Skipped. This is an end-user desktop workflow, not a developer-facing API, SDK, CLI, or onboarding surface.

### Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | CEO | Add document-level partial output directory | Auto | Completeness | Progress UX must not reduce output trust | Leave final dir half-written |
| 2 | CEO | Keep full task system out of scope | Auto | Pragmatic | Queue/history/断点续跑 are not needed for this desktop fix | Full job table/history UI |
| 3 | CEO | Downgrade fixed weights from truth to estimate | Auto | Explicit over clever | Static weights are not real elapsed-time evidence | Present precise percent as truth |
| 4 | Eng | Keep core events UI-free | Auto | Boundary clarity | Core splitter should not know doc_id/doc_total/UI percent | Put batch fields in core callbacks |
| 5 | Eng | Worker emits events only; UI thread updates DB/table | Auto | Safety | Existing PySide pattern keeps UI mutations on main thread | Worker direct DB/UI writes |
| 6 | Eng | Add progress throttling | Auto | Performance | Prevent progress events from becoming a new bottleneck | Emit every row/file unthrottled |
| 7 | Eng | Avoid new pytest-qt dependency for now | Auto | Pragmatic | Pure helpers and worker thin tests cover risk without test stack churn | Heavy UI dependency |

### Final Approval Gate

User challenges: none. Both independent reviewers agreed with the direction after adding output consistency.

Taste decisions: none blocking.

Auto-decided: 7 decisions, listed in the audit trail.

Review scores:

| Area | Result |
| --- | --- |
| CEO | Approved with mandatory partial output addition |
| Design | 8/10 after state coverage additions |
| Engineering | Approved with boundary and test requirements |
| DX | Skipped |

Cross-phase themes:

1. Output trust matters more than animated progress.
2. Percent should be conservative unless backed by measured timings.
3. Core/UI boundaries must stay clean.
4. Tests must cover cancellation and filesystem consistency, not just event emission.

