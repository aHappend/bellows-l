<div align="center">
  <h1>BELLOWS-L3 · 高吞吐流式 LZ4 压缩与解压硬件加速芯片</h1>
  <p><strong>流式 LZ4 滑动窗口解压、哈希匹配表硬件压缩与多通道校验子系统</strong></p>
  <p>
    <img src="https://img.shields.io/badge/Quartus_17.1_STA-127.11%20MHz-0f766e?style=flat-square" alt="STA Fmax">
    <img src="https://img.shields.io/badge/Setup_WNS-%2B2.133%20ns-0f766e?style=flat-square" alt="WNS">
    <img src="https://img.shields.io/badge/Arria_10_PCIe_HIL-PASSED%20(3%2F3)-1d4ed8?style=flat-square" alt="FPGA HIL">
    <img src="https://img.shields.io/badge/Author-Sufeng_Guo_(MSRA)-334155?style=flat-square" alt="Author">
  </p>
  <p>
    <a href="../README.zh-CN.md">返回系列主页</a> ·
    <a href="SHOWCASE_REPORT.zh-CN.pdf"><strong>中文学术白皮书 (PDF)</strong></a> ·
    <a href="SHOWCASE_REPORT.pdf"><strong>英文学术白皮书 (PDF)</strong></a> ·
    <a href="REPORT.pdf"><strong>开发者工程签核报告 (PDF)</strong></a> ·
    <a href="rtl/">RTL 源码</a> ·
    <a href="README.md"><strong>English</strong></a>
  </p>
</div>

---

## 核心硬件签核指标总览

**BELLOWS-L3** 是由 **Vulcan** 面向 **流式 LZ4 滑动窗口解压、哈希匹配表硬件压缩与多通道校验子系统** 全自动架构设计、RTL 实现并通过四级硬件签核的 `100 MHz+` 专用硬件加速芯片，目标运行平台为 **Intel Arria 10 GX (10AX115N3F40E2SG) PCIe Gen3x8 加速卡**。

| 签核维度 | 实测指标 | 工程验证说明 |
| :--- | :--- | :--- |
| **功能与数值一致性** | **100% 比特级精确匹配** | 全测试集硬件输出与黄金参考标准零偏差 |
| **参考模型余弦相似度 / 精度** | **0.999999995** | 硬件定点输出与官方 FP32 浮点基准余弦相似度 |
| **Quartus 17.1 静态时序 (STA)** | **Fmax = 127.11 MHz (`WNS = +2.133 ns`)** | `100.0 MHz` (`10.0 ns`) 时序基线 `0` 建立/保持违例签核 |
| **Intel Arria 10 GX 资源占用** | **3.31% ALMs · 0.53% DSPs** | `14,138 / 427,200` ALMs · `512 / 2,713` M20K · `8 / 1,518` DSPs |
| **物理 FPGA 板级实测 (HIL)** | **通过 (`3/3` 轮，`0` 误差)** | Intel Arria 10 GX (`10AX115N3F40E2SG`, `chip_id = 23645547322997765`) PCIe Gen3x8 实测 |

## 中文学术白皮书分页预览 (`SHOWCASE_REPORT.zh-CN.pdf`)

<table>
  <tr>
    <td align="center" width="33%"><a href="SHOWCASE_REPORT.zh-CN.pdf"><img src="showcase_figures_zh/page-1.png" width="100%" alt="第 1 页"></a><br><sub><strong>第 1 页 · 核心指标总览与微架构拓扑</strong></sub></td>
    <td align="center" width="33%"><a href="SHOWCASE_REPORT.zh-CN.pdf"><img src="showcase_figures_zh/page-2.png" width="100%" alt="第 2 页"></a><br><sub><strong>第 2 页 · 实验基准测试与精度对比分析</strong></sub></td>
    <td align="center" width="33%"><a href="SHOWCASE_REPORT.zh-CN.pdf"><img src="showcase_figures_zh/page-3.png" width="100%" alt="第 3 页"></a><br><sub><strong>第 3 页 · Arria 10 STA、板级 HIL 与演进路线</strong></sub></td>
  </tr>
</table>

## 单语双轨制文档体系

| 文档类别 | 链接 | 内容定位 |
| :--- | :--- | :--- |
| **中文学术产品白皮书** | [**`SHOWCASE_REPORT.zh-CN.pdf`**](SHOWCASE_REPORT.zh-CN.pdf) · [`SHOWCASE_REPORT.zh-CN.md`](SHOWCASE_REPORT.zh-CN.md) | IEEE/ACM 双栏学术论文排版，涵盖架构创新、实测基准对比、FPGA 资源剖析与演进规划 |
| **英文学术产品白皮书** | [**`SHOWCASE_REPORT.pdf`**](SHOWCASE_REPORT.pdf) · [`SHOWCASE_REPORT.md`](SHOWCASE_REPORT.md) | 纯英文正式版学术产品白皮书 |
| **开发者工程签核报告** | [**`REPORT.pdf`**](REPORT.pdf) · [`REPORT.md`](REPORT.md) | 完整 SystemVerilog RTL 微架构、接口时序协议、定点数值边界与验证台账 |
| **自主研发历程日志** | [`.vulcan/engineering/JOURNEY.zh-CN.md`](.vulcan/engineering/JOURNEY.zh-CN.md) | Coordinator、Designer、Verifier、Reviewer 四角色闭环研发记录 |

---
<p align="center"><sub>作者：<strong>Sufeng Guo</strong> · 微软亚洲研究院 (Microsoft Research Asia) · <a href="mailto:sufeng_guo@smail.nju.edu.cn">sufeng_guo@smail.nju.edu.cn</a></sub></p>
