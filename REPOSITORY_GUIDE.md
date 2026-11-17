# Bellows-L — Repository guide / 文件导航

[English](README.md) · [简体中文](README.zh-CN.md)

Documentation inventory checked on 2026-11-17, against repository base `46cac938c557efc953cc353e3f90ec6294f46c9f`.

## Reading the inventory / 阅读方法

This is a path-level index, not a new experiment or a recertification. Each measurement belongs to the exact linked record and directory. Different copies of a chip can contain different source revisions and results. A recorded pass does not imply that another copy, model size, software stack or board image passed.

本页按实际路径列出交付物，不代表新实验或重新签核。同名芯片的多份目录可能有不同源码和结果；一份记录的通过不外推到其他副本、模型规模、软件栈或板卡镜像。

## Source, tests and reports / 源码、测试与报告

| Existing directory | Source / constraints | Public tests / technical documents | Reports |
| --- | --- | --- | --- |
| [`bellows-l1/`](bellows-l1/) | [`bellows-l1/rtl/`](bellows-l1/rtl/) | [`bellows-l1/tests/`](bellows-l1/tests/) · [`bellows-l1/design/`](bellows-l1/design/) · [`bellows-l1/README.md`](bellows-l1/README.md) | [`bellows-l1/REPORT.md`](bellows-l1/REPORT.md) · [`bellows-l1/REPORT.pdf`](bellows-l1/REPORT.pdf) · [`bellows-l1/SHOWCASE_REPORT.pdf`](bellows-l1/SHOWCASE_REPORT.pdf) · [`bellows-l1/SHOWCASE_REPORT.zh-CN.pdf`](bellows-l1/SHOWCASE_REPORT.zh-CN.pdf) |
| [`bellows-l2/`](bellows-l2/) | [`bellows-l2/rtl/`](bellows-l2/rtl/) | [`bellows-l2/tests/`](bellows-l2/tests/) · [`bellows-l2/design/`](bellows-l2/design/) · [`bellows-l2/README.md`](bellows-l2/README.md) | [`bellows-l2/REPORT.md`](bellows-l2/REPORT.md) · [`bellows-l2/REPORT.pdf`](bellows-l2/REPORT.pdf) · [`bellows-l2/SHOWCASE_REPORT.pdf`](bellows-l2/SHOWCASE_REPORT.pdf) · [`bellows-l2/SHOWCASE_REPORT.zh-CN.pdf`](bellows-l2/SHOWCASE_REPORT.zh-CN.pdf) |
| [`bellows-l3/`](bellows-l3/) | [`bellows-l3/rtl/`](bellows-l3/rtl/) | [`bellows-l3/tests/`](bellows-l3/tests/) · [`bellows-l3/design/`](bellows-l3/design/) · [`bellows-l3/README.md`](bellows-l3/README.md) | [`bellows-l3/REPORT.md`](bellows-l3/REPORT.md) · [`bellows-l3/REPORT.pdf`](bellows-l3/REPORT.pdf) · [`bellows-l3/SHOWCASE_REPORT.pdf`](bellows-l3/SHOWCASE_REPORT.pdf) · [`bellows-l3/SHOWCASE_REPORT.zh-CN.pdf`](bellows-l3/SHOWCASE_REPORT.zh-CN.pdf) |
| [`bellows-l4/`](bellows-l4/) | [`bellows-l4/rtl/`](bellows-l4/rtl/) | [`bellows-l4/tests/`](bellows-l4/tests/) · [`bellows-l4/design/`](bellows-l4/design/) | [`bellows-l4/REPORT.md`](bellows-l4/REPORT.md) · [`bellows-l4/REPORT.pdf`](bellows-l4/REPORT.pdf) · [`bellows-l4/SHOWCASE_REPORT.pdf`](bellows-l4/SHOWCASE_REPORT.pdf) · [`bellows-l4/SHOWCASE_REPORT.zh-CN.pdf`](bellows-l4/SHOWCASE_REPORT.zh-CN.pdf) |
| [`bellows-l5/`](bellows-l5/) | [`bellows-l5/rtl/`](bellows-l5/rtl/) | [`bellows-l5/tests/`](bellows-l5/tests/) · [`bellows-l5/design/`](bellows-l5/design/) | — |
| [`bellows_l1/`](bellows_l1/) | [`bellows_l1/rtl/`](bellows_l1/rtl/) | [`bellows_l1/tests/`](bellows_l1/tests/) · [`bellows_l1/design/`](bellows_l1/design/) | [`bellows_l1/REPORT.md`](bellows_l1/REPORT.md) · [`bellows_l1/REPORT.pdf`](bellows_l1/REPORT.pdf) · [`bellows_l1/SHOWCASE_REPORT.pdf`](bellows_l1/SHOWCASE_REPORT.pdf) · [`bellows_l1/SHOWCASE_REPORT.zh-CN.pdf`](bellows_l1/SHOWCASE_REPORT.zh-CN.pdf) |
| [`bellows_l2/`](bellows_l2/) | [`bellows_l2/rtl/`](bellows_l2/rtl/) | [`bellows_l2/tests/`](bellows_l2/tests/) · [`bellows_l2/design/`](bellows_l2/design/) | [`bellows_l2/REPORT.md`](bellows_l2/REPORT.md) · [`bellows_l2/REPORT.pdf`](bellows_l2/REPORT.pdf) · [`bellows_l2/SHOWCASE_REPORT.pdf`](bellows_l2/SHOWCASE_REPORT.pdf) · [`bellows_l2/SHOWCASE_REPORT.zh-CN.pdf`](bellows_l2/SHOWCASE_REPORT.zh-CN.pdf) |
| [`bellows_l3/`](bellows_l3/) | [`bellows_l3/rtl/`](bellows_l3/rtl/) | [`bellows_l3/tests/`](bellows_l3/tests/) · [`bellows_l3/design/`](bellows_l3/design/) | [`bellows_l3/REPORT.md`](bellows_l3/REPORT.md) · [`bellows_l3/REPORT.pdf`](bellows_l3/REPORT.pdf) · [`bellows_l3/SHOWCASE_REPORT.pdf`](bellows_l3/SHOWCASE_REPORT.pdf) · [`bellows_l3/SHOWCASE_REPORT.zh-CN.pdf`](bellows_l3/SHOWCASE_REPORT.zh-CN.pdf) |
| [`bellows_l4/`](bellows_l4/) | [`bellows_l4/rtl/`](bellows_l4/rtl/) | [`bellows_l4/tests/`](bellows_l4/tests/) · [`bellows_l4/design/`](bellows_l4/design/) | [`bellows_l4/REPORT.md`](bellows_l4/REPORT.md) · [`bellows_l4/REPORT.pdf`](bellows_l4/REPORT.pdf) · [`bellows_l4/SHOWCASE_REPORT.pdf`](bellows_l4/SHOWCASE_REPORT.pdf) · [`bellows_l4/SHOWCASE_REPORT.zh-CN.pdf`](bellows_l4/SHOWCASE_REPORT.zh-CN.pdf) |
| [`bellows_l5/`](bellows_l5/) | [`bellows_l5/rtl/`](bellows_l5/rtl/) | [`bellows_l5/tests/`](bellows_l5/tests/) · [`bellows_l5/design/`](bellows_l5/design/) | — |
| [`chips/bellows_l1/`](chips/bellows_l1/) | [`chips/bellows_l1/rtl/`](chips/bellows_l1/rtl/) | [`chips/bellows_l1/tests/`](chips/bellows_l1/tests/) · [`chips/bellows_l1/design/`](chips/bellows_l1/design/) | [`chips/bellows_l1/REPORT.md`](chips/bellows_l1/REPORT.md) · [`chips/bellows_l1/REPORT.pdf`](chips/bellows_l1/REPORT.pdf) · [`chips/bellows_l1/SHOWCASE_REPORT.pdf`](chips/bellows_l1/SHOWCASE_REPORT.pdf) · [`chips/bellows_l1/SHOWCASE_REPORT.zh-CN.pdf`](chips/bellows_l1/SHOWCASE_REPORT.zh-CN.pdf) |
| [`chips/bellows_l2/`](chips/bellows_l2/) | [`chips/bellows_l2/rtl/`](chips/bellows_l2/rtl/) | [`chips/bellows_l2/tests/`](chips/bellows_l2/tests/) · [`chips/bellows_l2/design/`](chips/bellows_l2/design/) | [`chips/bellows_l2/REPORT.md`](chips/bellows_l2/REPORT.md) · [`chips/bellows_l2/REPORT.pdf`](chips/bellows_l2/REPORT.pdf) · [`chips/bellows_l2/SHOWCASE_REPORT.pdf`](chips/bellows_l2/SHOWCASE_REPORT.pdf) · [`chips/bellows_l2/SHOWCASE_REPORT.zh-CN.pdf`](chips/bellows_l2/SHOWCASE_REPORT.zh-CN.pdf) |
| [`chips/bellows_l3/`](chips/bellows_l3/) | [`chips/bellows_l3/rtl/`](chips/bellows_l3/rtl/) | [`chips/bellows_l3/tests/`](chips/bellows_l3/tests/) · [`chips/bellows_l3/design/`](chips/bellows_l3/design/) | [`chips/bellows_l3/REPORT.md`](chips/bellows_l3/REPORT.md) · [`chips/bellows_l3/REPORT.pdf`](chips/bellows_l3/REPORT.pdf) · [`chips/bellows_l3/SHOWCASE_REPORT.pdf`](chips/bellows_l3/SHOWCASE_REPORT.pdf) · [`chips/bellows_l3/SHOWCASE_REPORT.zh-CN.pdf`](chips/bellows_l3/SHOWCASE_REPORT.zh-CN.pdf) |
| [`chips/bellows_l4/`](chips/bellows_l4/) | [`chips/bellows_l4/rtl/`](chips/bellows_l4/rtl/) | [`chips/bellows_l4/tests/`](chips/bellows_l4/tests/) · [`chips/bellows_l4/design/`](chips/bellows_l4/design/) | [`chips/bellows_l4/REPORT.md`](chips/bellows_l4/REPORT.md) · [`chips/bellows_l4/REPORT.pdf`](chips/bellows_l4/REPORT.pdf) · [`chips/bellows_l4/SHOWCASE_REPORT.pdf`](chips/bellows_l4/SHOWCASE_REPORT.pdf) · [`chips/bellows_l4/SHOWCASE_REPORT.zh-CN.pdf`](chips/bellows_l4/SHOWCASE_REPORT.zh-CN.pdf) |
| [`chips/bellows_l5/`](chips/bellows_l5/) | [`chips/bellows_l5/rtl/`](chips/bellows_l5/rtl/) | [`chips/bellows_l5/tests/`](chips/bellows_l5/tests/) · [`chips/bellows_l5/design/`](chips/bellows_l5/design/) | — |

## Public result records / 公开结果记录

Status and numbers below are transcribed only from the linked record. Functional simulation, generic synthesis, standalone/virtual-pin timing, bridge connectivity, workload readback and system-software execution are separate scopes. Missing entries mean that this index found no matching public record at that path, not that an experiment failed or never occurred.

下表状态与数值只来自对应文件。功能仿真、通用综合、独立 IP／虚拟引脚时序、桥接连通性、工作负载读回和系统软件执行分别解释；未列出不等于判定失败或从未做过。

| Exact directory | Record | Recorded result and scope |
| --- | --- | --- |
| `bellows-l1` | [`bellows-l1/evidence/verification-receipts.json`](bellows-l1/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows-l1` | [`bellows-l1/evidence/rtl-timing-lint.json`](bellows-l1/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `bellows-l1` | [`bellows-l1/evidence/quartus-sta.json`](bellows-l1/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `435.54`; setup slack ns: `7.704`; hold slack ns: `-0.196` |
| `bellows-l1` | [`bellows-l1/evidence/ppa-resource-summary.json`](bellows-l1/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows-l2` | [`bellows-l2/evidence/verification-receipts.json`](bellows-l2/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows-l2` | [`bellows-l2/evidence/rtl-timing-lint.json`](bellows-l2/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `bellows-l2` | [`bellows-l2/evidence/quartus-sta.json`](bellows-l2/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `151.63`; setup slack ns: `3.405`; hold slack ns: `0.05` |
| `bellows-l2` | [`bellows-l2/evidence/ppa-resource-summary.json`](bellows-l2/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows-l2` | [`bellows-l2/evidence/board-hil.json`](bellows-l2/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `bellows-l3` | [`bellows-l3/evidence/verification-receipts.json`](bellows-l3/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows-l3` | [`bellows-l3/evidence/rtl-timing-lint.json`](bellows-l3/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `bellows-l3` | [`bellows-l3/evidence/quartus-sta.json`](bellows-l3/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `127.11`; setup slack ns: `2.133`; hold slack ns: `0.045` |
| `bellows-l3` | [`bellows-l3/evidence/ppa-resource-summary.json`](bellows-l3/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows-l3` | [`bellows-l3/evidence/board-hil.json`](bellows-l3/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `bellows-l4` | [`bellows-l4/evidence/verification-receipts.json`](bellows-l4/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows-l4` | [`bellows-l4/evidence/rtl-timing-lint.json`](bellows-l4/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `bellows-l4` | [`bellows-l4/evidence/quartus-sta.json`](bellows-l4/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `103.35`; setup slack ns: `0.324`; hold slack ns: `0.038` |
| `bellows-l4` | [`bellows-l4/evidence/ppa-resource-summary.json`](bellows-l4/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows-l4` | [`bellows-l4/evidence/board-hil.json`](bellows-l4/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `bellows-l5` | [`bellows-l5/evidence/verification-receipts.json`](bellows-l5/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows-l5` | [`bellows-l5/evidence/rtl-timing-lint.json`](bellows-l5/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `bellows-l5` | [`bellows-l5/evidence/quartus-sta.json`](bellows-l5/evidence/quartus-sta.json) | recorded status: `failed` |
| `bellows-l5` | [`bellows-l5/evidence/ppa-resource-summary.json`](bellows-l5/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows_l1` | [`bellows_l1/evidence/verification-receipts.json`](bellows_l1/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows_l1` | [`bellows_l1/evidence/rtl-timing-lint.json`](bellows_l1/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `bellows_l1` | [`bellows_l1/evidence/quartus-sta.json`](bellows_l1/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `435.54`; setup slack ns: `7.704`; hold slack ns: `-0.196` |
| `bellows_l1` | [`bellows_l1/evidence/ppa-resource-summary.json`](bellows_l1/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows_l2` | [`bellows_l2/evidence/verification-receipts.json`](bellows_l2/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows_l2` | [`bellows_l2/evidence/rtl-timing-lint.json`](bellows_l2/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `bellows_l2` | [`bellows_l2/evidence/quartus-sta.json`](bellows_l2/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `151.63`; setup slack ns: `3.405`; hold slack ns: `0.05` |
| `bellows_l2` | [`bellows_l2/evidence/ppa-resource-summary.json`](bellows_l2/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows_l2` | [`bellows_l2/evidence/board-hil.json`](bellows_l2/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `bellows_l3` | [`bellows_l3/evidence/verification-receipts.json`](bellows_l3/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows_l3` | [`bellows_l3/evidence/rtl-timing-lint.json`](bellows_l3/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `bellows_l3` | [`bellows_l3/evidence/quartus-sta.json`](bellows_l3/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `127.11`; setup slack ns: `2.133`; hold slack ns: `0.045` |
| `bellows_l3` | [`bellows_l3/evidence/ppa-resource-summary.json`](bellows_l3/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows_l3` | [`bellows_l3/evidence/board-hil.json`](bellows_l3/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `bellows_l4` | [`bellows_l4/evidence/verification-receipts.json`](bellows_l4/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows_l4` | [`bellows_l4/evidence/rtl-timing-lint.json`](bellows_l4/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `bellows_l4` | [`bellows_l4/evidence/quartus-sta.json`](bellows_l4/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `103.35`; setup slack ns: `0.324`; hold slack ns: `0.038` |
| `bellows_l4` | [`bellows_l4/evidence/ppa-resource-summary.json`](bellows_l4/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows_l4` | [`bellows_l4/evidence/board-hil.json`](bellows_l4/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `bellows_l5` | [`bellows_l5/evidence/verification-receipts.json`](bellows_l5/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `bellows_l5` | [`bellows_l5/evidence/rtl-timing-lint.json`](bellows_l5/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `bellows_l5` | [`bellows_l5/evidence/quartus-sta.json`](bellows_l5/evidence/quartus-sta.json) | recorded status: `failed` |
| `bellows_l5` | [`bellows_l5/evidence/ppa-resource-summary.json`](bellows_l5/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/bellows_l1` | [`chips/bellows_l1/evidence/verification-receipts.json`](chips/bellows_l1/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/bellows_l1` | [`chips/bellows_l1/evidence/rtl-timing-lint.json`](chips/bellows_l1/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `chips/bellows_l1` | [`chips/bellows_l1/evidence/quartus-sta.json`](chips/bellows_l1/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `435.54`; setup slack ns: `7.704`; hold slack ns: `-0.196` |
| `chips/bellows_l1` | [`chips/bellows_l1/evidence/ppa-resource-summary.json`](chips/bellows_l1/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/bellows_l2` | [`chips/bellows_l2/evidence/verification-receipts.json`](chips/bellows_l2/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/bellows_l2` | [`chips/bellows_l2/evidence/rtl-timing-lint.json`](chips/bellows_l2/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `chips/bellows_l2` | [`chips/bellows_l2/evidence/quartus-sta.json`](chips/bellows_l2/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `151.63`; setup slack ns: `3.405`; hold slack ns: `0.05` |
| `chips/bellows_l2` | [`chips/bellows_l2/evidence/ppa-resource-summary.json`](chips/bellows_l2/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/bellows_l2` | [`chips/bellows_l2/evidence/board-hil.json`](chips/bellows_l2/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `chips/bellows_l3` | [`chips/bellows_l3/evidence/verification-receipts.json`](chips/bellows_l3/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/bellows_l3` | [`chips/bellows_l3/evidence/rtl-timing-lint.json`](chips/bellows_l3/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `chips/bellows_l3` | [`chips/bellows_l3/evidence/quartus-sta.json`](chips/bellows_l3/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `127.11`; setup slack ns: `2.133`; hold slack ns: `0.045` |
| `chips/bellows_l3` | [`chips/bellows_l3/evidence/ppa-resource-summary.json`](chips/bellows_l3/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/bellows_l3` | [`chips/bellows_l3/evidence/board-hil.json`](chips/bellows_l3/evidence/board-hil.json) | recorded status: `passed`; scope: SoftReg/M20K stimulus profiles and output/counter telemetry as specified in this record; not a blanket full-model/system execution claim |
| `chips/bellows_l4` | [`chips/bellows_l4/evidence/verification-receipts.json`](chips/bellows_l4/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/bellows_l4` | [`chips/bellows_l4/evidence/rtl-timing-lint.json`](chips/bellows_l4/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `chips/bellows_l4` | [`chips/bellows_l4/evidence/quartus-sta.json`](chips/bellows_l4/evidence/quartus-sta.json) | recorded status: `passed`; Fmax MHz: `103.35`; setup slack ns: `0.324`; hold slack ns: `0.038` |
| `chips/bellows_l4` | [`chips/bellows_l4/evidence/ppa-resource-summary.json`](chips/bellows_l4/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/bellows_l4` | [`chips/bellows_l4/evidence/board-hil.json`](chips/bellows_l4/evidence/board-hil.json) | recorded status: `passed`; scope: BAR0/reg57 bridge-connectivity probe only; not per-chip workload execution |
| `chips/bellows_l5` | [`chips/bellows_l5/evidence/verification-receipts.json`](chips/bellows_l5/evidence/verification-receipts.json) | Recorded artifact; inspect its applicability, source binding and scope. |
| `chips/bellows_l5` | [`chips/bellows_l5/evidence/rtl-timing-lint.json`](chips/bellows_l5/evidence/rtl-timing-lint.json) | recorded status: `passed` |
| `chips/bellows_l5` | [`chips/bellows_l5/evidence/quartus-sta.json`](chips/bellows_l5/evidence/quartus-sta.json) | recorded status: `failed` |
| `chips/bellows_l5` | [`chips/bellows_l5/evidence/ppa-resource-summary.json`](chips/bellows_l5/evidence/ppa-resource-summary.json) | Recorded artifact; inspect its applicability, source binding and scope. |

## File-management policy / 文件管理约定

- Keep RTL, constraints, tests and result originals in their existing locations. This documentation refresh does not move or delete them.
- Hyphenated, underscored and `chips/` directories are separate existing trees, not interchangeable aliases. The index lists all of them without declaring one authoritative.
- Preserve dated reports as publications. Update the README and this guide when the public source/evidence changes; do not silently rewrite an old result.
- Keep chip artifacts separate from the private Vulcan implementation. Public reproducibility instructions must not require private framework code or internal operation traces.

保留现有源码、约束、测试和原始证据路径；连字符、下划线和 `chips/` 多份目录不自动视为等价。历史报告保留其发表时范围，公开复现不得依赖私有框架实现。
