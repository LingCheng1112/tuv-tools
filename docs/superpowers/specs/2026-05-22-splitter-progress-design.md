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
2. 不把过程进度持久化进 SQLite；数据库仍只保存最终状态、条款数、完成时间和错误。
3. 不改变 DOCX 拆分、条款识别、清洗和导出结果语义。
4. 不在本设计中处理导出文档的页眉页脚保留问题。

## 方案选择

推荐采用“阶段化真实进度”方案。

轻量 UI 修补只增加阶段文字，不能解决大文件长时间不动和取消不及时的问题。完整任务系统虽然能力最强，但对当前桌面工具过重，会引入任务表、恢复策略和历史管理等额外复杂度。阶段化进度能覆盖当前生产痛点，同时把改动限制在 splitter 调用链和 UI 绑定层。

## 进度事件模型

新增一个轻量数据结构 `SplitProgressEvent`，用于从 worker 向 UI 传递细粒度进度。

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

整体进度仍以批次为单位，但每个文档内部按阶段加权。

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

## 核心函数扩展

`build_sections()` 增加可选参数：

```python
def build_sections(
    docx_path: Path,
    progress: ProgressCallback | None = None,
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
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> None:
```

兼容规则：

1. 不传回调时结果和现有行为一致。
2. 进度回调只汇报状态，不修改业务数据。
3. 取消回调返回 `True` 时抛出内部 `SplitCancelled` 异常，由 `SplitWorker` 捕获并转成取消状态。
4. `SplitCancelled` 不写入 `failed`，避免把用户主动取消记录成失败。

## Worker 行为

`SplitWorker` 新增信号：

```python
progress_detail = Signal(object)
batch_cancelled = Signal()
```

处理流程：

1. 批次开始时重置 `_cancelled = False`。
2. 每个文档开始时，数据库和表格行状态更新为 `processing`。
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
4. 未开始的文档保持原状态，当前文档可恢复为 `pending` 或显示 `cancelled`。推荐先恢复为 `pending`，避免新增持久状态。

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

## 文件变更范围

| 文件 | 变更 |
| --- | --- |
| `src/tuv_tools/ui/views/splitter_view.py` | 扩展 `SplitWorker` 信号、取消语义、进度区 UI 和状态统计 |
| `src/tuv_tools/core/splitter/parsing.py` | 给解析流程增加可选进度和取消回调 |
| `src/tuv_tools/core/splitter/exporting.py` | 给导出流程增加可选进度和取消回调 |
| `src/tuv_tools/core/splitter/models.py` | 可放置 `SplitProgressEvent` 和 `SplitCancelled`，保持 splitter 内聚 |
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

## 验收标准

1. 批量拆分时进度条显示 0 到 100 的整体百分比。
2. 当前文件名、文档序号、处理阶段和阶段计数可见。
3. 大文档解析和导出期间进度会持续变化。
4. 点击取消后，当前文档在安全检查点退出，未开始文档不被处理。
5. 用户取消不会记录为失败，也不会显示“拆分完成”。
6. 现有 splitter 单元测试和导出集成测试通过。
7. 新增进度和取消相关测试通过。
