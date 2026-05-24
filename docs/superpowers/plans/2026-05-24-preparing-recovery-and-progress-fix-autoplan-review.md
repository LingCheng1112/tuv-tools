# /autoplan Review: Preparing Recovery and Progress Fix

**日期**: 2026-05-24  
**对象**: [2026-05-24-preparing-recovery-and-progress-fix-design.md](</O:/tuv-tools/docs/superpowers/specs/2026-05-24-preparing-recovery-and-progress-fix-design.md>)  
**模式**: 单审稿人降级模式（外部 Codex / Claude CLI 在合理等待窗口内未返回结果）

## Phase 1: CEO Review

### Premise Check

已确认的前提基本成立：

1. 预处理残留恢复是实际用户痛点，不是“锦上添花”
2. 多表进度回退会削弱可取消、可观察流程的可信度
3. `pywin32` 无条件依赖会扩大非 Windows 安装阻力

这些前提与当前代码面一致，且都在同一 blast radius 内：

- `PreparingWorker` 停止语义: [worker.py](</O:/tuv-tools/src/tuv_tools/core/preparing/worker.py:42>)
- 恢复与状态流的主入口: [splitter_view.py](</O:/tuv-tools/src/tuv_tools/ui/views/splitter_view.py:125>)
- 选择规则与右键行为: [document_list.py](</O:/tuv-tools/src/tuv_tools/ui/widgets/document_list.py:186>)
- 进度映射: [splitter_progress.py](</O:/tuv-tools/src/tuv_tools/ui/views/splitter_progress.py:25>)

### CEO Findings

1. **没有 scope challenge。**  
   这份 spec 的问题定义是对的，仍然应该优先解决。没有发现需要把任务拆成两个 feature 或完全换方向的理由。

2. **一个中等级别的 scope hygiene 问题。**  
   spec 把“恢复残留预处理”“跳过预处理拆分”“进度修复”“平台依赖调整”打包在一起是合理的，但实现时必须坚持只改 blast radius 内文件。不要顺手把导入流程、settings、通用任务系统一起重做。

3. **6 个月后最可能后悔的点不是方向，而是边界没写死。**  
   如果现在不把 `prepare_paused` 的入口、恢复规则、批量行为写得更显式，后面很容易演变成“这个状态看着像 pending，但又不是 pending”的维护债。

### CEO Verdict

- 问题是否值得解决：`是`
- 是否需要更大重构：`否`
- 是否有 user challenge：`无`
- CEO 评分：`8/10`

## Phase 2: Design Review

### What Was Examined

- 状态机设计: spec 第 1 节
- 启动恢复弹窗: spec 第 3 节
- `prepare_paused` 交互设计: spec 第 4-5 节
- 进度修复展示层: spec 第 6.2 节

### Design Findings

1. **`P2` 可发现性是一个 taste decision，不是阻塞问题。**  
   当前 spec 让 `prepare_paused` 的两个关键动作只出现在右键菜单里。这个方案改动小，但 discoverability 一般。  
   备选方案是在行状态或底部操作区给 paused 文档增加一个轻量 CTA。  
   我倾向先保守：第一版保留右键入口，避免把 UI 范围扩太大。

2. **`P2` 恢复弹窗需要明确“展示多少文件名”。**  
   spec 写了“展示前若干项”，但没有给边界。建议固定成“展示前 3-5 个，附总数”，否则不同实现者会做出不同 UI。

3. **`P2` `prepare_paused` 文案值得再收紧。**  
   当前文案是“已暂停预处理”。从用户理解上，“待确认恢复”或“预处理已暂停”会比纯状态词更清楚。这个不是结构问题，是文案层的选择。

### Design Verdict

- 结构是否成立：`成立`
- 是否需要返工 UI 结构：`不需要`
- Taste decisions：`2 个`
- Design 评分：`7/10`

## Phase 3: Eng Review

### What Was Examined

- `PreparingWorker` 当前阻塞点与 stop 机制: [worker.py](</O:/tuv-tools/src/tuv_tools/core/preparing/worker.py:31>)
- 关闭窗口等待逻辑: [splitter_view.py](</O:/tuv-tools/src/tuv_tools/ui/views/splitter_view.py:498>)
- 当前 `PreparingWorker` 测试覆盖: [test_preparing_worker.py](</O:/tuv-tools/tests/test_preparing_worker.py:31>)
- 进度 core / UI 契约: [parsing.py](</O:/tuv-tools/src/tuv_tools/core/splitter/parsing.py:370>), [splitter_progress.py](</O:/tuv-tools/src/tuv_tools/ui/views/splitter_progress.py:34>)
- 状态 helper 现状: [ui_helpers.py](</O:/tuv-tools/src/tuv_tools/core/splitter/ui_helpers.py:8>)

### Engineering Findings

1. **`P1` spec 里的 stop 重构缺了一半：它解决了“队尾继续跑”，但没有解决“空闲阻塞退出”。**  
   spec 第 2 节建议把 `stop()` 改成只设置 `_stop_requested = True`。  
   问题是当前 worker 在空闲时阻塞在 `queue.get(timeout=30)`，见 [worker.py](</O:/tuv-tools/src/tuv_tools/core/preparing/worker.py:31>) 和 [worker.py](</O:/tuv-tools/src/tuv_tools/core/preparing/worker.py:55>)。  
   如果只改成布尔标记，空闲 worker 在关闭窗口时最多还会卡 30 秒，`closeEvent(... wait(3000))` 依旧不可靠，见 [splitter_view.py](</O:/tuv-tools/src/tuv_tools/ui/views/splitter_view.py:504>)。  
   **Fix**: 设计里要保留“唤醒阻塞等待”的机制。可选：
   - 保留 `_STOP` 作为 wake-up sentinel，但语义改成“停止后不再消费新文档”
   - 或把 idle wait 改成很短的轮询，但这比 sentinel 更差

2. **`P2` spec 没把 `DocumentTable` 到 `SplitterView` 的新信号契约写显式。**  
   当前表格只有 `split_requested`、`open_output_requested`、`files_dropped` 等信号，见 [document_list.py](</O:/tuv-tools/src/tuv_tools/ui/widgets/document_list.py:30>)。  
   但新设计引入了两个动作：
   - `继续预处理`
   - `跳过预处理并拆分`
   
   spec 只描述了菜单动作，没有明确是否新增：
   - `resume_preparing_requested(doc_id)`
   - `skip_preparing_split_requested(doc_id)`
   
   **Fix**: 在 spec 的文件变更和交互章节里把这两个信号写死，否则实现者很容易把表格层和视图层耦合成直接调用。

3. **`P2` 数据访问层应从“可能修改”升级为“明确补 helper”。**  
   spec 目前把 [database.py](</O:/tuv-tools/src/tuv_tools/config/database.py:217>) 写成“可能修改”。  
   但恢复残留 `preparing`、批量转 `prepare_paused`、恢复缺失文件失败，都是稳定的数据访问动作。  
   **Fix**: 明确加至少一类 helper：
   - `get_documents_by_status(status: str) -> list[dict]`
   - 或 `get_preparing_documents()`
   - 若批量更新需要简单安全，增加 `update_documents_status(doc_ids, status, error=None)`

4. **`P2` progress core 侧需要写清统计口径。**  
   spec 第 6.1 节说要统计所有参与 `splitting_tables` 的总行数，但没有定义口径。  
   现状里 `_split_table_into_sections()` 会遍历每个表的每一行，且在 `build_sections()` 里它先于 `_should_ignore_table()` 调用，见 [parsing.py](</O:/tuv-tools/src/tuv_tools/core/splitter/parsing.py:456>)。  
   **Fix**: 明确“总行数 = `build_sections()` 中所有 table block 被 `_split_table_into_sections()` 实际扫描的行数总和”，这样实现者不会只统计命中条款的行，避免 percent 卡住后再跳。

5. **`P3` 现有测试计划还缺一个恢复拒绝后的批量行为断言。**  
   当前 spec 写了 `prepare_paused` 不参与全选和批量拆分，但测试计划里还没明确“批量拆分不会带上 paused 文档”的视图级断言。  
   **Fix**: 在 `tests/test_splitter_view.py` 增加批量入口回归，而不只测菜单和弹窗。

### Eng Verdict

- 是否可实施：`可以`
- 阻塞问题：`1 个高优先级`
- 建议在实现前先修 spec：`是`
- Eng 评分：`6/10`

## Phase 3.5: DX Review

本 spec 不属于 developer-facing feature。  
虽然涉及依赖安装声明，但不引入新的 API / CLI / 文档 onboarding 流程，因此 DX phase 按 autoplan 规则跳过。

- DX 评分：`skipped, no developer-facing scope`

## Cross-Phase Themes

**Theme: 状态和边界要显式。**  
CEO 和 Eng 两个 phase 都指向同一个问题：这次任务不怕“改得少”，怕“语义没写死”。  
高置信度信号是：

- `prepare_paused` 不能像模糊的 pending 变种一样存在
- stop 机制不能只改表面语义，不改阻塞唤醒
- UI 动作和 signal contract 要写显式

## Deferred

- 不做持久化预处理任务表
- 不做全局手动停止预处理按钮
- 不做 paused 行内 CTA 的第一版实现

## Autoplan Verdict

### Summary

这份 spec 方向是对的，范围也合理，没有发现需要推翻用户目标的 user challenge。  
但它还不能直接进入实现，至少要先修 1 个工程阻塞点和 2-3 个边界不清的问题，主要集中在 stop 唤醒机制、UI signal 契约、以及数据库 helper 明确化。

### Scores

- CEO: `8/10`
- Design: `7/10`
- Eng: `6/10`
- DX: `skipped`

### Decisions

- Auto-decided: `4`
- Taste decisions: `2`
- User challenges: `0`

### Recommended Next Step

先 revise spec，再开始 implementation plan。
