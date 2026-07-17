(function (global) {
  "use strict";

  const KIND_TYPES = Object.freeze({
    scatter: "scattergl",
    line: "scatter",
    line_collection: "scattergl",
    polygon: "scatter",
    text: "scatter",
    gradient: "heatmap",
    info_table: "table",
  });
  const LINE_DASH = Object.freeze({ solid: "solid", dashed: "dash", dotted: "dot", dashdot: "dashdot" });
  const MARKER_SYMBOL = Object.freeze({ circle: "circle", square: "square", triangle: "triangle-up", star: "star", diamond: "diamond" });

  function traceTypeForLayer(layer) {
    if (layer.kind === "scatter") {
      return layer.group_id === "stars" || Number(layer.row_count || 0) > 1000
        ? "scattergl"
        : "scatter";
    }
    return KIND_TYPES[layer.kind];
  }

  function column(table, name, required = true) {
    const value = table.getChild(name);
    if (!value) {
      if (required) throw new Error(`Arrow table is missing required column ${name}`);
      return null;
    }
    return value.toArray();
  }

  function styleFor(layer, scene) {
    if (layer.style && typeof layer.style === "object") return layer.style;
    if (!layer.style_id) return {};
    const asset = (scene.styles || []).find((item) => item.id === layer.style_id);
    if (!asset) throw new Error(`unknown style id ${layer.style_id} for layer ${layer.id}`);
    return asset.value || {};
  }

  function paletteFor(style, scene) {
    if (!style.palette_id) return [];
    const asset = (scene.palettes || []).find((item) => item.id === style.palette_id);
    if (!asset) throw new Error(`unknown palette id ${style.palette_id}`);
    return asset.colors || [];
  }

  function coordinateRefs(layer, style) {
    if (layer.coordinate_space === "data" && style.xref === "paper" && style.yref === "paper") {
      return ["paper", "paper"];
    }
    if (layer.coordinate_space === "axes") return ["x domain", "y domain"];
    if (layer.coordinate_space === "paper") return ["paper", "paper"];
    return ["x", "y"];
  }

  function clipFor(layer, scene) {
    if (!layer.clip_id) return null;
    const clips = Array.isArray(scene.clips)
      ? scene.clips
      : Object.entries(scene.clips || {}).map(([id, value]) => ({ id, ...value }));
    const clip = clips.find((value) => value.id === layer.clip_id);
    if (!clip) throw new Error(`unknown clip id ${layer.clip_id} for layer ${layer.id}`);
    return clip;
  }

  function decodeCoordinate(layer, table, name) {
    const values = column(table, name);
    const encoding = layer.coordinate_encoding && layer.coordinate_encoding[name];
    if (!encoding || encoding.kind === "absolute-f64"
        || (encoding.origin === 0 && encoding.scale === 1)) return values;
    const result = new Float64Array(values.length);
    for (let index = 0; index < values.length; index += 1) {
      result[index] = values[index] * encoding.scale + encoding.origin;
    }
    return result;
  }

  function pathCoordinates(layer, table) {
    const x = decodeCoordinate(layer, table, "x");
    const y = decodeCoordinate(layer, table, "y");
    const paths = column(table, "path_id");
    let breaks = 0;
    for (let index = 1; index < paths.length; index += 1) {
      if (paths[index] !== paths[index - 1]) breaks += 1;
    }
    if (!breaks) return { x, y };
    const XArray = x instanceof Float32Array && y instanceof Float32Array ? Float32Array : Float64Array;
    const resultX = new XArray(x.length + breaks);
    const resultY = new XArray(y.length + breaks);
    let target = 0;
    for (let index = 0; index < x.length; index += 1) {
      if (index && paths[index] !== paths[index - 1]) {
        resultX[target] = NaN;
        resultY[target] = NaN;
        target += 1;
      }
      resultX[target] = x[index];
      resultY[target] = y[index];
      target += 1;
    }
    return { x: resultX, y: resultY };
  }

  function lineStyle(style) {
    const dash = Array.isArray(style.line_style)
      ? "solid"
      : (LINE_DASH[String(style.line_style || "solid")] || "solid");
    return {
      color: style.color || "#777777",
      width: Math.max(0.25, Number(style.width || 1)),
      dash,
    };
  }

  function discreteColorscale(palette) {
    if (!palette.length) return [[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]];
    if (palette.length === 1) return [[0, palette[0]], [1, palette[0]]];
    const result = [];
    for (let index = 0; index < palette.length; index += 1) {
      result.push([index / palette.length, palette[index]]);
      result.push([(index + 1) / palette.length, palette[index]]);
    }
    result[result.length - 1][0] = 1;
    return result;
  }

  function scatterTrace(layer, table, scene, style) {
    const palette = paletteFor(style, scene);
    const size = column(table, "size");
    const opacity = column(table, "opacity");
    const colorIndex = column(table, "color_index");
    const useWebgl = traceTypeForLayer({ ...layer, row_count: layer.row_count ?? table.numRows }) === "scattergl";
    const markerSize = new Float32Array(size.length);
    const markerOpacity = useWebgl ? new Float32Array(opacity.length) : opacity;
    for (let index = 0; index < size.length; index += 1) {
      const scaled = size[index] * 1.15;
      markerSize[index] = Math.max(scaled, useWebgl ? 1 : 1.5);
      if (useWebgl) {
        const coverage = Math.min(1, scaled * scaled * 6);
        markerOpacity[index] = opacity[index] * coverage;
      }
    }
    const transparent = String(style.fill || "").toLowerCase() === "none";
    const trace = {
      type: useWebgl ? "scattergl" : "scatter",
      x: decodeCoordinate(layer, table, "x"),
      y: decodeCoordinate(layer, table, "y"),
      mode: "markers",
      marker: {
        size: markerSize,
        color: transparent ? "rgba(0,0,0,0)" : colorIndex,
        opacity: markerOpacity,
        symbol: MARKER_SYMBOL[style.symbol || "circle"] || style.symbol || "circle",
        line: {
          color: style.edge_color || "rgba(0,0,0,0)",
          width: useWebgl ? 0 : Math.max(0, Number(style.edge_width || 0) * 2),
        },
        ...(transparent ? {} : {
          colorscale: discreteColorscale(palette),
          cmin: -0.5,
          cmax: Math.max(0.5, palette.length - 0.5),
          showscale: false,
        }),
      },
      hoverinfo: layer.interactive ? "text" : "skip",
      name: String(style.legend_label || layer.group_id || layer.id),
      legendgroup: layer.group_id,
      showlegend: Boolean(style.legend_label),
    };
    if (layer.interactive && layer.hover_fields && layer.hover_fields.length) {
      const values = layer.hover_fields.map((name) => {
        const result = column(table, name, false);
        if (!result) throw new Error(`interactive layer ${layer.id} is missing hover field ${name}`);
        return result;
      });
      trace.customdata = Array.from({ length: table.numRows }, (_, row) =>
        values.map((items) => items[row]));
      trace.hovertemplate = layer.hover_fields
        .map((name, index) => `${name}: %{customdata[${index}]}`)
        .join("<br>") + "<extra></extra>";
      trace.hoverinfo = "all";
    }
    return trace;
  }

  function lineTrace(layer, table, style) {
    const coordinates = pathCoordinates(layer, table);
    return {
      type: layer.kind === "line_collection" ? "scattergl" : "scatter",
      x: coordinates.x,
      y: coordinates.y,
      mode: "lines",
      line: lineStyle(style),
      opacity: style.alpha === undefined ? 1 : Number(style.alpha),
      hoverinfo: "none",
      name: String(style.legend_label || layer.group_id || layer.id),
      legendgroup: layer.group_id,
      showlegend: Boolean(style.legend_label),
    };
  }

  function polygonTrace(layer, table, style) {
    const x = decodeCoordinate(layer, table, "x");
    const y = decodeCoordinate(layer, table, "y");
    const polygonIds = column(table, "polygon_id");
    const ringIds = column(table, "ring_id");
    const ringSets = new Map();
    for (let index = 0; index < polygonIds.length; index += 1) {
      const rings = ringSets.get(polygonIds[index]) || new Set();
      rings.add(ringIds[index]);
      ringSets.set(polygonIds[index], rings);
    }
    if ([...ringSets.values()].some((rings) => rings.size > 1)) {
      throw new Error(
        "polygon holes are not supported by the one-trace browser adapter; " +
        "refusing to render rather than silently filling holes",
      );
    }
    let separators = 0;
    for (let index = 1; index < x.length; index += 1) {
      if (polygonIds[index] !== polygonIds[index - 1] || ringIds[index] !== ringIds[index - 1]) separators += 1;
    }
    const resultX = new Float64Array(x.length + separators * 2 + 1);
    const resultY = new Float64Array(y.length + separators * 2 + 1);
    let target = 0;
    let start = 0;
    for (let index = 0; index <= x.length; index += 1) {
      const boundary = index === x.length
        || (index && (polygonIds[index] !== polygonIds[index - 1] || ringIds[index] !== ringIds[index - 1]));
      if (!boundary) continue;
      for (let source = start; source < index; source += 1) {
        resultX[target] = x[source]; resultY[target] = y[source]; target += 1;
      }
      if (index > start) {
        resultX[target] = x[start]; resultY[target] = y[start]; target += 1;
        resultX[target] = NaN; resultY[target] = NaN; target += 1;
      }
      start = index;
    }
    return {
      type: "scatter",
      x: resultX.subarray(0, target),
      y: resultY.subarray(0, target),
      mode: "lines",
      fill: style.fill_color && String(style.fill_color).toLowerCase() !== "none" ? "toself" : undefined,
      fillcolor: style.fill_color || "rgba(0,0,0,0)",
      line: { color: style.edge_color || "rgba(0,0,0,0)", width: Math.max(0, Number(style.edge_width || 0)) },
      opacity: style.alpha === undefined ? 1 : Number(style.alpha),
      hoverinfo: "none",
      showlegend: false,
    };
  }

  function textTrace(layer, table, scene, style) {
    const text = Array.from(column(table, "text"), (value) => String(value).replaceAll("\n", "<br>"));
    const x = decodeCoordinate(layer, table, "x");
    const y = decodeCoordinate(layer, table, "y");
    const xOffset = column(table, "x_offset");
    const yOffset = column(table, "y_offset");
    const rotation = column(table, "rotation");
    const styleIds = column(table, "style_id");
    const variants = Array.isArray(style.text_styles) && style.text_styles.length
      ? style.text_styles
      : [style];
    const fontSize = new Float32Array(text.length);
    const fontColor = new Array(text.length);
    const fontFamily = new Array(text.length);
    const outputX = new Float64Array(x.length);
    const outputY = new Float64Array(y.length);
    const viewport = scene.viewport || {};
    const bounds = viewport.data_bounds || {};
    const [xref, yref] = coordinateRefs(layer, style);
    const width = Math.max(1, Number(viewport.reference_width || 1));
    const height = Math.max(1, Number(viewport.reference_height || 1));
    const xScale = xref === "x" ? Number(bounds.x_max - bounds.x_min || 1) / width : 1 / width;
    const yScale = yref === "y" ? Number(bounds.y_max - bounds.y_min || 1) / height : 1 / height;
    for (let index = 0; index < text.length; index += 1) {
      const variant = variants[styleIds[index]];
      if (!variant) throw new Error(`text style_id ${styleIds[index]} is not defined for layer ${layer.id}`);
      fontSize[index] = Math.max(8, Number(variant.font_size || style.font_size || 12));
      fontColor[index] = variant.font_color || style.font_color || "#ffffff";
      fontFamily[index] = variant.font_name || style.font_name || "Inter, Arial, sans-serif";
      outputX[index] = x[index] + xOffset[index] * xScale;
      outputY[index] = y[index] + yOffset[index] * yScale;
    }
    const trace = {
      type: "scatter",
      x: outputX,
      y: outputY,
      mode: "text",
      text,
      textposition: "middle center",
      textfont: {
        size: fontSize,
        color: fontColor,
        family: fontFamily,
      },
      textangle: rotation,
      opacity: style.font_alpha === undefined ? (style.alpha === undefined ? 1 : Number(style.alpha)) : Number(style.font_alpha),
      hoverinfo: "skip",
      showlegend: false,
    };
    if (xref !== "x" || yref !== "y") {
      trace.xaxis = "x2";
      trace.yaxis = "y2";
      if (xref === "paper" && yref === "paper") {
        trace.xaxis = "x3";
        trace.yaxis = "y3";
      }
    }
    trace.cliponaxis = false;
    trace.meta = { xref, yref };
    return trace;
  }

  function pointInClip(x, y, clip) {
    const points = clip.points || [];
    if (clip.kind === "rect") {
      const xs = points.map((point) => Number(point[0]));
      const ys = points.map((point) => Number(point[1]));
      return x >= Math.min(...xs) && x <= Math.max(...xs)
        && y >= Math.min(...ys) && y <= Math.max(...ys);
    }
    if (clip.kind !== "polygon" || points.length < 3) {
      throw new Error(`unsupported clip geometry kind ${clip.kind}`);
    }
    let inside = false;
    for (let index = 0, previous = points.length - 1; index < points.length; previous = index, index += 1) {
      const xi = Number(points[index][0]), yi = Number(points[index][1]);
      const xj = Number(points[previous][0]), yj = Number(points[previous][1]);
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  function gradientTrace(layer, scene, style) {
    const bounds = (scene.viewport && scene.viewport.data_bounds) || {};
    const xMin = Number(bounds.x_min || 0), xMax = Number(bounds.x_max || 1);
    const yMin = Number(bounds.y_min || 0), yMax = Number(bounds.y_max || 1);
    const direction = style.direction || "linear";
    if (!["linear", "radial", "mollweide"].includes(direction)) {
      throw new Error(`unsupported gradient direction: ${direction}`);
    }
    if (!Array.isArray(style.color_stops) || style.color_stops.length < 2) {
      throw new Error(`gradient layer ${layer.id} requires at least two color stops`);
    }
    const clip = clipFor(layer, scene);
    const radial = direction === "radial";
    const rows = direction === "linear" ? (clip ? 220 : 2000) : (radial ? 220 : 250);
    const columns = direction === "linear" ? (clip ? 220 : 2) : (radial ? 220 : 250);
    const x = new Float64Array(columns), y = new Float64Array(rows);
    for (let index = 0; index < columns; index += 1) x[index] = xMin + (xMax - xMin) * index / Math.max(1, columns - 1);
    for (let index = 0; index < rows; index += 1) y[index] = yMin + (yMax - yMin) * index / Math.max(1, rows - 1);
    const z = new Array(rows);
    for (let row = 0; row < rows; row += 1) {
      z[row] = new Float32Array(columns);
      for (let col = 0; col < columns; col += 1) {
        let value;
        let valid = true;
        if (radial) {
          const clipXs = clip ? clip.points.map((point) => Number(point[0])) : [xMin, xMax];
          const clipYs = clip ? clip.points.map((point) => Number(point[1])) : [yMin, yMax];
          const clipXMin = Math.min(...clipXs), clipXMax = Math.max(...clipXs);
          const clipYMin = Math.min(...clipYs), clipYMax = Math.max(...clipYs);
          const center = style.center || [(clipXMin + clipXMax) / 2, (clipYMin + clipYMax) / 2];
          const defaultRadius = clip
            ? Math.min(clipXMax - clipXMin, clipYMax - clipYMin) / 2
            : Math.max(
              Math.abs(xMax - center[0]), Math.abs(xMin - center[0]),
              Math.abs(yMax - center[1]), Math.abs(yMin - center[1]),
            );
          const resolvedRadius = Math.max(
            Number(style.radius === undefined || style.radius === null ? defaultRadius : style.radius),
            1e-9,
          );
          const radiusSquared = ((x[col] - Number(center[0])) / resolvedRadius) ** 2
            + ((y[row] - Number(center[1])) / resolvedRadius) ** 2;
          value = Math.min(1, radiusSquared);
          // Match the Python adapter: an explicit clip is the radial mask.
          // Without a clip, the resolved radius defines the circular mask.
          valid = clip ? true : radiusSquared <= 1;
        } else if (direction === "mollweide") {
          const xNormalized = 2 * col / Math.max(1, columns - 1) - 1;
          const yNormalized = 2 * row / Math.max(1, rows - 1) - 1;
          const theta = Math.asin(Math.max(-1, Math.min(1, yNormalized)));
          const cosTheta = Math.cos(theta);
          const longitude = Math.abs(cosTheta) > 1e-12 ? Math.PI * xNormalized / cosTheta : Infinity;
          const latitude = Math.asin(Math.max(-1, Math.min(1, (2 * theta + Math.sin(2 * theta)) / Math.PI)));
          const cosLatitude = Math.cos(latitude);
          const equatorial = [
            cosLatitude * Math.cos(longitude),
            -cosLatitude * Math.sin(longitude),
            -Math.sin(latitude),
          ];
          const galacticZ = -0.8676661490190047 * equatorial[0]
            + -0.1980763734312015 * equatorial[1]
            + 0.4559837761750669 * equatorial[2];
          value = (Math.asin(Math.max(-1, Math.min(1, galacticZ))) + Math.PI / 2) / Math.PI;
          valid = Math.abs(yNormalized) <= 1 && Math.abs(longitude) <= Math.PI && Math.abs(cosTheta) > 1e-12;
        } else value = row / Math.max(1, rows - 1);
        if (clip && !pointInClip(x[col], y[row], clip)) valid = false;
        z[row][col] = valid ? value : NaN;
      }
    }
    let colorscale = style.color_stops.map((stop) => [Number(stop[0]), String(stop[1])]);
    if (radial) {
      const positions = colorscale.map((stop) => stop[0] / 2);
      positions[positions.length - 1] = 1;
      colorscale = colorscale.map((stop, index) => [1 - positions[index], stop[1]]).reverse();
    }
    return {
      type: "heatmap", x, y, z,
      colorscale,
      zmin: 0, zmax: 1, zsmooth: direction === "linear" ? false : "best",
      showscale: false, hoverinfo: "skip", showlegend: false,
    };
  }

  function infoTableTrace(table, style) {
    return {
      type: "table",
      header: {
        values: Array.from(column(table, "column"), String),
        font: { color: style.font_color || "#111111", size: Number(style.font_size || 12) * 1.2 },
      },
      cells: {
        values: [Array.from(column(table, "value"), String)],
        font: { color: style.font_color || "#111111", size: Number(style.font_size || 12) },
      },
      columnwidth: column(table, "width"),
      showlegend: false,
    };
  }

  function layerToPlotlyTrace(layer, table, scene) {
    if (!KIND_TYPES[layer.kind]) throw new Error(`unsupported Scene kind: ${layer.kind}`);
    const style = styleFor(layer, scene);
    clipFor(layer, scene);
    let trace;
    if (layer.kind === "scatter") trace = scatterTrace(layer, table, scene, style);
    else if (layer.kind === "line" || layer.kind === "line_collection") trace = lineTrace(layer, table, style);
    else if (layer.kind === "polygon") trace = polygonTrace(layer, table, style);
    else if (layer.kind === "text") trace = textTrace(layer, table, scene, style);
    else if (layer.kind === "gradient") trace = gradientTrace(layer, scene, style);
    else trace = infoTableTrace(table, style);
    const [xref, yref] = coordinateRefs(layer, style);
    if (["scatter", "line", "line_collection", "polygon", "text"].includes(layer.kind)
        && (xref !== "x" || yref !== "y")) {
      trace.xaxis = xref === "paper" ? "x3" : "x2";
      trace.yaxis = yref === "paper" ? "y3" : "y2";
      trace.cliponaxis = false;
    }
    trace.meta = {
      ...(trace.meta || {}),
      starplot_layer_id: layer.id,
      starplot_zorder: layer.zorder,
      xref,
      yref,
      clip_id: layer.clip_id || null,
    };
    return trace;
  }

  function placeholder(layer) {
    return {
      type: traceTypeForLayer(layer),
      visible: false,
      meta: { starplot_layer_id: layer.id, starplot_zorder: layer.zorder },
    };
  }

  function sceneLayout(scene) {
    const viewport = scene.viewport || {};
    const bounds = viewport.data_bounds || {};
    return {
      paper_bgcolor: viewport.paper_background || "#ffffff",
      plot_bgcolor: viewport.axes_background || "#ffffff",
      xaxis: {
        range: bounds.x_min === undefined ? undefined : [bounds.x_min, bounds.x_max],
        showgrid: false, zeroline: false, constrain: "domain",
      },
      yaxis: {
        range: bounds.y_min === undefined ? undefined : [bounds.y_min, bounds.y_max],
        showgrid: false, zeroline: false, scaleanchor: "x", scaleratio: 1,
      },
      xaxis2: { range: [0, 1], overlaying: "x", visible: false, fixedrange: true },
      yaxis2: { range: [0, 1], overlaying: "y", visible: false, fixedrange: true },
      xaxis3: { range: [0, 1], domain: [0, 1], overlaying: "x", visible: false, fixedrange: true },
      yaxis3: { range: [0, 1], domain: [0, 1], overlaying: "y", visible: false, fixedrange: true },
      showlegend: Boolean(viewport.showlegend),
      margin: viewport.margin || { l: 10, r: 10, t: 10, b: 10 },
    };
  }

  function restyleUpdate(trace) {
    const update = {};
    for (const [name, value] of Object.entries(trace)) update[name] = [value];
    update.visible = [true];
    return update;
  }

  async function renderScene(target, source, options) {
    const settings = options || {};
    const Plotly = settings.Plotly || global.Plotly;
    if (!Plotly || typeof Plotly.react !== "function" || typeof Plotly.restyle !== "function") {
      throw new Error("Plotly 3.x must be loaded before rendering a Starplot Scene");
    }
    if (!source || typeof source.loadManifest !== "function" || typeof source.loadLayer !== "function") {
      throw new Error("source must implement the SceneSource contract");
    }
    const scene = await source.loadManifest(settings.signal);
    const slots = [...scene.layers].sort((left, right) =>
      Number(left.zorder) - Number(right.zorder) || String(left.id).localeCompare(String(right.id)));
    const slotById = new Map(slots.map((layer, index) => [layer.id, index]));
    await Plotly.react(target, slots.map(placeholder), sceneLayout(scene), settings.config || {});
    const loadOrder = [...scene.layers].sort((left, right) =>
      Number(left.load_priority) - Number(right.load_priority)
      || Number(left.zorder) - Number(right.zorder)
      || String(left.id).localeCompare(String(right.id)));
    for (const layer of loadOrder) {
      const table = await global.StarplotScene.collectLayerTable(
        source,
        layer,
        settings.request,
        settings.signal,
      );
      const trace = layerToPlotlyTrace(layer, table, scene);
      await Plotly.restyle(target, restyleUpdate(trace), [slotById.get(layer.id)]);
    }
    return target;
  }

  global.StarplotScene = Object.assign(global.StarplotScene || {}, {
    layerToPlotlyTrace,
    renderScene,
    traceTypeForLayer,
  });
})(typeof window !== "undefined" ? window : globalThis);
