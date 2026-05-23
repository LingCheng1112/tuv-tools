# Design: DOCX 复选框统一替换预处理

**日期**: 2026-05-24
**状态**: 设计中

## 概述

导入 DOCX 文档时自动执行复选框统一替换预处理：将文档中的旧式表单域复选框和纯文本复选框符号（☒/☐）统一转换为 Word ContentControl 复选框。预处理在后台 Word 进程中执行，期间文档列表显示"预处理中"状态且禁止拆分操作。

## 动机

用户已有的 VBA 脚本 `统一替换复选框.bas` 实现了复选框统一替换逻辑。将此功能集成到 TUV Tools 的文档导入流程中，确保每个导入的 DOCX 在拆分前已完成复选框标准化。

## 设计

### 1. 资源文件

将 `D:\Data\统一替换复选框.bas` 复制到项目，去除中文，保存为纯英文参考文件：

```
resources/unify_checkboxes.bas   ← 英文版 VBA 参考（不直接执行）
```

**需替换的中文元素：**

| 原文 | 替换为 |
|------|--------|
| `统一替换复选框` (模块名) | `UnifyCheckboxes` |
| `批量替换全部复选框` (主过程名) | `ReplaceAllCheckboxes` |
| `替换失败：` (错误消息) | `Replacement failed: ` |

### 2. 新增：PreparingWorker（QThread）

新文件：`src/tuv_tools/core/preparing/__init__.py`
（单个模块，导出 `prepare_document` 和 `PreparingWorker`）

#### 2a. `prepare_document(docx_path: str) -> None`

将 VBA 逻辑移植为 win32com Word 自动化。执行步骤：

1. `win32com.client.Dispatch("Word.Application")` 创建 Word 实例（`Visible=False`，`ScreenUpdating=False`）
2. `Documents.Open(docx_path)` 打开文档
3. `Unprotect` 如果文档有保护
4. **Step 1**: 替换纯文本复选框符号为临时标记
   - `☒` (U+2612) → `@@CHECKED_BOX@@`
   - `☐` (U+2610) → `@@UNCHECKED_BOX@@`
5. **Step 2**: 遍历 `FormFields`（倒序），将旧式复选框替换为 ContentControl 复选框
6. **Step 3**: 查找临时标记 `@@CHECKED_BOX@@` / `@@UNCHECKED_BOX@@`，逐一替换为 ContentControl 复选框
7. **Step 4**: 对每个新建的 ContentControl 调用 `NormalizeCheckboxFont`（清除 Italic/Bold）
8. `Document.Save()` + `Document.Close()`
9. `Application.Quit()` 退出 Word

**错误处理**：任何步骤抛异常 → 关闭文档和 Word → 重新 raise 异常（由 PreparingWorker 捕获）

**关键细节**：
- Word COM 操作必须全路径，不使用相对路径
- 需要 `import win32com.client`（依赖 `pywin32`）
- 步骤 3 中无法创建 ContentControl 的位置保留原标记文本，不中断流程

#### 2b. `PreparingWorker(QThread)`

```python
class PreparingWorker(QThread):
    doc_prepared = Signal(int)      # doc_id — 预处理成功
    doc_error = Signal(int, str)    # doc_id, error_message — 预处理失败

    def __init__(self, items: list[tuple[int, str]]):
        # items: [(doc_id, file_path), ...]
        # 顺序处理多个文档

    def run(self):
        for doc_id, file_path in self._items:
            try:
                prepare_document(file_path)
                self.doc_prepared.emit(doc_id)
            except Exception as exc:
                self.doc_error.emit(doc_id, str(exc))
```

`PreparingWorker` 不做取消支持（预处理通常很快，不需要中断）。

### 3. Import flow change: SplitterView._add_paths

现有逻辑：
```python
def _add_paths(paths):
    for fp in paths:
        db.add_document(fp)      # status='pending'
    self._load_documents()
```

修改后：
```python
def _add_paths(paths):
    new_items = []
    for fp in paths:
        doc_id = db.add_document(fp)       # 仍然是 status='pending'
        db.update_document_status(doc_id, "preparing")
        new_items.append((doc_id, fp))
    self._load_documents()
    if new_items:
        worker = PreparingWorker(new_items)
        worker.doc_prepared.connect(self._on_doc_prepared)
        worker.doc_error.connect(self._on_prepare_error)
        worker.finished.connect(lambda: self._cleanup_preparing_worker(worker))
        self._preparing_workers.append(worker)
        worker.start()
```

**关键决策**：`add_document` 仍用 `status='pending'` 作为默认值，然后**立即覆盖**为 `preparing`。这样数据库 schema 无需改动，且显式表达了"导入 → 立即预处理"的意图。

`_on_doc_prepared(doc_id)`: 调 `db.update_document_status(doc_id, "pending")` + `table.update_row_status(doc_id, "pending")`

`_on_prepare_error(doc_id, error)`: 调 `db.update_document_status(doc_id, "failed", error=error)` + `table.update_row_status(doc_id, "failed")`

新增成员：`self._preparing_workers: list[PreparingWorker]`

### 4. DocumentTable changes

#### 4a. 新增 status 显示

`STATUS_LABELS` 字典新增：

```python
"preparing": "⟳ 预处理中",
```

#### 4b. Checkbox 禁用逻辑

`_build_row()` 中，checkbox 的 `setEnabled` 取决于状态：

```python
can_select = doc["status"] not in ("preparing", "processing")
cb.setEnabled(can_select)
```

#### 4c. 右键菜单

`_show_context_menu()` 中 "拆分此文档" 菜单项的可见性：

```python
if doc["status"] not in ("preparing", "processing"):
    split_action = QAction("拆分此文档", self)
    ...
    menu.addAction(split_action)
```

"打开输出目录" 菜单项同理（仅 completed 时显示，已有逻辑）。

#### 4d. 失败文档重新拆分时触发重新预处理

`_start_batch_split()` 收集 `checked_ids` 时，对于 status 为 `failed` 或 `cancelled` 的文档，应先将其状态重置为 `preparing`，然后启动 `PreparingWorker`，而非直接启动 `SplitWorker`。流程：

```
用户点击拆分 → 检测到 failed/cancelled 文档
  → update_document_status(doc_id, "preparing")
  → PreparingWorker 处理
  → 成功 → 自动触发 SplitWorker 拆分
  → 失败 → 保持 failed 状态
```

实现方式：`_start_batch_split()` 中，将 items 分为两类：
- **可直接拆分的**（pending/completed）→ 直接交给 SplitWorker
- **需要预处理的**（failed/cancelled/preparing 已有跳过逻辑）→ 先交给 PreparingWorker，成功回调中再启动 SplitWorker

#### 4e. 底部批量拆分

`_start_batch_split()` 中 `checked_ids` 收集已跳过 preparing/processing 的文档（当前已有此逻辑，但需确认），如果跳过了一些，按钮文案需调整或在旁边显示提示。

### 5. SplitterView 生命周期

`closeEvent` 中新增对 `_preparing_workers` 的清理：

```python
for w in self._preparing_workers:
    if w.isRunning():
        w.wait(3000)
```

### 6. 不需要改动的部分

- **数据库 schema**：`imported_documents.status` 已是 TEXT 类型，`preparing` 直接可用。`update_document_status` 方法已支持任意 status 字符串。
- **SplitWorker**：无改动。`_start_batch_split` 已通过 `checked_ids` 选择目标文档。

### 7. 依赖变化

在 `pyproject.toml` 中新增：

```toml
dependencies = [
    ...
    "pywin32>=305",
]
```

## 文件变更汇总

| 文件 | 操作 | 说明 |
|------|------|------|
| `resources/unify_checkboxes.bas` | **新增** | 英文版 VBA 参考文件 |
| `src/tuv_tools/core/preparing/__init__.py` | **新增** | `prepare_document()` + `PreparingWorker` |
| `src/tuv_tools/ui/views/splitter_view.py` | **修改** | `_add_paths`、新增信号处理、closeEvent |
| `src/tuv_tools/ui/widgets/document_list.py` | **修改** | STATUS_LABELS、checkbox 禁用、右键菜单 |
| `pyproject.toml` | **修改** | 新增 pywin32 依赖 |

## 测试计划

### 单元测试

- `test_preparing.py`：mock `win32com.client`，验证 `prepare_document` 按正确顺序调用 Word COM 方法
- `test_document_list.py`（扩展现有）：验证 preparing/processing 状态下 checkbox 禁用、右键菜单隐藏拆分项

### 集成测试

- 完整导入 → 预处理 → 拆分的端到端流程（需要真实 Word 环境或跳过）

## 状态流转总图

```
import ──→ preparing ──┬──→ pending ──→ processing ──→ completed
            (预处理中)   │    (未处理)     (拆分中)       (已拆分)
                        │
                        ├──→ failed      (预处理失败)
                        │
              preparing/processing/cancelled/failed:
              └── checkbox 禁用 + 拆分操作禁用
```
