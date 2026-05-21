# Splitter 模块优化 — detect_clause_in_cells 重构

日期: 2026-05-21
状态: 已设计，待实施

## 背景

方案 A 优化已完成（`clean_text` 性能、Counter 消除 O(n²)、分支合并、遍历合并）。方案 B 聚焦于 `parsing.py` 中 `detect_clause_in_cells` 函数的重构。

## 当前问题

`detect_clause_in_cells`（parsing.py:70-116）是一个 46 行的函数，包含 4 条检测路径：

1. **直接匹配** — `detect_clause_in_text(first_cell)` 命中则直接返回
2. **分段匹配** — 第一格按 `|` 分割后逐段检测
3. **跨格数字条款** — 第一格只有条款号，第二格有标题，用 CLAUSE_HEAD_RE 匹配
4. **跨格 Annex** — 同上但用 ANNEX_HEAD_RE

路径 3 和 4 结构几乎完全相同，路径 2 是独立的预处理逻辑。4 条路径混在一个函数中，共享局部变量和中间状态，难以理解、难以测试单个路径。

## 设计

### 目标结构

4 个小函数 + 1 个入口编排函数。

### 入口函数

```python
def detect_clause_in_cells(cells: list[str]) -> ClauseMatch | None:
    if not cells:
        return None
    first = clean_text(cells[0])
    if not first:
        return None
    if match := _try_detect_in_first_cell(first):
        return match
    if match := _try_detect_in_segments(first):
        return match
    second = next((clean_text(v) for v in cells[1:] if clean_text(v)), "")
    return _try_detect_across_cells(first, second)
```

### 子函数

| 函数 | 职责 | 行数估算 | 依赖 |
|------|------|----------|------|
| `_try_detect_in_first_cell(first)` | cleanup → detect_clause_in_text → has_title_text 校验 → ClauseMatch | ~8 | `detect_clause_in_text`, `has_title_text` |
| `_try_detect_in_segments(first)` | `\|` 分割 → 逐段匹配 → 排除不合法前缀 → ClauseMatch | ~15 | `detect_clause_in_text`, `re.match` |
| `_try_detect_across_cells(first, second)` | normalize → CLAUSE_HEAD_RE/ANNEX_HEAD_RE → has_title_text(second) → ClauseMatch | ~20 | `normalize_clause_leading_text`, `has_title_text`, `get_major_version`, 正则 |

每个子函数接收已清洗的字符串，返回 `ClauseMatch | None`。

### \_try\_detect\_across\_cells 细节

将原始路径 3 和 4 合并：
- 先校验 `has_title_text(second)`，失败返回 None
- `normalize_clause_leading_text(first)` 提净
- 先用 `CLAUSE_HEAD_RE` 匹配数字条款号（保留 `"-" in primary → None` 排除）
- 再用 `ANNEX_HEAD_RE` 匹配 Annex
- title_hint 统一为 `f"{normalized} | {second}"` 格式

### 文件变更范围

仅修改 `src/tuv_tools/core/splitter/parsing.py`：
- 新增 3 个私有函数（`_try_detect_in_first_cell`, `_try_detect_in_segments`, `_try_detect_across_cells`）
- 重写 `detect_clause_in_cells` 为编排函数
- 不修改其他文件，不修改 `build_sections` 或其他调用方

## 验证策略

现有 `tests/test_splitter.py::TestDetectClauseInCells` 的 7 个测试：
- `test_first_cell_clause` — 路径 1
- `test_segmented_cell` — 路径 2
- `test_second_cell_title` — 路径 3
- `test_annex_in_cell` — 路径 4
- `test_empty_cells` — 边界
- `test_no_match` — 边界

全部通过即为行为等价。同时运行已有的 `TestBuildSections` 和 `TestExportIntegration` 确保端到端结果不变。
