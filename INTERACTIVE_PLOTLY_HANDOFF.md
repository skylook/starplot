# Interactive Plotly Backend — 任务交接文档

> **最终状态更新（2026-07-16）：交互后端视觉一致性工作已完成。**
>
> 22/22 个示例已重新生成并由具备图像阅读能力的 agent 逐对检查通过。
> 最终验收证据、逐例结论、通用修正机制和测试限制请以
> [`docs/interactive-parity-ledger.md`](docs/interactive-parity-ledger.md)
> 为准。本文后续“尚未完成”“待解决问题”和早期 diff 数字是开发初期的历史诊断，
> 已被最终 ledger 取代，不应再作为当前状态或下一步任务清单。

## 项目概述

为 `starplot` 天文绘图库开发交互式 Plotly 后端，使其输出在视觉上与现有 Matplotlib 后端一致。

项目路径：`/Users/skylook/Develop/starplot`

## 架构

### Matplotlib 后端（已有）
- `src/starplot/plots/base.py` — `BasePlot` 基类
- `src/starplot/plots/map.py` — `MapPlot`（含 `ZenithPlot`）
- `src/starplot/plots/horizon.py` — `HorizonPlot`
- `src/starplot/plots/optic.py` — `OpticPlot`
- `src/starplot/plots/zenith.py` — `ZenithPlot`
- `src/starplot/plotters/` — 各种绘图 mixin（stars, dsos, constellations, milkyway, gradients, legend, arrow, text）
- 使用 Cartopy 投影，`DPI=100`，`resolution` 参数控制输出尺寸

### Interactive Plotly 后端（本次开发）
- `src/starplot/interactive/__init__.py` — 导出 4 个 Interactive 类
- `src/starplot/interactive/plots.py` — `InteractiveMapPlot`, `InteractiveZenithPlot`, `InteractiveHorizonPlot`, `InteractiveOpticPlot`，继承自对应 Matplotlib 类 + `RecordingMixin`，提供 `export_html()` 和 `to_plotly()` API
- `src/starplot/interactive/recording_mixin.py` — `RecordingMixin`，重写底层绘制方法，将 Matplotlib 绘图命令录制为 `DrawingCommand`
- `src/starplot/interactive/recorder.py` — `DrawingRecorder`，存储命令列表和投影/样式信息
- `src/starplot/interactive/commands.py` — `DrawingCommand` 数据类（kind/data/style/metadata/zorder/gid）
- `src/starplot/interactive/plotly_renderer.py` — `PlotlyRenderer`，将 `DrawingCommand` 列表渲染为 `plotly.graph_objects.Figure`
- `src/starplot/interactive/style_converter.py` — 样式转换工具

### 对比工具
- `comparison_outputs/run_comparison.py` — 全量跑 22 个示例，生成 3 组 PNG
- `comparison_outputs/diff_report.py` — 像素级对比，输出 `diff_report.md`
- `comparison_outputs/quick_run.py` — **单示例快速对比**（用法：`python quick_run.py horizon_sgr`）
- `comparison_outputs/report.md` — 最新对比报告

### 示例
- `examples/` — 22 个 Matplotlib 示例
- `examples/interactive/` — 22 个对应的 Interactive 示例

### 测试
- `tests/test_interactive/` — 59 个测试通过，1 个跳过
  - `test_commands.py`, `test_recorder.py`, `test_plotly_renderer.py`, `test_interactive_plots.py`, `test_visual_consistency.py`

## 迁移完成状态

### ✅ 功能迁移：已完成

**4 个 Interactive Plot 类全部实现**，继承自对应 Matplotlib 类 + `RecordingMixin`：

| 类 | 公开方法数 | 继承自 |
|----|-----------|--------|
| `InteractiveMapPlot` | 41 | `MapPlot` |
| `InteractiveZenithPlot` | 41 | `ZenithPlot` |
| `InteractiveHorizonPlot` | 41 | `HorizonPlot` |
| `InteractiveOpticPlot` | 38 | `OpticPlot` |

**所有公开绘图方法可用**：`stars`, `messier`, `galaxies`, `nebula`, `dsos`, `constellations`, `constellation_borders`, `constellation_labels`, `milky_way`, `planets`, `sun`, `moon`, `ecliptic`, `celestial_equator`, `horizon`, `gridlines`, `marker`, `line`, `polygon`, `rectangle`, `ellipse`, `circle`, `arrow`, `text`, `title`, `legend`, `star_magnitude_scale`, `info`, `optic_fov`, `zenith` 等。

**录制机制**：`RecordingMixin` 重写底层绘制方法（`_scatter_stars`, `_polygon`, `_text`, `line`, `marker`, `gridlines`, `constellations`, `horizon`, `ecliptic`, `celestial_equator`, `arrow`, `title`, `info`, `_plot_gradient_background`），上层方法（`stars`, `messier`, `planets`, `moon` 等）通过调用这些底层方法自动被录制。

**渲染器**：`PlotlyRenderer` 支持 7 种 `DrawingCommand`：`scatter`, `line`, `polygon`, `text`, `line_collection`, `gradient`, `info_table`。

**交互功能**：hover tooltip、legend toggle、click 事件等已实现。

### 历史诊断：视觉一致性当时尚未完成（现已解决）

历史像素差异（`nonzero%`）是开发初期的诊断数据，现已由
[`docs/interactive-parity-ledger.md`](docs/interactive-parity-ledger.md)
中的最终验收结论取代，不应作为当前状态参考。

## 历史待解决问题（均已解决或由最终 ledger 验收）

### 1. 尺寸/纵横比不一致（影响所有示例）

**现象**：
- Plotly 输出 1400×1000，Matplotlib 输出 4447×3172（3 倍差距）
- `export_html` 默认 `width=1200, height=900`，各示例已手动指定但仍不匹配
- `scaleanchor="y", scaleratio=1, constrain="domain"` 导致 Plotly 绘图区上下留白不对称（如 `horizon_double_cluster` 顶部黑边 30px、底部 10px）

**相关代码**：
- `src/starplot/interactive/plotly_renderer.py` 的 `_setup_layout()` 方法（约 120-170 行）
- `src/starplot/interactive/plots.py` 的 `export_html()` 和 `to_plotly()` 方法
- `src/starplot/plots/base.py` 的 `_fit_to_ax()` 方法（Matplotlib 如何调整 figsize）

**Matplotlib 行为**：
- `HorizonPlot` 用 `figsize=(self.figure_size, self.figure_size)` 创建正方形 figure
- `_fit_to_ax()` 根据 axes 实际窗口范围调整 figure 尺寸为非正方形
- `export()` 用 `bbox_inches="tight"` 裁剪，`pad_inches=padding * scale`
- 最终 PNG 尺寸 = figsize × DPI，如 4000×4000 → tight 裁剪后 4447×3172

**Plotly 当前行为**：
- 用 `width/height` 参数直接指定像素尺寸
- `scaleanchor="y", scaleratio=1` 强制 1:1 纵横比，`constrain="domain"` 导致留白

**建议方向**：
- 计算正确的 width/height 比例，使 Plotly 绘图区与 Matplotlib axes 区域比例一致
- 或者去掉 `scaleanchor`/`scaleratio`，让 Plotly 自由拉伸 axes 填满绘图区（Matplotlib Cartopy GeoAxes 就是这么做的）

### 2. 渐变背景颜色偏差（影响 horizon 示例）

**现象**：
- Plotly `Heatmap` 渐变中心像素 `[0,10,45]`，Matplotlib `gouraud` 渐变中心 `[0,13,55]`
- 颜色过渡不一致，`horizon_gradient` 差异高达 68%

**相关代码**：
- `src/starplot/interactive/plotly_renderer.py` 的 `_render_gradient()` 方法（约 407-461 行）
- `src/starplot/plotters/gradients.py` — Matplotlib 渐变实现（参考）

**Matplotlib 实现**：
- 用 `pcolormesh` + `shading='gouraud'` 渲染渐变
- `LinearSegmentedColormap.from_list()` 创建 colormap，`N=750`
- 垂直渐变：`y_array = np.linspace(0, 1, 750)`，`gradient = np.linspace(0, 1, 750).reshape(-1, 1).repeat(2, axis=1)`

**Plotly 当前实现**：
- 用 `go.Heatmap` 渲染，`zsmooth=False`，`zmin=0.0`, `zmax=1.0`
- `steps=2000` 的 `np.linspace` 生成 y 和 z
- colorscale 直接传入 color stops

**已验证**：
- Plotly `Heatmap` 的 colorscale 插值与 Matplotlib `LinearSegmentedColormap` 在相同 z=0.5 处颜色一致（都是 `[27,26,90]`），说明 colorscale 本身没问题
- 差异来自 `Heatmap` 像素映射方式与 `gouraud` 不同

**建议方向**：
- 方案 A：用 `layout_image`（PNG data URL）替代 `Heatmap`，自己用 matplotlib colormap 生成渐变 PNG，作为背景图铺满绘图区
- 方案 B：调整 `Heatmap` 参数（`zsmooth`、y 范围）使其更接近 `gouraud`
- 方案 A 已验证可行（测试代码生成 `[0,10,46]` 接近 Matplotlib 的 `[0,11,46]`）

### 3. `map_milky_way_stars` 示例缺失

**现象**：diff report 显示 `missing`

**原因**：该示例有 `skip_write_image` 标志，未生成 Plotly PNG

**相关文件**：`examples/interactive/map_milky_way_stars_interactive.py`

### 4. `BIG_SKY_MAG11` 导入问题

**现象**：某些示例依赖此数据但导入失败

**相关代码**：搜索 `BIG_SKY_MAG11` 或 `BIG_SKY` 在 `src/starplot/` 中的引用

### 5. 边距不对称

**现象**：Plotly 顶部/底部留白不均匀（如 `horizon_double_cluster` 顶部 30px、底部 10px）

**原因**：`constrain="domain"` + `scaleanchor` 导致 Plotly 在保持纵横比时将绘图区偏移

**建议**：与问题 1 一起解决

## 关键文件索引

| 文件 | 作用 | 关键行 |
|------|------|--------|
| `src/starplot/interactive/plotly_renderer.py` | 核心渲染器 | `_setup_layout` ~120行, `_render_gradient` ~407行, `_render_polygon` ~288行, `_render_scatter` ~189行 |
| `src/starplot/interactive/plots.py` | 用户 API | `export_html` ~27行, `to_plotly` ~53行, 各类默认 width/height ~82-129行 |
| `src/starplot/interactive/recording_mixin.py` | 录制 Matplotlib 命令 | `_record_plot_info` ~88行, `_scatter_stars` ~147行, `_polygon` ~220行, `horizon` ~682行, `_plot_gradient_background` ~1091行 |
| `src/starplot/interactive/recorder.py` | 存储命令 | `record_*` 方法 |
| `src/starplot/interactive/commands.py` | DrawingCommand 数据类 | 7 种 kind |
| `src/starplot/interactive/style_converter.py` | 样式转换 | |
| `src/starplot/plots/base.py` | Matplotlib 基类 | `_fit_to_ax` ~180行, `export` ~223行 |
| `src/starplot/plots/horizon.py` | Matplotlib HorizonPlot | figure 创建 ~555行 |
| `src/starplot/plotters/gradients.py` | Matplotlib 渐变 | `_create_gradient_arrays` ~102行 |
| `comparison_outputs/quick_run.py` | 单示例快速对比 | `python quick_run.py <示例名>` |
| `comparison_outputs/diff_report.py` | 像素对比 | |
| `comparison_outputs/run_comparison.py` | 全量对比（慢） | |

## 工作流程建议

1. **不要全量跑** `run_comparison.py`，太慢（22 个示例 + 高分辨率渲染 + kaleido 截图）
2. **用 `quick_run.py` 单步调试**：
   ```bash
   cd comparison_outputs
   python quick_run.py horizon_double_cluster
   python diff_report.py  # 只看这一个示例的 diff
   ```
3. **改代码前先读** `plotly_renderer.py` 的相关函数，理解现有实现
4. **改完后用 `quick_run.py` 验证**，确认改善后再跑下一个示例
5. **最后全量跑一次** `run_comparison.py` 确认没有回归

## 环境信息

- Python 3.12
- 依赖：plotly, kaleido, matplotlib, cartopy, numpy, pandas, ibis, duckdb, shapely, pydantic
- 测试：`python -m pytest tests/test_interactive/ -x --tb=line -q`（59 passed, 1 skipped）
- 数据：starplot catalogs + de421.bsp（首次运行会自动下载）
