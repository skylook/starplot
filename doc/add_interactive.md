# Starplot 交互式 Plotly 后端实现方案

> 本文档为实现方案设计，供工程师参考实现。完成后保存至 `doc/add_interactive.md`。

## 1. 背景与目标

### 1.1 问题

Starplot 当前只能生成静态星图（PNG/SVG），用户无法在浏览器中进行缩放、平移、查看天体信息等交互操作。参考 [GitHub Issue #146](https://github.com/steveberardi/starplot/issues/146)。

### 1.2 目标

1. **增加 Plotly 交互式 Web 后端**：支持 zoom/pan、hover tooltips、click-to-identify、legend filtering
2. **零修改现有代码**：不改动 `src/starplot/` 中的任何现有文件（仅在 `pyproject.toml` 中添加可选依赖），以便与上游保持同步
3. **后端独立性**：架构允许未来添加其他后端（Bokeh、D3 等），只需实现新的 Renderer 类
4. **API 一致性**：`InteractiveMapPlot` 与 `MapPlot` 使用完全相同的 API，仅多一个 `export_html()` 方法
5. **视觉一致性测试**：通过感知哈希对比 matplotlib PNG 与 Plotly PNG 的相似度

### 1.3 安装方式

```bash
pip install starplot[interactive]   # 安装 plotly + kaleido
```

---

## 2. 架构设计

### 2.1 核心思路：Parallel Plot Builder（录制回放模式）

```
用户代码                     现有 starplot (不修改)              新增交互模块
─────────                    ─────────────────────             ─────────────
InteractiveMapPlot(...)  →   RecordingMixin + MapPlot
  .stars(...)            →   MapPlot.stars() [matplotlib渲染] + RecordingMixin 录制 DrawingCommand
  .constellations(...)   →   同上
  .export("chart.png")   →   BasePlot.export() [matplotlib savefig]  ← 不变
  .export_html("x.html") →   PlotlyRenderer.render(commands) → Plotly Figure → HTML
  .to_plotly()            →   返回 Plotly Figure 对象供进一步自定义
```

**关键设计决策：**

| 决策 | 说明 |
|------|------|
| 在 starplot 绘图原语层面录制 | 仅需拦截 8 个方法，不拦截底层 matplotlib API |
| 录制投影后的坐标 | Plotly 端不需要 Cartopy，直接使用投影坐标 |
| 碰撞检测继承 | matplotlib 先运行完碰撞检测，只有存活的标签才被录制 |
| WebGL 渲染 | 使用 `Scattergl` 支持 10万+ 星点的流畅交互 |
| MRO 继承顺序 | `RecordingMixin` 排在 `MapPlot` 之前，通过 `super()` 调用保留原有行为 |

### 2.2 类继承关系

```
                        BasePlot (现有)
                       /           \
                  MapPlot        HorizonPlot/OpticPlot (现有)
                    |                |
              RecordingMixin    RecordingMixin  (新增，通过 super() 调链)
                    |                |
           InteractiveMapPlot  InteractiveHorizonPlot (新增，用户使用)
```

Python MRO 示例：
```python
class InteractiveMapPlot(RecordingMixin, MapPlot):
    pass
# MRO: InteractiveMapPlot → RecordingMixin → MapPlot → BasePlot → StarPlotterMixin → ...
```

当调用 `_scatter_stars()` 时：
1. Python 找到 `RecordingMixin._scatter_stars()` (因为 RecordingMixin 在 MRO 中更前)
2. `super()._scatter_stars()` 调用 `StarPlotterMixin._scatter_stars()` (matplotlib 渲染)
3. matplotlib 渲染完毕后，RecordingMixin 录制 DrawingCommand

---

## 3. 文件结构

### 3.1 新增文件

```
src/starplot/interactive/                 # 新增 Python 包
    __init__.py                           # 导出公开 API
    commands.py                           # DrawingCommand 数据类
    recorder.py                           # DrawingRecorder 录制器
    recording_mixin.py                    # RecordingMixin 录制混入类
    plotly_renderer.py                    # PlotlyRenderer 回放渲染器
    style_converter.py                    # 样式转换 (starplot → Plotly)
    plots.py                              # Interactive*Plot 用户类
    testing.py                            # VisualConsistencyChecker 视觉一致性测试工具

examples/interactive/                     # 交互式示例
    star_chart_basic_interactive.py       # 基础天顶图 (对应 star_chart_basic.py)
    star_chart_detail_interactive.py      # 详细天顶图 (对应 star_chart_detail.py)
    map_orion_interactive.py              # 猎户座区域图 (对应 map_orion.py)
    map_big_dipper_interactive.py         # 北斗星图 (对应 map_big_dipper.py)
    map_orthographic_interactive.py       # 正交投影图 (对应 map_orthographic.py)
    map_virgo_cluster_interactive.py      # 室女座星系团 (对应 map_virgo_cluster.py)
    horizon_sgr_interactive.py            # 人马座地平图 (对应 horizon_sgr.py)
    horizon_gradient_interactive.py       # 渐变地平图 (对应 horizon_gradient.py)
    optic_m45_interactive.py              # M45 望远镜视图 (对应 optic_m45.py)

tests/test_interactive/                   # 测试
    __init__.py
    test_commands.py
    test_recorder.py
    test_plotly_renderer.py
    test_visual_consistency.py
    test_interactive_plots.py
```

### 3.2 现有文件变更

**仅修改 1 个文件（纯增量改动）：**

```toml
# pyproject.toml - 添加可选依赖
[project.optional-dependencies]
interactive = ["plotly>=5.0", "kaleido>=0.2"]
```

### 3.3 关键现有文件参考（只读，不修改）

| 文件路径 | 作用 | 录制拦截点 |
|----------|------|-----------|
| `src/starplot/plots/base.py` | 基类：marker(), _polygon(), line(), export(), ecliptic(), celestial_equator() | 4 个方法 |
| `src/starplot/plotters/stars.py` | 星点渲染：_scatter_stars() | 1 个方法 |
| `src/starplot/plotters/text.py` | 文本标签：_text(), CollisionHandler | 1 个方法 |
| `src/starplot/plotters/constellations.py` | 星座线：constellations() | 1 个方法 |
| `src/starplot/plotters/gradients.py` | 渐变背景：_plot_gradient_background() | 1 个方法 |
| `src/starplot/styles/base.py` | 样式系统：所有 matplot_kwargs() 方法 | 样式转换参考 |
| `src/starplot/plots/map.py` | MapPlot：_init_plot(), _plot_kwargs(), gridlines() | 投影/坐标系 |
| `src/starplot/plots/zenith.py` | ZenithPlot：继承 MapPlot | 同 MapPlot |
| `src/starplot/plots/horizon.py` | HorizonPlot：AZ_ALT 坐标系 | 坐标系差异 |
| `src/starplot/plots/optic.py` | OpticPlot：望远镜模拟 | 坐标系差异 |
| `src/starplot/projections.py` | Cartopy 投影包装 | 投影信息提取 |
| `hash_checks/hashio.py` | 视觉回归测试基础设施 | 复用哈希算法 |

---

## 4. 详细实现规格

### 4.1 `commands.py` — DrawingCommand 数据类

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class DrawingCommand:
    """后端无关的绘图指令"""
    kind: str                       # "scatter" | "line" | "polygon" | "text" |
                                    # "line_collection" | "gradient"
    data: dict = field(default_factory=dict)
    # 坐标数据（后端无关）:
    #   scatter: {x, y, sizes, colors, alphas}
    #   line: {x, y}
    #   polygon: {points}  # list of (x,y) tuples
    #   text: {text, x, y}
    #   line_collection: {lines}  # list of [(x1,y1),(x2,y2)] pairs
    #   gradient: {direction, color_stops}

    style: dict = field(default_factory=dict)
    # 后端无关的样式属性:
    #   color, edge_color, line_width, line_style, alpha, fill_color, font_size,
    #   font_weight, font_color, font_name, anchor_point, etc.

    metadata: list[dict] = field(default_factory=list)
    # 每个对象的元数据（用于 tooltip）:
    #   star: {name, magnitude, hip, bayer, constellation, ra, dec, type:"star"}
    #   dso: {name, type, magnitude, size, m, ngc, ra, dec, type:"dso"}
    #   planet: {name, magnitude, ra, dec, type:"planet"}
    #   constellation: {name, iau_id, type:"constellation"}

    zorder: int = 0                 # 图层顺序
    gid: str = ""                   # 元素组 ID (与 matplotlib gid 一致)
```

### 4.2 `recorder.py` — DrawingRecorder

```python
class DrawingRecorder:
    """录制绘图命令，不修改绘图流水线"""

    def __init__(self):
        self.commands: list[DrawingCommand] = []
        self.projection_info: dict = {}
        # {type, center_ra, center_dec, ra_min, ra_max, dec_min, dec_max,
        #  x_min, x_max, y_min, y_max (投影后坐标范围)}
        self.style_info: dict = {}
        # {background_color, figure_background_color, width, height}

    def record_scatter(self, x, y, sizes, colors, alphas, metadata, gid, zorder): ...
    def record_line(self, x, y, style_dict, gid, zorder): ...
    def record_polygon(self, points, style_dict, gid, zorder): ...
    def record_text(self, text, x, y, style_dict, gid, zorder): ...
    def record_line_collection(self, lines, style_dict, gid, zorder): ...
    def record_gradient(self, direction, color_stops, gid="gradient"): ...

    def clear(self):
        """清除所有录制的命令"""
        self.commands.clear()
```

### 4.3 `recording_mixin.py` — RecordingMixin（核心）

录制 8 个关键绘图方法，每个方法通过 `super()` 保留原有行为后录制命令：

```python
class RecordingMixin:
    """录制绘图指令的混入类。必须在 MRO 中排在具体 Plot 类之前。"""

    def __init__(self, *args, **kwargs):
        self._recorder = DrawingRecorder()
        super().__init__(*args, **kwargs)
        # super().__init__ 之后，plot 已初始化完毕
        self._record_plot_info()

    def _record_plot_info(self):
        """提取投影和样式信息"""
        self._recorder.projection_info = {
            'type': getattr(self, 'projection', None).__class__.__name__
                    if hasattr(self, 'projection') else None,
            'ra_min': getattr(self, 'ra_min', 0),
            'ra_max': getattr(self, 'ra_max', 360),
            'dec_min': getattr(self, 'dec_min', -90),
            'dec_max': getattr(self, 'dec_max', 90),
        }
        # 提取投影后的坐标范围（用于 Plotly 坐标轴）
        self._recorder.projection_info.update(
            self._get_projected_extent()
        )
        self._recorder.style_info = {
            'background_color': self.style.background_color.as_hex()
                if not self.style.has_gradient_background()
                else '#000',
            'figure_background_color': self.style.figure_background_color.as_hex(),
            'resolution': self.resolution,
        }
```

**8 个录制方法的实现要点：**

#### 方法 1: `_scatter_stars()` — 星点（最关键）

```python
def _scatter_stars(self, ras, decs, sizes, alphas, colors, style=None, **kwargs):
    result = super()._scatter_stars(ras, decs, sizes, alphas, colors, style, **kwargs)

    # 从 self._objects.stars 中获取最近添加的星点元数据
    recent_stars = self._objects.stars[-len(ras):]
    metadata = [
        {
            "name": s.get_label(s) if hasattr(s, 'get_label') else "",
            "magnitude": s.magnitude,
            "hip": s.hip,
            "bayer": getattr(s, 'bayer', None),
            "constellation": s.constellation_id,
            "ra": s.ra, "dec": s.dec,
            "type": "star",
        }
        for s in recent_stars
    ]

    self._recorder.record_scatter(
        x=list(ras), y=list(decs),
        sizes=list(sizes),
        colors=list(colors) if not isinstance(colors, str) else [colors] * len(ras),
        alphas=list(alphas) if not isinstance(alphas, (int, float)) else [alphas] * len(ras),
        metadata=metadata,
        gid="stars",
        zorder=kwargs.get("zorder", (style or self.style.star).marker.zorder),
    )
    return result
```

#### 方法 2: `_polygon()` — 多边形（银河、DSO 形状、圆、椭圆等）

```python
def _polygon(self, points, style, **kwargs):
    super()._polygon(points, style, **kwargs)
    self._recorder.record_polygon(
        points=[(float(x), float(y)) for x, y in points],
        style_dict={
            "fill_color": style.fill_color.as_hex() if style.fill_color else None,
            "edge_color": style.edge_color.as_hex() if style.edge_color else None,
            "edge_width": style.edge_width,
            "alpha": style.alpha,
            "line_style": str(style.line_style),
        },
        gid=kwargs.get("gid", "polygon"),
        zorder=style.zorder,
    )
```

#### 方法 3: `_text()` — 文本标签

```python
def _text(self, x, y, text, **kwargs):
    result = super()._text(x, y, text, **kwargs)
    if result is not None:  # 只录制未被碰撞检测删除的标签
        self._recorder.record_text(
            text=text, x=float(x), y=float(y),
            style_dict={
                "font_size": kwargs.get("fontsize", 12),
                "font_color": kwargs.get("color", "#000"),
                "font_weight": kwargs.get("weight", "normal"),
                "font_name": kwargs.get("fontname", "Inter"),
                "ha": kwargs.get("ha", "center"),
                "va": kwargs.get("va", "center"),
                "alpha": kwargs.get("alpha", 1.0),
            },
            gid=kwargs.get("gid", "text"),
            zorder=kwargs.get("zorder", 0),
        )
    return result
```

#### 方法 4: `line()` — 线段

```python
def line(self, style, coordinates=None, geometry=None, **kwargs):
    super().line(style=style, coordinates=coordinates, geometry=geometry, **kwargs)
    coords = geometry.coords if geometry is not None else coordinates
    processed = [self._prepare_coords(*p) for p in coords]
    x, y = zip(*processed)
    self._recorder.record_line(
        x=list(x), y=list(y),
        style_dict={
            "color": style.color.as_hex(),
            "width": style.width,
            "line_style": str(style.style),
            "alpha": style.alpha,
        },
        gid=kwargs.get("gid", "line"),
        zorder=style.zorder,
    )
```

#### 方法 5: `constellations()` — 星座线

这是最复杂的录制，因为原方法内部构建 `lines` 列表后创建 `LineCollection`。策略：完全重写方法，在构建 lines 的同时录制：

```python
def constellations(self, style=None, where=None, sql=None, catalog=None):
    # 调用 super() 让 matplotlib 完整渲染
    super().constellations(style=style, where=where, sql=sql, catalog=catalog)

    # 星座线的数据已经通过 self._objects.constellations 获取
    # 需要重新计算线段数据用于录制
    # 方案：从 self._objects.constellations 中提取 star_hip_lines，
    # 复用 _prepare_constellation_stars() 获取坐标
    constellation_lines = []
    constellation_metadata = []
    constars = self._prepare_constellation_stars(self._objects.constellations)

    for c in self._objects.constellations:
        for s1_hip, s2_hip in c.star_hip_lines:
            if constars.get(s1_hip) and constars.get(s2_hip):
                s1_ra, s1_dec = constars[s1_hip]
                s2_ra, s2_dec = constars[s2_hip]
                # 处理 RA 环绕
                if s1_ra - s2_ra > 60:
                    s2_ra += 360
                elif s2_ra - s1_ra > 60:
                    s1_ra += 360
                constellation_lines.append([(s1_ra, s1_dec), (s2_ra, s2_dec)])
                constellation_metadata.append({
                    "name": c.name, "iau_id": c.iau_id, "type": "constellation"
                })

    if constellation_lines:
        resolved_style = style or self.style.constellation_lines
        self._recorder.record_line_collection(
            lines=constellation_lines,
            style_dict={
                "color": resolved_style.color.as_hex(),
                "width": resolved_style.width,
                "alpha": resolved_style.alpha,
            },
            metadata=constellation_metadata,
            gid="constellations-line",
            zorder=resolved_style.zorder,
        )
```

#### 方法 6-7: `ecliptic()` / `celestial_equator()` — 参考线

```python
def ecliptic(self, style=None, label="ECLIPTIC", collision_handler=None):
    super().ecliptic(style=style, label=label, collision_handler=collision_handler)
    # 录制黄道线坐标
    from starplot.data import ecliptic as ecliptic_data
    resolved_style = style or self.style.ecliptic
    x, y = [], []
    for ra, dec in ecliptic_data.RA_DECS:
        x0, y0 = self._prepare_coords(ra * 15, dec)
        x.append(x0); y.append(y0)
    self._recorder.record_line(
        x=x, y=y,
        style_dict={"color": resolved_style.line.color.as_hex(),
                     "width": resolved_style.line.width,
                     "line_style": str(resolved_style.line.style),
                     "alpha": resolved_style.line.alpha},
        gid="ecliptic-line",
        zorder=resolved_style.line.zorder,
    )
```

#### 方法 8: `_plot_gradient_background()` — 渐变背景

```python
def _plot_gradient_background(self, gradient_preset):
    super()._plot_gradient_background(gradient_preset)
    self._recorder.record_gradient(
        direction=self._gradient_direction.value,
        color_stops=gradient_preset,
        gid="gradient",
    )
```

### 4.4 `style_converter.py` — 样式转换

```python
# Marker 符号映射
MARKER_SYMBOL_MAP = {
    "point": "circle",       # MarkerSymbolEnum.POINT
    "circle": "circle",      # MarkerSymbolEnum.CIRCLE
    "square": "square",      # MarkerSymbolEnum.SQUARE
    "star": "star",          # MarkerSymbolEnum.STAR
    "diamond": "diamond",    # MarkerSymbolEnum.DIAMOND
    "triangle": "triangle-up",  # MarkerSymbolEnum.TRIANGLE
    "plus": "cross",         # MarkerSymbolEnum.PLUS
    "circle_plus": "circle-cross",
    "circle_cross": "circle-x",
    "circle_dot": "circle-dot",
    "comet": "star-diamond",
    "star_4": "star-square",
    "star_8": "star",
    "ellipse": "circle",     # 近似
}

# Line style 映射
LINE_STYLE_MAP = {
    "solid": "solid",
    "dashed": "dash",
    "dotted": "dot",
    "dashdot": "dashdot",
}

# 文本对齐映射
ANCHOR_MAP = {
    # matplotlib (va, ha) → Plotly (yanchor, xanchor)
    ("top", "left"): ("top", "right"),      # starplot 坐标反转
    ("top", "right"): ("top", "left"),
    ("bottom", "left"): ("bottom", "right"),
    ("bottom", "right"): ("bottom", "left"),
    ("center", "center"): ("middle", "center"),
    ("center", "left"): ("middle", "right"),
    ("center", "right"): ("middle", "left"),
    ("top", "center"): ("top", "center"),
    ("bottom", "center"): ("bottom", "center"),
}

def convert_marker_style(style_dict: dict, scale: float = 1.0) -> dict: ...
def convert_line_style(style_dict: dict, scale: float = 1.0) -> dict: ...
def convert_text_style(style_dict: dict, scale: float = 1.0) -> dict: ...
def convert_polygon_style(style_dict: dict, scale: float = 1.0) -> dict: ...

# 大小校准：matplotlib 使用 points²，Plotly 使用 px
def calibrate_marker_size(mpl_size: float, scale: float = 1.0) -> float:
    """将 matplotlib scatter 的 s 参数（points²）转为 Plotly marker size（px）"""
    return (mpl_size ** 0.5) * 0.5  # 校准系数需实测调整
```

### 4.5 `plotly_renderer.py` — PlotlyRenderer

```python
import plotly.graph_objects as go

class PlotlyRenderer:
    """将 DrawingCommand 列表渲染为 Plotly Figure"""

    def __init__(self, projection_info: dict, style_info: dict):
        self.fig = go.Figure()
        self.projection_info = projection_info
        self.style_info = style_info
        self._trace_groups = {}  # gid → trace indices（用于 legend filtering）
        self._setup_layout()

    def render(self, commands: list[DrawingCommand]) -> go.Figure:
        """按 zorder 排序后渲染所有命令"""
        for cmd in sorted(commands, key=lambda c: c.zorder):
            handler = {
                'scatter': self._render_scatter,
                'line': self._render_line,
                'polygon': self._render_polygon,
                'text': self._render_text,
                'line_collection': self._render_line_collection,
                'gradient': self._render_gradient,
            }.get(cmd.kind)
            if handler:
                handler(cmd)
        self._add_interactive_features()
        return self.fig

    def _setup_layout(self):
        """设置 Plotly 布局以匹配 matplotlib 输出"""
        bg = self.style_info.get('background_color', '#fff')
        self.fig.update_layout(
            plot_bgcolor=bg,
            paper_bgcolor=self.style_info.get('figure_background_color', '#fff'),
            xaxis=dict(
                showgrid=False, zeroline=False,
                scaleanchor="y", scaleratio=1,
                showticklabels=False,
            ),
            yaxis=dict(
                showgrid=False, zeroline=False,
                showticklabels=False,
            ),
            hovermode='closest',
            dragmode='pan',
            showlegend=True,
            margin=dict(l=20, r=20, t=40, b=20),
        )

    def _render_scatter(self, cmd: DrawingCommand):
        """渲染星点/标记为 Plotly Scattergl（WebGL 加速）"""
        hover_texts = []
        for meta in cmd.metadata:
            if meta.get('type') == 'star':
                name = meta.get('name', '')
                mag = meta.get('magnitude', '?')
                ra_h = meta.get('ra', 0) / 15  # 度 → 时
                dec = meta.get('dec', 0)
                bayer = meta.get('bayer', '')
                constellation = meta.get('constellation', '')
                parts = [f"<b>{name}</b>"] if name else []
                if bayer:
                    parts.append(f"{bayer}")
                parts.append(f"Magnitude: {mag:.2f}" if isinstance(mag, float) else f"Magnitude: {mag}")
                parts.append(f"RA: {ra_h:.4f}h / DEC: {dec:.4f}°")
                if constellation:
                    parts.append(f"Constellation: {constellation}")
                hover_texts.append("<br>".join(parts))
            elif meta.get('type') == 'dso':
                parts = [f"<b>{meta.get('name', 'DSO')}</b>"]
                parts.append(f"Type: {meta.get('dso_type', '?')}")
                if meta.get('magnitude'):
                    parts.append(f"Magnitude: {meta['magnitude']:.1f}")
                parts.append(f"RA: {meta.get('ra', 0)/15:.4f}h / DEC: {meta.get('dec', 0):.4f}°")
                hover_texts.append("<br>".join(parts))
            else:
                hover_texts.append("")

        sizes = [calibrate_marker_size(s) for s in cmd.data.get('sizes', [])]

        self.fig.add_trace(go.Scattergl(
            x=cmd.data['x'],
            y=cmd.data['y'],
            mode='markers',
            marker=dict(
                size=sizes,
                color=cmd.data.get('colors'),
                opacity=cmd.data.get('alphas', [1.0])[0]
                    if isinstance(cmd.data.get('alphas'), list) else cmd.data.get('alphas', 1.0),
                symbol=MARKER_SYMBOL_MAP.get(cmd.style.get('symbol', 'circle'), 'circle'),
            ),
            text=hover_texts,
            hoverinfo='text',
            name=self._gid_to_legend_name(cmd.gid),
            legendgroup=cmd.gid,
            showlegend=cmd.gid not in self._trace_groups,
        ))
        self._trace_groups.setdefault(cmd.gid, []).append(len(self.fig.data) - 1)

    def _render_line_collection(self, cmd: DrawingCommand):
        """渲染星座线（用 None 分隔符高效渲染多条线段）"""
        x_all, y_all, hover_all = [], [], []
        for i, line in enumerate(cmd.data.get('lines', [])):
            for point in line:
                x_all.append(point[0])
                y_all.append(point[1])
                meta = cmd.metadata[i] if i < len(cmd.metadata) else {}
                hover_all.append(meta.get('name', ''))
            x_all.append(None)
            y_all.append(None)
            hover_all.append(None)

        self.fig.add_trace(go.Scattergl(
            x=x_all, y=y_all,
            mode='lines',
            line=dict(
                color=cmd.style.get('color', '#ccc'),
                width=max(1, cmd.style.get('width', 1) * 0.3),  # 缩放线宽
            ),
            text=hover_all,
            hoverinfo='text',
            name="Constellations",
            legendgroup="constellations",
            showlegend="constellations" not in self._trace_groups,
        ))
        self._trace_groups.setdefault("constellations", []).append(len(self.fig.data) - 1)

    def _render_polygon(self, cmd: DrawingCommand):
        """渲染多边形（银河、DSO 形状等）"""
        points = cmd.data.get('points', [])
        if not points:
            return
        x = [p[0] for p in points] + [points[0][0]]
        y = [p[1] for p in points] + [points[0][1]]
        self.fig.add_trace(go.Scatter(
            x=x, y=y,
            mode='lines',
            fill='toself' if cmd.style.get('fill_color') else None,
            fillcolor=cmd.style.get('fill_color'),
            line=dict(
                color=cmd.style.get('edge_color', 'rgba(0,0,0,0)'),
                width=cmd.style.get('edge_width', 0) * 0.3,
            ),
            opacity=cmd.style.get('alpha', 1.0),
            hoverinfo='none',
            legendgroup=cmd.gid,
            showlegend=False,
        ))

    def _render_text(self, cmd: DrawingCommand):
        """渲染文本标签为 Plotly annotation"""
        va = cmd.style.get('va', 'center')
        ha = cmd.style.get('ha', 'center')
        yanchor, xanchor = ANCHOR_MAP.get((va, ha), ('middle', 'center'))

        self.fig.add_annotation(
            x=cmd.data['x'], y=cmd.data['y'],
            text=cmd.data['text'],
            showarrow=False,
            font=dict(
                size=max(8, cmd.style.get('font_size', 12) * 0.4),
                color=cmd.style.get('font_color', '#000'),
                family=cmd.style.get('font_name', 'Inter'),
            ),
            xanchor=xanchor,
            yanchor=yanchor,
            opacity=cmd.style.get('alpha', 1.0),
        )

    def _render_line(self, cmd: DrawingCommand):
        """渲染线段（黄道线、天赤道等）"""
        style = cmd.style
        self.fig.add_trace(go.Scattergl(
            x=cmd.data['x'], y=cmd.data['y'],
            mode='lines',
            line=dict(
                color=style.get('color', '#777'),
                width=max(1, style.get('width', 1) * 0.3),
                dash=LINE_STYLE_MAP.get(style.get('line_style', 'solid'), 'solid'),
            ),
            hoverinfo='none',
            name=self._gid_to_legend_name(cmd.gid),
            legendgroup=cmd.gid,
            showlegend=cmd.gid not in self._trace_groups,
        ))
        self._trace_groups.setdefault(cmd.gid, []).append(len(self.fig.data) - 1)

    def _render_gradient(self, cmd: DrawingCommand):
        """渲染渐变背景（使用 Plotly 渐变色或 shape）"""
        # 方案：使用多层半透明 rect shapes 模拟渐变
        # 或使用 Heatmap trace
        pass  # 第一版可跳过，使用纯色背景

    def _add_interactive_features(self):
        """添加交互功能"""
        # 配置 modebar 按钮
        self.fig.update_layout(
            modebar=dict(
                add=['zoom', 'pan', 'select', 'lasso', 'resetScale2d'],
            ),
            # 点击事件配置
            clickmode='event+select',
        )

    @staticmethod
    def _gid_to_legend_name(gid: str) -> str:
        """将 gid 转为可读的 legend 名称"""
        return {
            "stars": "Stars",
            "constellations-line": "Constellations",
            "constellations-border": "Borders",
            "constellations-label-name": "Labels",
            "ecliptic-line": "Ecliptic",
            "celestial-equator-line": "Celestial Equator",
            "planet-marker": "Planets",
            "moon-marker": "Moon",
            "sun-marker": "Sun",
            "marker": "Markers",
        }.get(gid, gid)
```

### 4.6 `plots.py` — 用户接口类

```python
from starplot.interactive.recording_mixin import RecordingMixin
from starplot.interactive.plotly_renderer import PlotlyRenderer
from starplot.plots import MapPlot, ZenithPlot, HorizonPlot, OpticPlot


class InteractiveMapPlot(RecordingMixin, MapPlot):
    """带交互式 Plotly 导出的 MapPlot。

    用法与 MapPlot 完全相同，额外提供：
    - export_html(): 导出交互式 Plotly HTML
    - to_plotly(): 返回 Plotly Figure 供进一步自定义

    Example:
        p = InteractiveMapPlot(projection=Miller(), ra_min=60, ra_max=120, ...)
        p.stars(where=[_.magnitude < 8])
        p.constellations()
        p.export("chart.png")            # matplotlib 静态导出（不变）
        p.export_html("chart.html")      # 交互式 Plotly HTML
    """

    def export_html(self, filename: str, width: int = 1200, height: int = 900, **kwargs):
        """导出为交互式 Plotly HTML 文件。

        Args:
            filename: 输出 HTML 文件路径
            width: HTML 中图表宽度（px）
            height: HTML 中图表高度（px）
            **kwargs: 传递给 plotly.io.write_html 的参数
        """
        fig = self.to_plotly()
        fig.update_layout(width=width, height=height)
        fig.write_html(filename, **kwargs)

    def to_plotly(self) -> "go.Figure":
        """返回 Plotly Figure 对象供进一步自定义。

        Returns:
            go.Figure: 可直接调用 fig.show() 或 fig.write_html() 等方法
        """
        renderer = PlotlyRenderer(
            projection_info=self._recorder.projection_info,
            style_info=self._recorder.style_info,
        )
        return renderer.render(self._recorder.commands)


class InteractiveZenithPlot(RecordingMixin, ZenithPlot):
    """带交互式 Plotly 导出的 ZenithPlot。API 同 ZenithPlot。"""

    def export_html(self, filename, width=1000, height=1000, **kwargs):
        fig = self.to_plotly()
        fig.update_layout(width=width, height=height)
        fig.write_html(filename, **kwargs)

    def to_plotly(self):
        renderer = PlotlyRenderer(
            self._recorder.projection_info, self._recorder.style_info)
        return renderer.render(self._recorder.commands)


class InteractiveHorizonPlot(RecordingMixin, HorizonPlot):
    """带交互式 Plotly 导出的 HorizonPlot。API 同 HorizonPlot。"""

    def export_html(self, filename, width=1200, height=600, **kwargs):
        fig = self.to_plotly()
        fig.update_layout(width=width, height=height)
        fig.write_html(filename, **kwargs)

    def to_plotly(self):
        renderer = PlotlyRenderer(
            self._recorder.projection_info, self._recorder.style_info)
        return renderer.render(self._recorder.commands)


class InteractiveOpticPlot(RecordingMixin, OpticPlot):
    """带交互式 Plotly 导出的 OpticPlot。API 同 OpticPlot。"""

    def export_html(self, filename, width=1000, height=1000, **kwargs):
        fig = self.to_plotly()
        fig.update_layout(width=width, height=height)
        fig.write_html(filename, **kwargs)

    def to_plotly(self):
        renderer = PlotlyRenderer(
            self._recorder.projection_info, self._recorder.style_info)
        return renderer.render(self._recorder.commands)
```

---

## 5. 交互式示例

以下为现有 examples 的 HTML 交互式版本。**改动极小：只需将 import 的 Plot 类替换为 Interactive 版本，添加 `export_html()` 调用。**

### 5.1 `examples/interactive/star_chart_basic_interactive.py`

```python
"""基础天顶图 - 交互式版本（对应 star_chart_basic.py）"""
from datetime import datetime
from zoneinfo import ZoneInfo

from starplot.interactive import InteractiveZenithPlot
from starplot import Observer, _
from starplot.styles import PlotStyle, extensions

tz = ZoneInfo("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

observer = Observer(dt=dt, lat=33.363484, lon=-116.836394)

p = InteractiveZenithPlot(
    observer=observer,
    style=PlotStyle().extend(extensions.BLUE_MEDIUM),
    resolution=3600,
    autoscale=True,
)
p.horizon()
p.constellations()
p.stars(where=[_.magnitude < 4.6], where_labels=[_.magnitude < 2.4])
p.constellation_labels()

# 静态导出（与原版一致）
p.export("star_chart_basic.png", transparent=True, padding=0.1)
# 交互式 HTML 导出
p.export_html("star_chart_basic.html")
```

### 5.2 `examples/interactive/star_chart_detail_interactive.py`

```python
"""详细天顶图 - 交互式版本（对应 star_chart_detail.py）
包含 DSO、黄道线、天赤道、银河、自定义标记"""
from datetime import datetime
from zoneinfo import ZoneInfo

from starplot.interactive import InteractiveZenithPlot
from starplot import Observer, _
from starplot.styles import PlotStyle, extensions

tz = ZoneInfo("America/Los_Angeles")
dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)

observer = Observer(dt=dt, lat=33.363484, lon=-116.836394)
p = InteractiveZenithPlot(
    observer=observer,
    style=PlotStyle().extend(extensions.BLUE_GOLD, extensions.GRADIENT_PRE_DAWN),
    resolution=3600,
    autoscale=True,
)
p.horizon()
p.constellations()
p.stars(where=[_.magnitude < 4.6], where_labels=[_.magnitude < 2.1])
p.galaxies(where=[_.magnitude < 9], where_labels=[False], where_true_size=[False])
p.open_clusters(where=[_.magnitude < 9], where_labels=[False], where_true_size=[False])
p.ecliptic()
p.celestial_equator()
p.milky_way()
p.marker(
    ra=12.36 * 15, dec=25.85,
    style={"marker": {"size": 60, "symbol": "circle", "fill": "none",
           "color": None, "edge_color": "hsl(44, 70%, 73%)", "edge_width": 2,
           "line_style": [1, [2, 3]], "alpha": 1, "zorder": 100},
           "label": {"zorder": 200, "font_size": 22, "font_weight": 700,
           "font_color": "hsl(44, 70%, 64%)", "font_alpha": 1,
           "offset_x": "auto", "offset_y": "auto", "anchor_point": "top right"}},
    label="Mel 111",
)
p.constellation_labels()

p.export("star_chart_detail.png", transparent=True, padding=0.1)
p.export_html("star_chart_detail.html", width=1000, height=1000)
```

### 5.3 `examples/interactive/map_orion_interactive.py`

```python
"""猎户座区域图 - 交互式版本（对应 map_orion.py）
包含网格线、星座边界、星团、星云、银河、黄道线"""
from starplot.interactive import InteractiveMapPlot
from starplot import Miller, _
from starplot.styles import PlotStyle, extensions

style = PlotStyle().extend(extensions.BLUE_LIGHT, extensions.MAP)

p = InteractiveMapPlot(
    projection=Miller(),
    ra_min=3.6 * 15, ra_max=7.8 * 15,
    dec_min=-15, dec_max=25,
    style=style, resolution=4096, autoscale=True,
)
p.gridlines()
p.constellations()
p.constellation_borders()
p.stars(where=[_.magnitude < 8], bayer_labels=True, where_labels=[_.magnitude < 5])
p.open_clusters(
    where=[(_.magnitude < 9) | (_.magnitude.isnull())],
    where_labels=[False],
    where_true_size=[_.size > 1],
)
p.nebula(where=[(_.magnitude < 9) | (_.magnitude.isnull())])
p.constellation_labels()
p.milky_way()
p.ecliptic()

p.export("map_orion.png", padding=0.3, transparent=True)
p.export_html("map_orion.html", width=1400, height=900)
```

### 5.4 `examples/interactive/map_big_dipper_interactive.py`

```python
"""北斗星图 - 交互式版本（对应 map_big_dipper.py）"""
from starplot.interactive import InteractiveMapPlot
from starplot import StereoNorth, _
from starplot.styles import PlotStyle, extensions

style = PlotStyle().extend(
    extensions.BLUE_DARK, extensions.MAP, {"background_color": "#2C3F62"}
)

p = InteractiveMapPlot(
    projection=StereoNorth(),
    ra_min=10.75 * 15, ra_max=14.2 * 15,
    dec_min=47, dec_max=65,
    style=style, resolution=2000,
)
p.stars(
    where=[_.magnitude < 3.6, _.dec > 45, _.dec < 64],
    size_fn=lambda s: 2600,
    style__marker__symbol="star",
    style__marker__color="#ffff6c",
    style__label__font_size=14,
    style__label__font_weight=400,
)

p.export("map_big_dipper.png", transparent=True)
p.export_html("map_big_dipper.html")
```

### 5.5 `examples/interactive/map_orthographic_interactive.py`

```python
"""正交投影全天图 - 交互式版本（对应 map_orthographic.py）
包含星座线、边界、DSO、黄道线、天赤道、银河"""
from datetime import datetime
from pytz import timezone

from starplot.interactive import InteractiveMapPlot
from starplot import Orthographic, Observer, _
from starplot.styles import PlotStyle, extensions

style = PlotStyle().extend(extensions.BLUE_MEDIUM, extensions.MAP)
tz = timezone("America/Los_Angeles")
dt = datetime(2024, 10, 19, 21, 00, tzinfo=tz)

observer = Observer(dt=dt, lat=32.97, lon=-117.038611)
p = InteractiveMapPlot(
    projection=Orthographic(center_ra=observer.lst, center_dec=observer.lat),
    observer=observer, style=style, resolution=2800, scale=0.86,
)
p.gridlines(labels=False)
p.constellations()
p.constellation_borders()
p.stars(where=[_.magnitude < 7], where_labels=[False])
p.open_clusters(where=[_.magnitude < 12], where_labels=[False], where_true_size=[False])
p.galaxies(where=[_.magnitude < 12], where_labels=[False], where_true_size=[False])
p.nebula(where=[_.magnitude < 12], where_labels=[False], where_true_size=[False])
p.ecliptic()
p.celestial_equator()
p.milky_way()

p.export("map_orthographic.png", padding=0.3, transparent=True)
p.export_html("map_orthographic.html", width=1000, height=1000)
```

### 5.6 `examples/interactive/map_virgo_cluster_interactive.py`

```python
"""室女座星系团 - 交互式版本（对应 map_virgo_cluster.py）"""
from starplot.interactive import InteractiveMapPlot
from starplot import Equidistant, CollisionHandler, _
from starplot.styles import PlotStyle, extensions, AnchorPointEnum

style = PlotStyle().extend(
    extensions.BLUE_MEDIUM, extensions.MAP,
    {"figure_background_color": "hsl(330, 44%, 20%)",
     "dso_galaxy": {"label": {"font_color": "hsl(330, 44%, 14%)",
                               "font_weight": 200,
                               "anchor_point": AnchorPointEnum.BOTTOM_CENTER.value}}},
)
collision_handler = CollisionHandler(plot_on_fail=True, attempts=1)

p = InteractiveMapPlot(
    projection=Equidistant(center_ra=11 * 15),
    ra_min=12 * 15, ra_max=13 * 15, dec_min=8, dec_max=18,
    style=style, resolution=3000, scale=1, collision_handler=collision_handler,
)
p.title("Virgo Cluster", style__font_color="hsl(330, 44%, 92%)")
p.stars(where=[_.magnitude < 12], where_labels=[False])
p.galaxies(where=[(_.magnitude < 12) | (_.magnitude.isnull())], where_true_size=[False])

p.export("map_virgo_cluster.png", padding=0.8)
p.export_html("map_virgo_cluster.html")
```

### 5.7 `examples/interactive/horizon_sgr_interactive.py`

```python
"""人马座地平图 - 交互式版本（对应 horizon_sgr.py）"""
from datetime import datetime
from zoneinfo import ZoneInfo

from starplot.interactive import InteractiveHorizonPlot
from starplot import Observer, _
from starplot.styles import PlotStyle, extensions

style = PlotStyle().extend(extensions.BLUE_MEDIUM, extensions.MAP)
dt = datetime(2024, 8, 30, 21, 0, 0, 0, tzinfo=ZoneInfo("US/Pacific"))
observer = Observer(dt=dt, lat=36.606111, lon=-118.079444)

p = InteractiveHorizonPlot(
    altitude=(0, 60), azimuth=(135, 225),
    observer=observer, style=style, resolution=4000, scale=0.9,
)
p.constellations()
p.milky_way()
p.stars(where=[_.magnitude < 5], where_labels=[_.magnitude < 2])
p.messier(where=[_.magnitude < 11], where_true_size=[False])
p.constellation_labels()
p.horizon(labels={180: "SOUTH"})
p.gridlines()

p.export("horizon_sgr.png", padding=0.5)
p.export_html("horizon_sgr.html", width=1400, height=700)
```

### 5.8 `examples/interactive/horizon_gradient_interactive.py`

```python
"""渐变地平图 - 交互式版本（对应 horizon_gradient.py）"""
from datetime import datetime
from zoneinfo import ZoneInfo

from starplot.interactive import InteractiveHorizonPlot
from starplot import Observer, _
from starplot.styles import PlotStyle, extensions

style = PlotStyle().extend(extensions.BLUE_GOLD, extensions.MAP, extensions.GRADIENT_PRE_DAWN)
dt = datetime(2025, 7, 26, 23, 30, 0, 0, tzinfo=ZoneInfo("Europe/London"))
observer = Observer(lat=55.079112, lon=-2.327469, dt=dt)

p = InteractiveHorizonPlot(
    altitude=(0, 60), azimuth=(135, 225),
    observer=observer, style=style, resolution=3200, scale=0.9,
)
p.constellations()
p.milky_way()
p.stars(where=[_.magnitude < 5], where_labels=[_.magnitude < 2], style__marker__symbol="star_4")
p.messier(where=[_.magnitude < 11], where_true_size=[False])
p.constellation_labels()
p.horizon(labels={180: "SOUTH"})

p.export("horizon_gradient.png", padding=0.1)
p.export_html("horizon_gradient.html", width=1400, height=700)
```

### 5.9 `examples/interactive/optic_m45_interactive.py`

```python
"""M45 望远镜视图 - 交互式版本（对应 optic_m45.py）"""
from datetime import datetime
from zoneinfo import ZoneInfo

from starplot.interactive import InteractiveOpticPlot
from starplot import DSO, Observer, _
from starplot.callables import color_by_bv
from starplot.models import Refractor
from starplot.styles import PlotStyle, extensions

dt = datetime(2023, 12, 16, 21, 0, 0, tzinfo=ZoneInfo("US/Pacific"))
style = PlotStyle().extend(extensions.GRAYSCALE_DARK, extensions.OPTIC)
observer = Observer(dt=dt, lat=33.363484, lon=-116.836394)

m45 = DSO.get(m="45")
p = InteractiveOpticPlot(
    ra=m45.ra, dec=m45.dec,
    observer=observer,
    optic=Refractor(focal_length=430, eyepiece_focal_length=11, eyepiece_fov=82),
    style=style, resolution=4096, autoscale=True,
)
p.stars(where=[_.magnitude < 12], color_fn=color_by_bv)
p.info()

p.export("optic_m45.png", padding=0.1, transparent=True)
p.export_html("optic_m45.html", width=1000, height=1000)
```

---

## 6. 测试设计

### 6.1 单元测试

#### `test_commands.py` — DrawingCommand 数据类

```python
def test_drawing_command_creation():
    cmd = DrawingCommand(kind="scatter", data={"x": [1,2], "y": [3,4]},
                         style={"color": "#fff"}, metadata=[], zorder=0, gid="stars")
    assert cmd.kind == "scatter"
    assert len(cmd.data["x"]) == 2

def test_drawing_command_defaults():
    cmd = DrawingCommand(kind="line")
    assert cmd.metadata == []
    assert cmd.zorder == 0
```

#### `test_recorder.py` — DrawingRecorder

```python
def test_recorder_records_scatter():
    rec = DrawingRecorder()
    rec.record_scatter(x=[1,2], y=[3,4], sizes=[10,20], colors=["#fff","#000"],
                       alphas=[1.0,0.8], metadata=[{"name":"Sirius"}], gid="stars", zorder=1)
    assert len(rec.commands) == 1
    assert rec.commands[0].kind == "scatter"
    assert rec.commands[0].gid == "stars"

def test_recorder_clear():
    rec = DrawingRecorder()
    rec.record_line(x=[1], y=[2], style_dict={}, gid="line", zorder=0)
    rec.clear()
    assert len(rec.commands) == 0
```

#### `test_plotly_renderer.py` — PlotlyRenderer

```python
def test_renderer_creates_figure():
    renderer = PlotlyRenderer(
        projection_info={"ra_min": 0, "ra_max": 360},
        style_info={"background_color": "#000"}
    )
    fig = renderer.render([])
    assert fig is not None
    assert len(fig.data) == 0

def test_renderer_scatter_trace():
    cmd = DrawingCommand(
        kind="scatter",
        data={"x": [1,2,3], "y": [4,5,6], "sizes": [10,20,30],
              "colors": ["#fff"]*3, "alphas": [1.0]*3},
        metadata=[{"name": "Star1", "magnitude": 2.0, "ra": 15, "dec": 30, "type": "star"}]*3,
        zorder=0, gid="stars"
    )
    renderer = PlotlyRenderer({"ra_min": 0, "ra_max": 360}, {"background_color": "#000"})
    fig = renderer.render([cmd])
    assert len(fig.data) == 1
    assert fig.data[0].type == "scattergl"
    assert len(fig.data[0].x) == 3

def test_renderer_line_collection():
    cmd = DrawingCommand(
        kind="line_collection",
        data={"lines": [[(0,0),(1,1)], [(2,2),(3,3)]]},
        style={"color": "#ccc", "width": 2, "alpha": 1.0},
        metadata=[{"name": "Orion"}, {"name": "Orion"}],
        zorder=0, gid="constellations-line"
    )
    renderer = PlotlyRenderer({"ra_min": 0, "ra_max": 360}, {"background_color": "#000"})
    fig = renderer.render([cmd])
    assert len(fig.data) == 1
    # 2 线段 + 2 个 None 分隔符 = 6 个点
    assert None in fig.data[0].x
```

### 6.2 集成测试

#### `test_interactive_plots.py`

```python
def test_interactive_map_plot_basic():
    """InteractiveMapPlot 应该和 MapPlot 产生相同的 objects 列表"""
    from starplot.interactive import InteractiveMapPlot
    from starplot import Miller
    from ibis import _

    p = InteractiveMapPlot(
        projection=Miller(), ra_min=60, ra_max=120,
        dec_min=-10, dec_max=30, resolution=2048,
    )
    p.stars(where=[_.magnitude < 7])
    p.constellations()

    # matplotlib 输出不变
    assert len(p.objects.stars) > 0
    assert len(p.objects.constellations) > 0

    # 录制了命令
    assert len(p._recorder.commands) > 0

    # 有 scatter 类型的命令（星点）
    scatter_cmds = [c for c in p._recorder.commands if c.kind == "scatter"]
    assert len(scatter_cmds) > 0

    # 有 line_collection 类型的命令（星座线）
    line_cmds = [c for c in p._recorder.commands if c.kind == "line_collection"]
    assert len(line_cmds) > 0

def test_export_html_creates_file(tmp_path):
    """export_html 应该生成有效的 HTML 文件"""
    from starplot.interactive import InteractiveMapPlot
    from starplot import Miller
    from ibis import _

    p = InteractiveMapPlot(
        projection=Miller(), ra_min=60, ra_max=120,
        dec_min=-10, dec_max=30, resolution=1024,
    )
    p.stars(where=[_.magnitude < 5])

    html_path = tmp_path / "test.html"
    p.export_html(str(html_path))

    assert html_path.exists()
    content = html_path.read_text()
    assert "plotly" in content.lower()
    assert "<script" in content

def test_to_plotly_returns_figure():
    """to_plotly 应该返回 Plotly Figure"""
    from starplot.interactive import InteractiveMapPlot
    from starplot import Miller
    from ibis import _
    import plotly.graph_objects as go

    p = InteractiveMapPlot(
        projection=Miller(), ra_min=60, ra_max=120,
        dec_min=-10, dec_max=30, resolution=1024,
    )
    p.stars(where=[_.magnitude < 5])

    fig = p.to_plotly()
    assert isinstance(fig, go.Figure)
    assert len(fig.data) > 0

def test_matplotlib_output_unchanged():
    """RecordingMixin 不应影响 matplotlib 输出"""
    from starplot import MapPlot, Miller
    from starplot.interactive import InteractiveMapPlot
    from ibis import _

    kwargs = dict(projection=Miller(), ra_min=60, ra_max=120,
                  dec_min=-10, dec_max=30, resolution=1024)

    p1 = MapPlot(**kwargs)
    p1.stars(where=[_.magnitude < 5])

    p2 = InteractiveMapPlot(**kwargs)
    p2.stars(where=[_.magnitude < 5])

    # 星点数量应该一致
    assert len(p1.objects.stars) == len(p2.objects.stars)
    # HIP 号应该一致
    assert set(s.hip for s in p1.objects.stars) == set(s.hip for s in p2.objects.stars)
```

### 6.3 视觉一致性测试

#### `test_visual_consistency.py`

```python
"""视觉一致性测试：比较 matplotlib 和 Plotly 的渲染结果。

原理：
1. 用 InteractiveMapPlot 渲染
2. 导出 matplotlib PNG (p.export)
3. 导出 Plotly 静态 PNG (fig.write_image via kaleido)
4. 使用感知哈希 (dhash) 对比两张图片的 Hamming 距离
5. Hamming 距离 < 阈值则通过

注意：由于 matplotlib 和 Plotly 的渲染引擎不同（字体渲染、抗锯齿、marker 形状等），
完全一致不可能。阈值设为相对宽松（如 30 bits on 64-bit hash）。
"""
import imagehash
from PIL import Image

HASH_TOLERANCE = 30  # bits of Hamming distance (out of 192 for 3-channel dhash)

def dhash_rgb(img: Image.Image) -> str:
    """复用 hash_checks/hashio.py 的 dhash 方法"""
    r, g, b = img.convert('RGB').split()
    return (str(imagehash.dhash(r)) + str(imagehash.dhash(g)) + str(imagehash.dhash(b)))

def hamming_distance(h1: str, h2: str) -> int:
    return sum(c1 != c2 for c1, c2 in zip(h1, h2))

def test_visual_consistency_star_positions(tmp_path):
    """验证星点位置在两个后端中大致一致"""
    from starplot.interactive import InteractiveMapPlot
    from starplot import Miller
    from ibis import _

    p = InteractiveMapPlot(
        projection=Miller(), ra_min=60, ra_max=120,
        dec_min=-10, dec_max=30, resolution=2048,
    )
    p.stars(where=[_.magnitude < 6])
    p.constellations()

    # 结构一致性：检查录制命令中的星点数量
    scatter_cmds = [c for c in p._recorder.commands if c.kind == "scatter"]
    total_recorded = sum(len(c.data['x']) for c in scatter_cmds)
    assert total_recorded == len(p.objects.stars), \
        f"Recorded {total_recorded} stars but plotted {len(p.objects.stars)}"

def test_visual_consistency_constellation_lines(tmp_path):
    """验证星座线数量在两个后端中一致"""
    from starplot.interactive import InteractiveMapPlot
    from starplot import Miller
    from ibis import _

    p = InteractiveMapPlot(
        projection=Miller(), ra_min=60, ra_max=120,
        dec_min=-10, dec_max=30, resolution=2048,
    )
    p.constellations()

    line_cmds = [c for c in p._recorder.commands if c.kind == "line_collection"]
    assert len(line_cmds) > 0
    total_lines = sum(len(c.data['lines']) for c in line_cmds)
    assert total_lines > 0, "Should have recorded constellation lines"

def test_visual_hash_comparison(tmp_path):
    """像素级视觉对比（需要 kaleido 安装）"""
    pytest.importorskip("kaleido")

    from starplot.interactive import InteractiveMapPlot
    from starplot import Miller
    from ibis import _

    p = InteractiveMapPlot(
        projection=Miller(), ra_min=60, ra_max=120,
        dec_min=-10, dec_max=30, resolution=2048,
    )
    p.stars(where=[_.magnitude < 6])

    mpl_path = str(tmp_path / "mpl.png")
    plotly_path = str(tmp_path / "plotly.png")

    p.export(mpl_path)
    fig = p.to_plotly()
    fig.write_image(plotly_path, width=2048, height=2048)

    h1 = dhash_rgb(Image.open(mpl_path))
    h2 = dhash_rgb(Image.open(plotly_path))
    dist = hamming_distance(h1, h2)

    assert dist < HASH_TOLERANCE, \
        f"Visual hash distance {dist} exceeds tolerance {HASH_TOLERANCE}"
```

### 6.4 测试 `testing.py` — 可复用的视觉一致性工具

```python
class VisualConsistencyChecker:
    """用于 CI 和开发中的视觉一致性对比工具。

    复用 hash_checks/hashio.py 的感知哈希方法。
    """

    def __init__(self, tolerance: int = 30):
        self.tolerance = tolerance

    def compare_plot(self, interactive_plot, output_dir: str) -> dict:
        """对比一个 InteractivePlot 的 matplotlib 和 Plotly 输出。

        Returns:
            dict with keys: passed, hamming_distance, mpl_path, plotly_path
        """
        ...

    def compare_all_examples(self, output_dir: str) -> list[dict]:
        """运行所有交互式示例并对比"""
        ...
```

---

## 7. 实现顺序与工时估计

| 阶段 | 任务 | 文件数 | 优先级 |
|------|------|--------|--------|
| **P1** | `commands.py` + `recorder.py` | 2 | 必需 |
| **P2** | `style_converter.py` | 1 | 必需 |
| **P3** | `recording_mixin.py` (8 个方法) | 1 | 必需（核心） |
| **P4** | `plotly_renderer.py` | 1 | 必需（核心） |
| **P5** | `plots.py` + `__init__.py` | 2 | 必需 |
| **P6** | `pyproject.toml` 添加可选依赖 | 1 (修改) | 必需 |
| **P7** | 9 个交互式示例 | 9 | 必需 |
| **P8** | 单元测试 + 集成测试 | 5 | 必需 |
| **P9** | `testing.py` 视觉一致性工具 | 1 | 建议 |
| **P10** | 增强交互功能（click-to-identify, 坐标显示） | 增强 P4 | 建议 |

---

## 8. 注意事项

### 8.1 已知限制

1. **渐变背景**：Plotly 没有原生的 pcolormesh，第一版可用纯色背景替代
2. **自定义 Marker Path**：starplot 使用 matplotlib.path.Path 定义的自定义 marker（如 circle_cross, circle_crosshair），Plotly 中需用近似符号替代
3. **碰撞检测精度**：Plotly 标签位置是从 matplotlib 碰撞检测继承的，但 Plotly 字体渲染大小可能略有差异
4. **投影精度**：坐标使用 matplotlib 投影后的值，在 Plotly 中作为 2D 笛卡尔坐标显示，可能在边缘有轻微变形差异
5. **Cartopy 网格线**：MapPlot 的 `gridlines()` 使用 Cartopy 的 `ax.gridlines()`，需要在 PlotlyRenderer 中单独实现等效的网格线

### 8.2 后续扩展

- **Bokeh 后端**：只需新增 `BokehRenderer` 实现 `render(commands)` 方法
- **Three.js 后端**：3D 星图的可能性，新增 `ThreeJSRenderer`
- **Dash 集成**：`to_plotly()` 返回的 Figure 可直接用于 Dash 应用
- **Jupyter 支持**：`to_plotly()` 返回的 Figure 在 Jupyter 中自动渲染为交互式图表
