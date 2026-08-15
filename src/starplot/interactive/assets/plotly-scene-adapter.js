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
  const LINE_DASH = Object.freeze({
    solid: "solid", "-": "solid",
    dashed: "dash", "--": "dash",
    dotted: "dot", ":": "dot",
    dashdot: "dashdot", "-.": "dashdot",
  });
  const MARKER_SYMBOL = Object.freeze({
    point: "circle",
    circle: "circle",
    square: "square",
    star: "star",
    diamond: "diamond",
    triangle: "triangle-up",
    plus: "cross",
    circle_plus: "circle-cross",
    circle_cross: "circle-x",
    circle_dot: "circle-dot",
    comet: "star-diamond",
    star_4: "star-square",
    // Keep this native Plotly symbol aligned with the Python adapter.
    star_8: "asterisk",
    // Matplotlib's ellipse marker is a 2:1 ellipse rotated 15°. Plotly custom
    // SVG path markers are centered at the origin with r=10 equal to half the
    // marker size; this path is the same 100-point ellipse scaled to that grid.
    ellipse: (
      "M 9.6593,2.5882 L 9.5577,2.8893 L 9.4177,3.1788 L 9.2398,3.4554 L 9.0247,3.7182 " +
      "L 8.7732,3.9660 L 8.4864,4.1978 L 8.1654,4.4127 L 7.8116,4.6098 L 7.4262,4.7884 " +
      "L 7.0110,4.9477 L 6.5676,5.0871 L 6.0977,5.2060 L 5.6033,5.3039 L 5.0863,5.3805 " +
      "L 4.5488,5.4354 L 3.9930,5.4684 L 3.4211,5.4794 L 2.8355,5.4684 L 2.2384,5.4353 " +
      "L 1.6323,5.3803 L 1.0196,5.3037 L 0.4029,5.2057 L -0.2155,5.0867 L -0.8330,4.9473 " +
      "L -1.4472,4.7880 L -2.0555,4.6093 L -2.6556,4.4121 L -3.2449,4.1972 L -3.8212,3.9653 " +
      "L -4.3822,3.7175 L -4.9254,3.4547 L -5.4489,3.1780 L -5.9503,2.8885 L -6.4279,2.5874 " +
      "L -6.8795,2.2758 L -7.3035,1.9551 L -7.6980,1.6265 L -8.0616,1.2914 L -8.3926,0.9510 " +
      "L -8.6899,0.6069 L -8.9522,0.2602 L -9.1785,-0.0874 L -9.3678,-0.4347 L -9.5193,-0.7803 " +
      "L -9.6326,-1.1227 L -9.7070,-1.4606 L -9.7424,-1.7926 L -9.7385,-2.1174 L -9.6955,-2.4337 " +
      "L -9.6133,-2.7401 L -9.4925,-3.0356 L -9.3335,-3.3188 L -9.1368,-3.5886 L -8.9034,-3.8440 " +
      "L -8.6341,-4.0839 L -8.3301,-4.3074 L -7.9925,-4.5135 L -7.6227,-4.7015 L -7.2223,-4.8705 " +
      "L -6.7927,-5.0199 L -6.3358,-5.1491 L -5.8534,-5.2576 L -5.3475,-5.3449 L -4.8199,-5.4107 " +
      "L -4.2730,-5.4547 L -3.7089,-5.4767 L -3.1299,-5.4766 L -2.5382,-5.4546 L -1.9363,-5.4105 " +
      "L -1.3266,-5.3447 L -0.7116,-5.2573 L -0.0937,-5.1488 L 0.5245,-5.0196 L 1.1407,-4.8701 " +
      "L 1.7522,-4.7010 L 2.3567,-4.5130 L 2.9517,-4.3068 L 3.5349,-4.0833 L 4.1038,-3.8433 " +
      "L 4.6561,-3.5879 L 5.1898,-3.3180 L 5.7025,-3.0348 L 6.1922,-2.7393 L 6.6571,-2.4328 " +
      "L 7.0951,-2.1165 L 7.5045,-1.7917 L 7.8838,-1.4597 L 8.2312,-1.1218 L 8.5456,-0.7793 " +
      "L 8.8255,-0.4338 L 9.0699,-0.0865 L 9.2778,0.2612 L 9.4483,0.6078 L 9.5808,0.9520 " +
      "L 9.6747,1.2923 L 9.7296,1.6274 L 9.7454,1.9560 L 9.7219,2.2767 L 9.6593,2.5882 Z"
    ),
    circle_crosshair: "circle-cross",
    circle_line: "circle",
    circle_dotted_edge: "circle",
    circle_dotted_rings: "circle-dot",
    square_stripes_diagonal: "square",
    sun: "star",
    ".": "circle",
    "o": "circle",
    "s": "square",
    "*": "star",
    "D": "diamond",
    "^": "triangle-up",
    "+": "cross",
  });
  const GROUP_NAMES = Object.freeze({
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
    "dso": "DSOs",
    "dso_galaxy": "Galaxies",
    "dso_nebula": "Nebulae",
    "dso_open_cluster": "Open Clusters",
    "dso_globular_cluster": "Globular Clusters",
  });
  function traceName(layer, style) {
    let name = "";
    if (style && style.legend_label) {
      name = String(style.legend_label);
    } else {
      const group = String(layer.group_id || "");
      if (GROUP_NAMES[group]) {
        name = GROUP_NAMES[group];
      } else if (group) {
        name = group
          .replace(/[-_]/g, " ")
          .replace(/\b\w/g, (character) => character.toUpperCase());
      }
    }
    return escapePlotlyText(name);
  }
  const MAX_INTERACTIVE_HOVER_POINTS = 100000;
  const MAX_SVG_ZORDER_POINTS = 100000;
  // Plotly ScatterGL spends most of its large-scene setup time materializing a
  // per-point colorscale.  Astronomy catalogs normally use a small discrete
  // palette, so split only genuinely dense, non-hoverable layers into a
  // bounded set of colour batches.  Coordinates, sizes, and opacities remain
  // per point; this changes neither Scene nor Arrow data.
  const MIN_DENSE_PALETTE_BATCH_ROWS = 100000;
  const MAX_DENSE_PALETTE_BATCHES = 64;
  const layoutEffects = new WeakMap();
  const markerSourceByTrace = new WeakMap();
  const textStrokeByAnnotation = new WeakMap();

  function escapePlotlyText(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function safePlotlyText(value) {
    return escapePlotlyText(value).replaceAll("\n", "<br>");
  }

  function layerFailureMessage(layer, error) {
    const message = error && error.message ? String(error.message) : "layer could not be loaded";
    return `Layer ${String(layer.id)} could not be loaded: ${message.replace(/https?:\/\/[^\s)]+/g, "remote data")}`;
  }

  function showLayerFailure(target, layer, error, retry, optional) {
    if (!target || !target.ownerDocument || typeof target.ownerDocument.createElement !== "function") return;
    const document = target.ownerDocument;
    const id = `starplot-layer-error-${String(layer.id).replace(/[^A-Za-z0-9_-]/g, "-")}`;
    let notice = document.getElementById(id);
    if (!notice) {
      notice = document.createElement("div"); notice.id = id; notice.setAttribute("role", "alert");
      notice.style.cssText = "position:absolute;left:1rem;right:1rem;bottom:1rem;padding:.75rem;background:#300;color:#fff;z-index:10";
      target.parentNode && target.parentNode.appendChild(notice);
    }
    notice.replaceChildren();
    const text = document.createElement("span");
    text.textContent = `${optional ? "Warning: " : "Error: "}${layerFailureMessage(layer, error)}`;
    notice.appendChild(text);
    if (typeof retry === "function") {
      const button = document.createElement("button"); button.type = "button"; button.textContent = "Retry";
      button.addEventListener("click", retry, { once: true }); notice.appendChild(document.createTextNode(" ")); notice.appendChild(button);
    }
  }

  function hiddenLayerTrace(layer) {
    if (traceTypeForLayer(layer) === "heatmap") {
      return { type: "heatmap", z: [[null]], hoverinfo: "skip", showscale: false, visible: false };
    }
    return {
      type: "scatter", x: [null], y: [null], mode: "markers",
      hoverinfo: "skip", showlegend: false, visible: false,
    };
  }

  function traceTypeForLayer(layer, forceSvgTracePlane = false) {
    if (forceSvgTracePlane && ["scatter", "line_collection"].includes(layer.kind)) return "scatter";
    if (layer.kind === "scatter") {
      return (
        layer.group_id === "stars" || Number(layer.row_count || 0) > 1000
      ) ? "scattergl" : "scatter";
    }
    if (layer.kind === "info_table") return "scatter";
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

  function plotlyColor(value, fallback) {
    return (value && String(value).toLowerCase() !== "none") ? value : fallback;
  }

  function plotlyFontFamily(value, weight) {
    const raw = String(value || "Inter").trim();
    if (String(weight || "").toLowerCase().includes("bold")) {
      return "Arial Black, Arial, sans-serif";
    }
    return raw.includes(",") ? raw : `${raw}, Arial, sans-serif`;
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

  function plotlyLineDash(lineStyle) {
    if (Array.isArray(lineStyle)) return "dash";
    const raw = String(lineStyle || "solid").trim().toLowerCase();
    if (LINE_DASH[raw]) return LINE_DASH[raw];
    // Matplotlib serializes custom dash patterns obtained from an artist as
    // strings such as "(0, (1, 2))" or "(1, [2, 3])".  Plotly cannot
    // represent arbitrary dash arrays, but its named dash is the semantic
    // nearest supported stroke; treating it as solid loses the essential
    // visual distinction.
    if (/^\(.*,.*\)$/.test(raw)) return "dash";
    return "solid";
  }

  function lineStyle(style, strokeScale = 1) {
    const dash = plotlyLineDash(style.line_style);
    const rawWidth = style.width !== undefined ? style.width : (style.edge_width !== undefined ? style.edge_width : 1);
    const rawColor = style.color !== undefined ? style.color : (style.edge_color !== undefined ? style.edge_color : "#777777");
    const color = String(rawColor).toLowerCase() === "none" ? "rgba(0,0,0,0)" : rawColor;
    return {
      color,
      width: Math.max(0.25, Number(rawWidth || 1) * strokeScale),
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

  function scatterTrace(layer, table, scene, style, forceSvgTracePlane, strokeScale = 1, markerScale = 1) {
    const palette = paletteFor(style, scene);
    const size = column(table, "size");
    const opacity = column(table, "opacity");
    const colorIndex = column(table, "color_index");
    const useWebgl = traceTypeForLayer(
      { ...layer, row_count: layer.row_count ?? table.numRows },
      forceSvgTracePlane,
    ) === "scattergl";
    const markerSize = new Float32Array(size.length);
    const markerOpacity = useWebgl ? new Float32Array(opacity.length) : opacity;
    for (let index = 0; index < size.length; index += 1) {
      const scaled = size[index] * markerScale;
      markerSize[index] = Math.max(scaled, useWebgl ? 1 : 1.5);
      if (useWebgl) {
        // ScatterGL rounds subpixel markers up to one physical pixel. Preserve
        // the Matplotlib marker's area through opacity rather than turning a
        // dense field of fractional stars into fully covered pixels. The 2.0
        // scale factor is the browser-specific empirical calibration; Kaleido
        // uses a different constant because its scattergl rasterizer blends
        // subpixel opacity differently.
        const coverage = Math.min(1, 2.0 * scaled * scaled);
        markerOpacity[index] = opacity[index] * coverage;
      }
    }
    const edgeWidth = Math.max(0, Number(style.edge_width || 0) * strokeScale);
    const transparent = String(style.fill || "").toLowerCase() === "none";
    const hoverAllowed = layer.interactive
      && Number(layer.row_count ?? table.numRows) <= MAX_INTERACTIVE_HOVER_POINTS;
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
          color: plotlyColor(style.edge_color, "rgba(0,0,0,0)"),
          width: useWebgl ? 0 : edgeWidth,
        },
        ...(transparent ? {} : {
          colorscale: discreteColorscale(palette),
          cmin: -0.5,
          cmax: Math.max(0.5, palette.length - 0.5),
          showscale: false,
        }),
      },
      hoverinfo: hoverAllowed ? "text" : "skip",
      name: traceName(layer, style),
      legendgroup: layer.group_id,
      showlegend: Boolean(traceName(layer, style)),
    };
    if (hoverAllowed
        && layer.hover_fields && layer.hover_fields.length) {
      const values = layer.hover_fields.map((name) => {
        const result = column(table, name, false);
        if (!result) throw new Error(`interactive layer ${layer.id} is missing hover field ${name}`);
        return result;
      });
      trace.customdata = Array.from({ length: table.numRows }, (_, row) =>
        values.map((items) => typeof items[row] === "string" ? escapePlotlyText(items[row]) : items[row]));
      trace.hovertemplate = layer.hover_fields
        .map((name, index) => `${escapePlotlyText(name)}: %{customdata[${index}]}`)
        .join("<br>") + "<extra></extra>";
      trace.hoverinfo = "all";
    }
    markerSourceByTrace.set(trace, { size, opacity, webgl: useWebgl });
    if (!useWebgl) trace.zorder = Number(layer.zorder);
    return trace;
  }

  function densePaletteScatterTraces(layer, table, scene, style, forceSvgTracePlane, strokeScale = 1, markerScale = 1) {
    const rowCount = Number(layer.row_count ?? table.numRows);
    const palette = paletteFor(style, scene);
    const transparent = String(style.fill || "").toLowerCase() === "none";
    const useWebgl = traceTypeForLayer(
      { ...layer, row_count: layer.row_count ?? table.numRows },
      forceSvgTracePlane,
    ) === "scattergl";
    const hoverAllowed = layer.interactive
      && rowCount <= MAX_INTERACTIVE_HOVER_POINTS;
    const hasCustomdata = hoverAllowed
      && layer.hover_fields && layer.hover_fields.length;
    // SVG layers need their literal trace ordering, and sparse/hoverable data
    // benefits more from one trace than from a palette split.
    if (!useWebgl || transparent || hasCustomdata
        || rowCount < MIN_DENSE_PALETTE_BATCH_ROWS
        || table.numRows < MIN_DENSE_PALETTE_BATCH_ROWS || !palette.length
        || palette.length > MAX_DENSE_PALETTE_BATCHES) {
      return [scatterTrace(
        layer, table, scene, style, forceSvgTracePlane, strokeScale, markerScale,
      )];
    }

    const colorIndex = column(table, "color_index");
    const size = column(table, "size");
    const counts = new Uint32Array(palette.length);
    const maximumScaledSize = new Float64Array(palette.length);
    for (let index = 0; index < colorIndex.length; index += 1) {
      const color = colorIndex[index];
      if (color >= palette.length) {
        return [scatterTrace(
          layer, table, scene, style, forceSvgTracePlane, strokeScale, markerScale,
        )];
      }
      counts[color] += 1;
      maximumScaledSize[color] = Math.max(
        maximumScaledSize[color], size[index] * markerScale,
      );
    }
    const active = [];
    for (let color = 0; color < counts.length; color += 1) if (counts[color]) active.push(color);
    if (active.length < 2 || active.length > MAX_DENSE_PALETTE_BATCHES) {
      return [scatterTrace(
        layer, table, scene, style, forceSvgTracePlane, strokeScale, markerScale,
      )];
    }

    const x = column(table, "x");
    const y = column(table, "y");
    const opacity = column(table, "opacity");
    const xEncoding = layer.coordinate_encoding && layer.coordinate_encoding.x;
    const yEncoding = layer.coordinate_encoding && layer.coordinate_encoding.y;
    const decodeX = xEncoding && xEncoding.kind !== "absolute-f64"
      && (xEncoding.origin !== 0 || xEncoding.scale !== 1);
    const decodeY = yEncoding && yEncoding.kind !== "absolute-f64"
      && (yEncoding.origin !== 0 || yEncoding.scale !== 1);
    const XArray = decodeX ? Float64Array : x.constructor;
    const YArray = decodeY ? Float64Array : y.constructor;
    const offsets = new Uint32Array(counts.length);
    const buckets = new Array(palette.length);
    for (const color of active) {
      const length = counts[color];
      buckets[color] = {
        x: new XArray(length), y: new YArray(length),
        // Plotly accepts a scalar marker diameter.  Preserve subpixel
        // brightness in opacity, but avoid coercing and uploading a row-sized
        // array when every clamped diameter in this color bucket is exactly 1.
        size: maximumScaledSize[color] > 1 ? new Float32Array(length) : null,
        opacity: new Float32Array(length),
        sourceSize: new size.constructor(length),
        sourceOpacity: new opacity.constructor(length),
      };
    }
    for (let index = 0; index < colorIndex.length; index += 1) {
      const color = colorIndex[index];
      const bucket = buckets[color];
      const target = offsets[color];
      bucket.x[target] = decodeX
        ? x[index] * xEncoding.scale + xEncoding.origin : x[index];
      bucket.y[target] = decodeY
        ? y[index] * yEncoding.scale + yEncoding.origin : y[index];
      const scaled = size[index] * markerScale;
      if (bucket.size) bucket.size[target] = Math.max(scaled, 1);
      bucket.opacity[target] = opacity[index] * Math.min(1, 2.0 * scaled * scaled);
      bucket.sourceSize[target] = size[index];
      bucket.sourceOpacity[target] = opacity[index];
      offsets[color] += 1;
    }
    const edgeWidth = Math.max(0, Number(style.edge_width || 0) * strokeScale);
    const name = traceName(layer, style);
    return active.map((color, index) => {
      const bucket = buckets[color];
      const marker = {
        color: palette[color],
        size: bucket.size || 1,
        opacity: bucket.opacity,
        symbol: MARKER_SYMBOL[style.symbol || "circle"] || style.symbol || "circle",
        line: {
          color: plotlyColor(style.edge_color, "rgba(0,0,0,0)"),
          width: 0,
        },
      };
      const result = {
        type: "scattergl",
        x: bucket.x,
        y: bucket.y,
        mode: "markers",
        marker,
        hoverinfo: hoverAllowed ? "text" : "skip",
        name,
        legendgroup: layer.group_id,
        // A layer represents one legend item even when it is rendered by
        // several GPU batches.
        showlegend: index === 0 && Boolean(name),
      };
      markerSourceByTrace.set(result, {
        size: bucket.sourceSize, opacity: bucket.sourceOpacity, webgl: true,
      });
      return result;
    });
  }

  function lineTrace(layer, table, style, forceSvgTracePlane, strokePixelScale = 1) {
    const coordinates = pathCoordinates(layer, table);
    const type = traceTypeForLayer(layer, forceSvgTracePlane);
    const name = traceName(layer, style);
    let text = null;
    if (
      layer.interaction !== "none"
      && layer.hover_fields
      && layer.hover_fields.includes("name")
      && table.getChild("name")
    ) {
      const names = column(table, "name", false);
      const x = coordinates.x;
      text = [];
      let cursor = 0;
      for (let index = 0; index < x.length; index += 1) {
        if (Number.isNaN(x[index])) {
          text.push(null);
          continue;
        }
        text.push(escapePlotlyText(names[cursor]));
        cursor += 1;
      }
    }
    const trace = {
      type,
      x: coordinates.x,
      y: coordinates.y,
      mode: "lines",
      line: { ...lineStyle(style, strokePixelScale), simplify: false },
      // Plotly's default Douglas-Peucker simplification visibly turns dense
      // horizon/optic clip borders into polygons.  Scene coordinates are
      // already clipped and encoded within the manifest's pixel error budget,
      // so preserve every recorded vertex here.
      opacity: style.alpha === undefined ? 1 : Number(style.alpha),
      hoverinfo: text ? "text" : "none",
      text,
      name,
      legendgroup: layer.group_id,
      showlegend: Boolean(name),
    };
    if (type === "scatter") trace.zorder = Number(layer.zorder);
    return trace;
  }

  function polygonTrace(layer, table, style, strokeScale = 1) {
    const x = decodeCoordinate(layer, table, "x");
    const y = decodeCoordinate(layer, table, "y");
    const polygonIds = column(table, "polygon_id");
    const ringIds = column(table, "ring_id");
    const vertexIndices = column(table, "vertex_index");
    const polygons = new Map();
    for (let index = 0; index < polygonIds.length; index += 1) {
      let rings = polygons.get(polygonIds[index]);
      if (!rings) { rings = new Map(); polygons.set(polygonIds[index], rings); }
      let points = rings.get(ringIds[index]);
      if (!points) { points = []; rings.set(ringIds[index], points); }
      points.push({ x: x[index], y: y[index], vertex: vertexIndices[index] });
    }
    const orderedPolygons = [...polygons.entries()]
      .sort(([left], [right]) => Number(left) - Number(right))
      .map(([polygonId, rings]) => ({
        polygonId,
        rings: [...rings.entries()]
          .sort(([left], [right]) => Number(left) - Number(right))
          .map(([ringId, points], ringIndex) => {
            const ordered = points.sort((left, right) => Number(left.vertex) - Number(right.vertex));
            const area = ordered.reduce((sum, point, index) => {
              const next = ordered[(index + 1) % ordered.length];
              return sum + point.x * next.y - next.x * point.y;
            }, 0) / 2;
            const wantsPositive = ringIndex === 0;
            return {
              ringId,
              points: area !== 0 && (area > 0) !== wantsPositive ? [...ordered].reverse() : ordered,
            };
          }),
      }));
    const [xref, yref] = coordinateRefs(layer, style);
    if (xref !== "x" || yref !== "y") {
      // Keep axes-domain and paper-space polygons aligned with the static Plotly
      // adapter: "x domain"/"y domain" map the axes area, and x3/y3 map paper.
      const shapeXref = xref === "paper" ? "x3" : xref;
      const shapeYref = yref === "paper" ? "y3" : yref;
      const shapes = [];
      for (const polygon of orderedPolygons) {
        let path = "";
        for (const ring of polygon.rings) {
          if (ring.points.length >= 3) path += ` M ${ring.points.map((point) => `${point.x},${point.y}`).join(" L ")} Z`;
        }
        if (path) shapes.push({
          type: "path", path: path.trim(), xref: shapeXref, yref: shapeYref, fillrule: "evenodd",
          fillcolor: plotlyColor(style.fill_color, "rgba(0,0,0,0)"),
          line: { ...lineStyle(style, strokeScale), color: plotlyColor(style.edge_color, "rgba(0,0,0,0)") },
          opacity: style.alpha === undefined ? 1 : Number(style.alpha),
        });
      }
      const trace = hiddenLayerTrace(layer);
      layoutEffects.set(trace, { shapes });
      return trace;
    }
    const pointCount = orderedPolygons.reduce((total, polygon) =>
      total + polygon.rings.reduce((ringTotal, ring) => ringTotal + ring.points.length + 2, 0), 0);
    const resultX = new Float64Array(pointCount);
    const resultY = new Float64Array(pointCount);
    let target = 0;
    for (const polygon of orderedPolygons) {
      for (const ring of polygon.rings) {
        for (const point of ring.points) {
          resultX[target] = point.x; resultY[target] = point.y; target += 1;
        }
        if (ring.points.length) {
          resultX[target] = ring.points[0].x; resultY[target] = ring.points[0].y; target += 1;
        }
        resultX[target] = NaN; resultY[target] = NaN; target += 1;
      }
    }
    return {
      type: "scatter",
      x: resultX.subarray(0, target),
      y: resultY.subarray(0, target),
      mode: "lines",
      fill: style.fill_color && String(style.fill_color).toLowerCase() !== "none" ? "toself" : undefined,
      fillcolor: plotlyColor(style.fill_color, "rgba(0,0,0,0)"),
      line: {
        ...lineStyle(style, strokeScale),
        color: plotlyColor(style.edge_color, "rgba(0,0,0,0)"),
        simplify: false,
      },
      opacity: style.alpha === undefined ? 1 : Number(style.alpha),
      hoverinfo: "none",
      showlegend: false,
      zorder: Number(layer.zorder),
    };
  }

  function textTrace(layer, table, scene, style) {
    const text = Array.from(column(table, "text"), safePlotlyText);
    const x = decodeCoordinate(layer, table, "x");
    const y = decodeCoordinate(layer, table, "y");
    const xOffset = column(table, "x_offset");
    const yOffset = column(table, "y_offset");
    const rotation = column(table, "rotation");
    const styleIds = column(table, "style_id");
    const variants = Array.isArray(style.text_styles) && style.text_styles.length
      ? style.text_styles
      : [style];
    const [xref, yref] = coordinateRefs(layer, style);
    const settings = arguments[4] || {};
    const pointScale = Number(settings.fontPixelScale || 1);
    const annotations = [];
    for (let index = 0; index < text.length; index += 1) {
      const variant = variants[styleIds[index]];
      if (!variant) throw new Error(`text style_id ${styleIds[index]} is not defined for layer ${layer.id}`);
      const horizontal = variant.ha || style.ha || "center";
      const vertical = variant.va || style.va || "center";
      const weight = String(variant.font_weight || style.font_weight || "normal").toLowerCase();
      annotations.push({
        x: x[index], y: (yref === "paper" && (layer.group_id === "horizon-bottom" || layer.group_id === "horizon-label" || style.footer)
          ? y[index] + Number(settings.footerOffset || 0) : y[index]), text: weight === "bold" ? `<b>${text[index]}</b>` : text[index],
        showarrow: false, xref, yref,
        xanchor: ["left", "right", "center"].includes(horizontal) ? horizontal : "center",
        yanchor: ({ center: "middle", baseline: "bottom", bottom: "bottom", top: "top" })[vertical] || "middle",
        xshift: Number(variant.xshift ?? style.xshift ?? xOffset[index]) * pointScale,
        yshift: Number(variant.yshift ?? style.yshift ?? yOffset[index]) * pointScale,
        textangle: Number(rotation[index]),
        font: {
          size: Math.max(8, Number(variant.font_size || style.font_size || 12) * pointScale),
          color: variant.font_color || style.font_color || "#ffffff",
          family: plotlyFontFamily(variant.font_name || style.font_name, weight),
        },
        opacity: Number(variant.font_alpha ?? style.font_alpha ?? style.alpha ?? 1),
      });
      const strokeColor = variant.stroke_color || style.stroke_color || null;
      const strokeWidth = Number(variant.stroke_width ?? style.stroke_width ?? 0) * pointScale;
      if (strokeColor && strokeWidth > 0) {
        textStrokeByAnnotation.set(annotations[annotations.length - 1], { color: strokeColor, width: strokeWidth });
      }
    }
    const trace = hiddenLayerTrace(layer);
    layoutEffects.set(trace, { annotations });
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
    const rawBounds = [bounds.x_min, bounds.x_max, bounds.y_min, bounds.y_max];
    if (rawBounds.some((value) => typeof value !== "number" || !Number.isFinite(value))) return null;
    const [xMin, xMax, yMin, yMax] = rawBounds;
    const direction = style.direction || "linear";
    if (!["linear", "radial", "mollweide"].includes(direction)) {
      throw new Error(`unsupported gradient direction: ${direction}`);
    }
    if (!Array.isArray(style.color_stops) || style.color_stops.length < 2) {
      throw new Error(`gradient layer ${layer.id} requires at least two color stops`);
    }
    const clip = clipFor(layer, scene);
    const radial = direction === "radial";
    const rows = direction === "linear" ? (clip ? 512 : 2000) : 512;
    const columns = direction === "linear" ? (clip ? 512 : 2) : 512;
    const x = new Float64Array(columns), y = new Float64Array(rows);
    for (let index = 0; index < columns; index += 1) x[index] = xMin + (xMax - xMin) * index / Math.max(1, columns - 1);
    for (let index = 0; index < rows; index += 1) y[index] = yMin + (yMax - yMin) * index / Math.max(1, rows - 1);
    const z = new Array(rows);
    for (let row = 0; row < rows; row += 1) {
      // Plotly heatmaps expect an ordinary two-dimensional array. Nested
      // typed rows render, but their colorscale interpolation can collapse
      // into visible hard bands (most obvious on radial optic gradients).
      z[row] = new Array(columns);
      for (let col = 0; col < columns; col += 1) {
        let value;
        let valid = true;
        if (radial) {
          const clipXs = clip ? clip.points.map((point) => Number(point[0])) : [xMin, xMax];
          const clipYs = clip ? clip.points.map((point) => Number(point[1])) : [yMin, yMax];
          const clipXMin = Math.min(...clipXs), clipXMax = Math.max(...clipXs);
          const clipYMin = Math.min(...clipYs), clipYMax = Math.max(...clipYs);
          const defaultCenter = [(clipXMin + clipXMax) / 2, (clipYMin + clipYMax) / 2];
          const defaultRadius = clip
            ? Math.min(clipXMax - clipXMin, clipYMax - clipYMin) / 2
            : Math.max(
              Math.abs(xMax - defaultCenter[0]), Math.abs(yMax - defaultCenter[1]),
            );
          const center = style.center || defaultCenter;
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

  function infoTableTrace(layer, table, style, scene, settings) {
    const columns = Array.from(column(table, "column"), escapePlotlyText);
    const values = Array.from(column(table, "value"), escapePlotlyText);
    const widths = Array.from(column(table, "width"), (value) => Math.max(0, Number(value)));
    const count = Math.min(columns.length, values.length);
    if (!count) return hiddenLayerTrace(layer);
    const total = widths.slice(0, count).reduce((sum, value) => sum + value, 0);
    const normalized = widths.slice(0, count).map((value) => total > 0 ? value / total : 1 / count);
    const lineColor = style.line_color || "#999999";
    const background = style.background_color || (scene.viewport && scene.viewport.paper_background) || "#ffffff";
    const fontScale = (settings && settings.fontPixelScale) || 1;
    const baseSize = Number(style.font_size || 12);
    const headerSize = Math.max(11, baseSize * 1.2 * fontScale);
    const valueSize = Math.max(10, baseSize * fontScale);
    const shapes = [{ type: "rect", xref: "paper", yref: "paper", x0: 0, x1: 1, y0: -0.09, y1: -0.01, line: { color: lineColor, width: 1 }, fillcolor: background, layer: "above" }];
    const annotations = [];
    let left = 0;
    for (let index = 0; index < count; index += 1) {
      const right = left + normalized[index];
      if (index) shapes.push({ type: "line", xref: "paper", yref: "paper", x0: left, x1: left, y0: -0.09, y1: -0.01, line: { color: lineColor, width: 1 }, layer: "above" });
      for (const [text, y, size] of [[`<b>${columns[index]}</b>`, -0.03, headerSize], [values[index], -0.068, valueSize]]) {
        annotations.push({ x: (left + right) / 2, y, xref: "paper", yref: "paper", text, showarrow: false, xanchor: "center", yanchor: "middle", font: { size, color: style.font_color || "#111111", family: style.font_name || "Inter, Arial, sans-serif" }, opacity: Number(style.font_alpha ?? 1) });
      }
      left = right;
    }
    const trace = hiddenLayerTrace(layer);
    layoutEffects.set(trace, { shapes, annotations, marginBottom: 105 });
    return trace;
  }

  function layerToPlotlyTrace(layer, table, scene, options) {
    if (!KIND_TYPES[layer.kind]) throw new Error(`unsupported Scene kind: ${layer.kind}`);
    const settings = options || {};
    const style = styleFor(layer, scene);
    clipFor(layer, scene);
    let trace;
    if (layer.kind === "scatter") trace = scatterTrace(layer, table, scene, style, settings.forceSvgTracePlane, settings.strokePixelScale, settings.markerScale);
    else if (layer.kind === "line" || layer.kind === "line_collection") trace = lineTrace(layer, table, style, settings.forceSvgTracePlane, settings.strokePixelScale);
    else if (layer.kind === "polygon") trace = polygonTrace(layer, table, style, settings.strokePixelScale);
    else if (layer.kind === "text") trace = textTrace(layer, table, scene, style, settings);
    else if (layer.kind === "gradient") trace = gradientTrace(layer, scene, style) || hiddenLayerTrace(layer);
    else trace = infoTableTrace(layer, table, style, scene, settings);
    const [xref, yref] = coordinateRefs(layer, style);
    if (["scatter", "line", "line_collection", "polygon"].includes(layer.kind)
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

  function layerToPlotlyTraces(layer, table, scene, options) {
    const settings = options || {};
    let traces;
    if (layer.kind === "scatter") {
      const style = styleFor(layer, scene);
      clipFor(layer, scene);
      const [xref, yref] = coordinateRefs(layer, style);
      traces = densePaletteScatterTraces(
        layer, table, scene, style, settings.forceSvgTracePlane, settings.strokePixelScale, settings.markerScale,
      ).map((trace) => {
        if (xref !== "x" || yref !== "y") {
          trace.xaxis = xref === "paper" ? "x3" : "x2";
          trace.yaxis = yref === "paper" ? "y3" : "y2";
          trace.cliponaxis = false;
        }
        trace.meta = {
          ...(trace.meta || {}), starplot_layer_id: layer.id,
          starplot_zorder: layer.zorder, xref, yref, clip_id: layer.clip_id || null,
        };
        return trace;
      });
    } else {
      traces = [layerToPlotlyTrace(layer, table, scene, options)];
    }

    // Normalize legend visibility so it matches the Python adapter: a named
    // trace appears once and only if its name is in the allowed label list.
    const viewport = scene.viewport || {};
    const legendLabels = viewport.legend_labels || [];
    const shown = settings.shownLegendNames;
    const allowLegend = Boolean(viewport.show_legend || viewport.showlegend);
    for (const trace of traces) {
      if (!allowLegend || !trace.showlegend) {
        trace.showlegend = false;
        continue;
      }
      const name = trace.name || "";
      if (!name || !legendLabels.includes(name) || (shown && shown.has(name))) {
        trace.showlegend = false;
      } else if (shown) {
        shown.add(name);
      }
    }
    return traces;
  }

  function placeholder(layer, forceSvgTracePlane) {
    return {
      type: traceTypeForLayer(layer, forceSvgTracePlane),
      visible: false,
      meta: { starplot_layer_id: layer.id, starplot_zorder: layer.zorder },
    };
  }

  function sceneLayout(scene, options = {}) {
    const viewport = scene.viewport || {};
    const bounds = viewport.data_bounds || {};
    const clips = Array.isArray(scene.clips)
      ? scene.clips
      : Object.entries(scene.clips || {}).map(([id, value]) => ({ id, ...value }));
    const plotClip = clips.find((c) => c.id === "plot");
    const axesBg = viewport.axes_background || "#ffffff";
    const shapes = [];
    const gradientOwnsPlotBackground = scene.layers.some((layer) =>
      layer.kind === "gradient" && layer.clip_id === "plot",
    );
    if (!gradientOwnsPlotBackground && plotClip && plotClip.points && plotClip.points.length >= 3) {
      // For non-rectangular clips, make the rectangular axes background
      // transparent and fill only the clip region with the axes color.  A
      // clipped gradient already paints that region.  Using a Plotly layout
      // shape underneath it creates a visibly faceted dark rim in circular
      // optic views, so do not duplicate the background in that case.
      const pts = plotClip.points;
      const ringPath = pts.map((p, i) =>
        (i === 0 ? "M" : "L") + Number(p[0]) + "," + Number(p[1])
      ).join(" ") + " Z";
      shapes.push({
        type: "path", path: ringPath, xref: "x", yref: "y",
        fillcolor: axesBg, line: { width: 0 }, layer: "below",
      });
    }
    return {
      // Matplotlib's transparent figure exports are composited against the
      // comparison page's white canvas.  Do the same instead of painting the
      // style's dark figure colour outside the projected axes.
      paper_bgcolor: viewport.transparent ? "#ffffff" : (viewport.paper_background || "#ffffff"),
      plot_bgcolor: plotClip ? "rgba(0,0,0,0)" : axesBg,
      xaxis: {
        range: bounds.x_min === undefined ? undefined : [bounds.x_min, bounds.x_max],
        showgrid: false, zeroline: false, scaleanchor: "y", scaleratio: 1, constrain: "domain", showticklabels: false, showline: false,
      },
      yaxis: {
        range: bounds.y_min === undefined ? undefined : [bounds.y_min, bounds.y_max],
        showgrid: false, zeroline: false, constrain: "domain", showticklabels: false, showline: false,
        domain: options.yDomain,
      },
      xaxis2: { range: [0, 1], overlaying: "x", visible: false, fixedrange: true },
      yaxis2: { range: [0, 1], overlaying: "y", visible: false, fixedrange: true },
      xaxis3: { range: [0, 1], domain: [0, 1], overlaying: "x", visible: false, fixedrange: true },
      yaxis3: { range: [0, 1], domain: [0, 1], overlaying: "y", visible: false, fixedrange: true },
      showlegend: Boolean(viewport.show_legend || viewport.showlegend),
      margin: { autoexpand: false, ...(options.margin || viewport.margin || { l: 10, r: 10, t: 10, b: 10 }) },
      annotations: [],
      shapes,
    };
  }

  function _estimatedResponsiveAxesWidth(viewport, margin, target, yDomain) {
    if (!target || typeof target.getBoundingClientRect !== "function") return null;
    const rect = target.getBoundingClientRect();
    const availableWidth = Number(rect.width) - Number(margin.l || 0) - Number(margin.r || 0);
    const availableHeight = Number(rect.height) - Number(margin.t || 0) - Number(margin.b || 0);
    if (!(availableWidth > 0) || !(availableHeight > 0)) return null;
    const bounds = viewport.data_bounds || {};
    const xRange = Math.abs(Number(bounds.x_max) - Number(bounds.x_min));
    const yRange = Math.abs(Number(bounds.y_max) - Number(bounds.y_min));
    if (!(xRange > 0) || !(yRange > 0)) return availableWidth;
    const domain = yDomain || [0, 1];
    const domainHeight = availableHeight * Math.abs(Number(domain[1]) - Number(domain[0]));
    // xaxis is scale-anchored to y with scaleratio=1.  Plotly therefore uses
    // the smaller of the available paper width and the width implied by the
    // y-axis pixel scale.  Predict that width before constructing dense marker
    // arrays so the normal render does not resend them in a corrective restyle.
    return Math.min(availableWidth, domainHeight * xRange / yRange);
  }

  function renderingMetrics(scene, tables, target) {
    const viewport = scene.viewport || {};
    const hasRecordedViewportMargin = Boolean(viewport.margin);
    let footerOffset = 0;
    for (const layer of scene.layers) {
      if (layer.group_id !== "horizon-bottom" || !tables.has(layer.id)) continue;
      const table = tables.get(layer.id);
      const y = decodeCoordinate(layer, table, "y");
      for (const value of y) footerOffset = Math.max(footerOffset, -Number(value));
    }
    footerOffset = Math.max(0, footerOffset);
    const hasGridLabels = scene.layers.some((layer) => layer.group_id === "gridlines-label");
    const sideMargin = footerOffset && hasGridLabels ? 50 : 10;
    const dpi = Number(viewport.dpi || 100);
    // The Scene's target_axes_width is the Matplotlib source width by default
    // (the export does not know the browser container size).  For responsive
    // rendering, infer Plotly's scale-anchored axes width from the container,
    // margins, and data aspect ratio so fonts, strokes, and markers start at
    // the rendered scale instead of requiring a dense corrective restyle.
    const margin = footerOffset && !hasRecordedViewportMargin
      ? { l: sideMargin, r: sideMargin, t: 30, b: 10, autoexpand: false }
      : (viewport.margin || { l: 10, r: 10, t: 10, b: 10, autoexpand: false });
    const yDomain = footerOffset && !hasRecordedViewportMargin
      ? [footerOffset, 1]
      : undefined;
    const sourceAxesWidth = Number(viewport.source_axes_width || viewport.reference_width || 1);
    const compiledTargetAxesWidth = Number(viewport.target_axes_width || sourceAxesWidth);
    let targetAxesWidth = compiledTargetAxesWidth;
    // When target equals source (the common responsive case where the export
    // does not know the browser container size), measure the actual container
    // so fonts/strokes/markers scale to the rendered chart.  Use a relative
    // epsilon comparison because the two manifest values may differ by
    // floating-point rounding while still representing the same width.
    const targetsEqualSource = Math.abs(targetAxesWidth - sourceAxesWidth)
      <= Math.max(1e-6, 1e-6 * Math.max(Math.abs(targetAxesWidth), Math.abs(sourceAxesWidth)));
    if (!targetAxesWidth || targetsEqualSource) {
      const estimatedAxesWidth = _estimatedResponsiveAxesWidth(viewport, margin, target, yDomain);
      if (estimatedAxesWidth > 0) targetAxesWidth = estimatedAxesWidth;
    }
    const widthScale = (targetAxesWidth / sourceAxesWidth) || 1;
    // Scene text originates in a high-resolution Matplotlib canvas.  Convert
    // points to source pixels, then scale to the compiled browser viewport.
    const fontPixelScale = (dpi / 72) * widthScale;
    return {
      footerOffset: hasRecordedViewportMargin ? 0 : footerOffset,
      fontPixelScale,
      widthScale,
      margin,
      // Strokes and text are both specified in Matplotlib points.  The
      // source-to-viewport ratio is already included in fontPixelScale.
      strokePixelScale: fontPixelScale,
      // Marker sizes are calibrated to source axes pixels by the Scene
      // compiler, so they only need the source-to-viewport ratio (no
      // point-to-pixel conversion) to render at the compiled width.
      // Scatter sizes were already calibrated by SceneCompiler for
      // compiledTargetAxesWidth.  Scale from that compiled width to the
      // current rendered axes width; using sourceAxesWidth here applies the
      // explicit export-width ratio twice.
      markerScale: (targetAxesWidth / compiledTargetAxesWidth) || 1,
      yDomain,
    };
  }

  function restyleUpdate(trace) {
    const update = {};
    for (const [name, value] of Object.entries(trace)) update[name] = [value];
    update.visible = [trace.visible === false ? false : true];
    return update;
  }

  function assertNotAborted(signal) {
    if (signal && signal.aborted) {
      const error = new Error("The operation was aborted");
      error.name = "AbortError";
      throw signal.reason || error;
    }
  }

  function afterFinalPaint() {
    const frame = typeof global.requestAnimationFrame === "function"
      ? global.requestAnimationFrame.bind(global)
      : (callback) => callback();
    return new Promise((resolve) => frame(() => frame(resolve)));
  }

  function polygonTableHasHoles(table) {
    const polygonIds = column(table, "polygon_id");
    const ringIds = column(table, "ring_id");
    const firstRingByPolygon = new Map();
    for (let index = 0; index < polygonIds.length; index += 1) {
      const polygonId = polygonIds[index];
      if (!firstRingByPolygon.has(polygonId)) firstRingByPolygon.set(polygonId, ringIds[index]);
      else if (firstRingByPolygon.get(polygonId) !== ringIds[index]) return true;
    }
    return false;
  }

  function needsSvgZorderPlane(slots) {
    const glLayers = slots.filter((layer) => traceTypeForLayer(layer, false) === "scattergl");
    if (!glLayers.length) return false;
    // Plotly puts WebGL canvases on a separate paint plane.  A chart mixing
    // them with ordinary SVG geometry can hide SVG layers regardless of Scene
    // zorder (for example an optic-FOV circle below stars).  For charts small
    // enough for SVG, preserve the canonical one-plane ordering instead.
    const hasSvgGeometry = slots.some((layer) => ["scatter", "line", "polygon"].includes(layer.kind)
      && traceTypeForLayer(layer, false) !== "scattergl");
    const largestGlLayer = Math.max(...glLayers.map((layer) => Number(layer.row_count || 0)));
    return hasSvgGeometry && largestGlLayer <= MAX_SVG_ZORDER_POINTS;
  }

  function normalizeSvgZorders(slots, traces, enabled) {
    if (!enabled) return;
    // Plotly interprets a negative SVG zorder as a request to paint beneath
    // its canvas traces.  Scene uses large negative values for a gradient's
    // background, then grid/FOV geometry above it.  Re-rank only the SVG
    // plane so its relative Scene ordering survives without falling behind
    // the gradient canvas.
    let zorder = 0;
    for (const layer of slots) {
      const layerTraces = traces.get(layer.id) || [];
      for (const trace of layerTraces) if (trace.type === "scatter") trace.zorder = zorder;
      zorder += 1;
    }
  }

  // -- Scale-correction helpers ------------------------------------------------
  // Plotly's scaleanchor constrains the axes domain to keep axes square inside
  // a non-square container.  renderingMetrics uses the container width as a
  // proxy for the axes width, which overestimates for circular projections.
  // After Plotly.react, we measure the actual axes domain and restyle
  // fonts/markers/strokes to the corrected scale.  The same logic runs on
  // window resize via a debounced handler.

  function _actualAxesSize(fullLayout) {
    if (!fullLayout || !fullLayout.xaxis || !fullLayout.width) return null;
    const plotAreaWidth = fullLayout.width - (fullLayout.margin.l || 0) - (fullLayout.margin.r || 0);
    const plotAreaHeight = fullLayout.height - (fullLayout.margin.t || 0) - (fullLayout.margin.b || 0);
    const xDom = fullLayout.xaxis.domain || [0, 1];
    const yDom = fullLayout.yaxis.domain || [0, 1];
    const axesW = plotAreaWidth * (xDom[1] - xDom[0]);
    const axesH = plotAreaHeight * (yDom[1] - yDom[0]);
    return axesW;
  }

  function _collectTextStrokes(layout, orderedEffects) {
    // Build an array of { color, width } parallel to layout.annotations so
    // we can re-apply strokes after restyle without relying on the original
    // annotation object identity (which is lost when relayout replaces them).
    const strokes = new Array((layout.annotations || []).length).fill(null);
    let offset = 0;
    for (const effects of orderedEffects) {
      const anns = effects.annotations || [];
      for (let i = 0; i < anns.length; i++) {
        const stroke = textStrokeByAnnotation.get(anns[i]);
        if (stroke) strokes[offset + i] = stroke;
      }
      offset += anns.length;
    }
    return strokes;
  }

  function _polygonShapeIndices(layout, orderedEffects) {
    // Return indices into layout.shapes that came from polygon effects (so
    // we can relayout their line.width on scale correction).
    const indices = [];
    let offset = layout.shapes.length - orderedEffects.reduce(
      (sum, e) => sum + (e.shapes || []).length, 0,
    );
    for (const effects of orderedEffects) {
      const shapes = effects.shapes || [];
      for (let i = 0; i < shapes.length; i++) {
        if (shapes[i].line && typeof shapes[i].line.width === "number") {
          indices.push(offset + i);
        }
      }
      offset += shapes.length;
    }
    return indices;
  }

  function _applyAnnotationStrokes(target, correctionState) {
    const { layout, textStrokes, correctedFontPixelScale, metrics } = correctionState;
    if (!textStrokes || !textStrokes.length) return;
    const scaleRatio = correctedFontPixelScale != null && metrics.fontPixelScale > 0
      ? correctedFontPixelScale / metrics.fontPixelScale
      : 1;
    const nodes = target.querySelectorAll(".annotation-text");
    nodes.forEach((node, index) => {
      const stroke = textStrokes[index];
      if (!stroke || !stroke.color || stroke.width <= 0) return;
      node.style.stroke = stroke.color;
      node.style.strokeWidth = `${stroke.width * scaleRatio}px`;
      node.style.paintOrder = "stroke fill";
    });
  }

  async function _applyScaleCorrection(target, state, Plotly) {
    const { scene, slots, traces, layout, metrics } = state;
    const fullLayout = target._fullLayout;
    const actualAxes = _actualAxesSize(fullLayout);
    if (actualAxes == null || actualAxes <= 0) {
      state.correctedFontPixelScale = metrics.fontPixelScale;
      return;
    }
    const sourceAxesWidth = Number(
      scene.viewport.source_axes_width || scene.viewport.reference_width || 1,
    );
    const compiledTargetAxesWidth = Number(
      scene.viewport.target_axes_width || sourceAxesWidth,
    );
    const correctedWidthScale = actualAxes / sourceAxesWidth;
    state.correctedWidthScale = correctedWidthScale;
    const dpi = Number(scene.viewport.dpi || 100);
    const correctedFontPixelScale = (dpi / 72) * correctedWidthScale;
    state.correctedFontPixelScale = correctedFontPixelScale;
    const traceList = state.plotlyTraces
      || slots.flatMap((layer) => traces.get(layer.id) || []);
    if (!state.scaleBaseline) {
      state.scaleBaseline = {
        annotations: (layout.annotations || []).map((annotation) => ({
          ...annotation, font: { ...(annotation.font || {}) },
        })),
        lineWidths: traceList.map((trace) =>
          trace.line && typeof trace.line.width === "number"
            ? Number(trace.line.width)
            : null),
        polygonShapeWidths: (state.polygonShapeIndices || []).map((index) => {
          const shape = layout.shapes[index];
          return shape && shape.line && typeof shape.line.width === "number"
            ? Number(shape.line.width)
            : null;
        }),
      };
    }
    if (state.appliedWidthScale === undefined) state.appliedWidthScale = metrics.widthScale;
    if (Math.abs(correctedWidthScale - state.appliedWidthScale) <= 0.01) return;
    // Restyle marker sizes
    const scatterIndices = traceList
      .map((t, i) => (t.marker && t.marker.size ? i : -1))
      .filter((i) => i >= 0);
    if (scatterIndices.length) {
      const opacityUpdate = [];
      const sizeUpdate = scatterIndices.map((i) => {
        const trace = traceList[i];
        const source = (state.markerSources && state.markerSources.get(trace))
          || markerSourceByTrace.get(trace);
        const sizes = source ? source.size : trace.marker.size;
        const newSizes = new (sizes.constructor || Array)(sizes.length);
        const newOpacity = source && source.webgl
          ? new (source.opacity.constructor || Array)(source.opacity.length)
          : null;
        for (let j = 0; j < sizes.length; j += 1) {
          const scaled = source
            ? sizes[j] * (actualAxes / compiledTargetAxesWidth)
            : sizes[j] / metrics.markerScale * correctedWidthScale;
          newSizes[j] = Math.max(
            scaled, 1,
          );
          if (newOpacity) {
            const coverage = Math.min(1, 2.0 * scaled * scaled);
            newOpacity[j] = source.opacity[j] * coverage;
          }
        }
        opacityUpdate.push(newOpacity);
        return newSizes;
      });
      const update = { "marker.size": sizeUpdate };
      if (opacityUpdate.some(Boolean)) {
        update["marker.opacity"] = opacityUpdate.map((value, index) =>
          value || traceList[scatterIndices[index]].marker.opacity);
      }
      await Plotly.restyle(target, update, scatterIndices);
    }
    // Restyle line widths (line, polygon-as-trace)
    const lineWidthIndices = state.scaleBaseline.lineWidths
      .map((width, index) => (width == null ? -1 : index))
      .filter((i) => i >= 0);
    if (lineWidthIndices.length) {
      const widthUpdate = lineWidthIndices.map((i) => {
        const w = state.scaleBaseline.lineWidths[i];
        return Math.max(0.25, w / metrics.strokePixelScale * correctedFontPixelScale);
      });
      await Plotly.restyle(target, { "line.width": widthUpdate }, lineWidthIndices);
    }
    // Relayout polygon shape line widths (polygon-as-shape path)
    if (state.polygonShapeIndices && state.polygonShapeIndices.length) {
      const shapeWidthUpdate = state.polygonShapeIndices.map((_idx, index) => {
        const w = state.scaleBaseline.polygonShapeWidths[index];
        if (w == null) return undefined;
        return Math.max(0.25, w / metrics.strokePixelScale * correctedFontPixelScale);
      });
      const relayoutUpdate = {};
      state.polygonShapeIndices.forEach((idx, i) => {
        if (shapeWidthUpdate[i] !== undefined) {
          relayoutUpdate[`shapes[${idx}].line.width`] = shapeWidthUpdate[i];
        }
      });
      await Plotly.relayout(target, relayoutUpdate);
    }
    // Relayout annotation font sizes and shifts
    if (layout.annotations && layout.annotations.length) {
      const baseAnnotations = state.scaleBaseline.annotations;
      if (baseAnnotations.length) {
        const newAnnotations = baseAnnotations.map((ann) => ({
          ...ann,
          font: {
            ...ann.font,
            size: Math.max(8, Number(ann.font.size) / metrics.fontPixelScale * correctedFontPixelScale),
          },
          xshift: Number(ann.xshift || 0) / metrics.fontPixelScale * correctedFontPixelScale,
          yshift: Number(ann.yshift || 0) / metrics.fontPixelScale * correctedFontPixelScale,
        }));
        await Plotly.relayout(target, { annotations: newAnnotations });
      }
    }
    state.appliedWidthScale = correctedWidthScale;
  }

  function _ensureResizeHandler(target, state, Plotly) {
    if (target._starplotResizeHandler) return;
    if (typeof window === "undefined" || typeof window.addEventListener !== "function") return;
    let timer = null;
    const handler = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(async () => {
        timer = null;
        // Re-measure and re-correct after Plotly's responsive resize settles.
        await _applyScaleCorrection(target, state, Plotly);
        _applyAnnotationStrokes(target, state);
      }, 150);
    };
    window.addEventListener("resize", handler);
    target._starplotResizeHandler = handler;
  }

  async function renderScene(target, source, options) {
    const settings = options || {};
    const Plotly = settings.Plotly || global.Plotly;
    if (!Plotly || typeof Plotly.react !== "function" || typeof Plotly.restyle !== "function" || typeof Plotly.relayout !== "function") {
      throw new Error("Plotly 3.x must be loaded before rendering a Starplot Scene");
    }
    if (!source || typeof source.loadManifest !== "function" || typeof source.loadLayer !== "function") {
      throw new Error("source must implement the SceneSource contract");
    }
    assertNotAborted(settings.signal);
    const scene = await source.loadManifest(settings.signal);
    assertNotAborted(settings.signal);
    const slots = [...scene.layers].sort((left, right) =>
      Number(left.zorder) - Number(right.zorder) || String(left.id).localeCompare(String(right.id)));
    const loadOrder = [...scene.layers].sort((left, right) =>
      Number(left.load_priority) - Number(right.load_priority)
      || Number(left.zorder) - Number(right.zorder)
      || String(left.id).localeCompare(String(right.id)));
    const loaded = await Promise.all(loadOrder.map(async (layer) => {
      try {
        assertNotAborted(settings.signal);
        const table = await global.StarplotScene.collectLayerTable(
          source, layer, settings.request, settings.signal,
        );
        assertNotAborted(settings.signal);
        return { layer, table };
      } catch (error) {
        if (!layer.required && !(settings.signal && settings.signal.aborted)) {
          showLayerFailure(target, layer, error, () => renderScene(target, source, settings), true);
          return { layer, error };
        }
        if (!(settings.signal && settings.signal.aborted)) {
          showLayerFailure(target, layer, error, () => renderScene(target, source, settings), false);
        }
        return { layer, error, required: true };
      }
    }));
    assertNotAborted(settings.signal);
    const tableCache = new Map(loaded.filter((item) => item.table).map((item) => [item.layer.id, item.table]));
    const requiredFailure = loaded.find((item) => item.required);
    const mixedSvgZorderPlane = needsSvgZorderPlane(slots);
    const forceSvgTracePlane = mixedSvgZorderPlane || slots.some((layer) =>
      layer.kind === "polygon" && layer.coordinate_space === "data"
      && tableCache.has(layer.id) && polygonTableHasHoles(tableCache.get(layer.id)));
    const metrics = renderingMetrics(scene, tableCache, target);
    const shownLegendNames = new Set();
    const traces = new Map();
    const effectsById = new Map();
    for (const item of loaded) {
      if (!item.table) continue;
      const layerTraces = layerToPlotlyTraces(
        item.layer, item.table, scene,
        { ...metrics, forceSvgTracePlane, shownLegendNames },
      );
      traces.set(item.layer.id, layerTraces);
      const effects = layoutEffects.get(layerTraces[0]);
      if (effects) effectsById.set(item.layer.id, effects);
    }
    normalizeSvgZorders(slots, traces, mixedSvgZorderPlane);
    const orderedEffects = slots.map((layer) => effectsById.get(layer.id)).filter(Boolean);
    const layout = sceneLayout(scene, metrics);
    layout.annotations = orderedEffects.flatMap((item) => item.annotations || []);
    layout.shapes = [...layout.shapes, ...orderedEffects.flatMap((item) => item.shapes || [])];
    const marginBottom = Math.max(0, ...orderedEffects.map((item) => Number(item.marginBottom || 0)));
    if (marginBottom) layout.margin = { ...metrics.margin, b: Math.max(Number(metrics.margin.b || 10), marginBottom) };
    const plotlyTraces = slots.flatMap((layer) =>
      traces.get(layer.id) || [placeholder(layer, forceSvgTracePlane)]);
    const polygonShapeIndices = _polygonShapeIndices(layout, orderedEffects);
    const correctionState = {
      scene, slots, traces, plotlyTraces, layout, metrics,
      markerSources: new Map(slots.flatMap((layer) =>
        (traces.get(layer.id) || []).map((trace) => [trace, markerSourceByTrace.get(trace)]))
        .filter((entry) => entry[1])),
      textStrokes: _collectTextStrokes(layout, orderedEffects),
      polygonShapeIndices,
      scaleBaseline: {
        annotations: (layout.annotations || []).map((annotation) => ({
          ...annotation, font: { ...(annotation.font || {}) },
        })),
        lineWidths: plotlyTraces.map((trace) =>
          trace.line && typeof trace.line.width === "number"
            ? Number(trace.line.width)
            : null),
        polygonShapeWidths: polygonShapeIndices.map((index) => {
          const shape = layout.shapes[index];
          return shape && shape.line && typeof shape.line.width === "number"
            ? Number(shape.line.width)
            : null;
        }),
      },
    };
    await Plotly.react(target, plotlyTraces, layout,
      { responsive: true, ...settings.config });
    // Plotly calibrates the axes domain to keep scaleanchor axes square inside
    // the (possibly non-square) container.  The initial renderingMetrics used
    // the container width as a proxy for the axes width, which overestimates
    // the real axes width for circular projections.  Recompute the scale from
    // the actual axes domain and restyle when the correction is significant.
    // This also runs on window resize (see _applyScaleCorrection).
    await _applyScaleCorrection(target, correctionState, Plotly);
    // Debounced resize re-correction.  Plotly's responsive:true only resizes
    // the canvas; it does not recompute font/marker/stroke scales.
    _ensureResizeHandler(target, correctionState, Plotly);
    if (target && typeof target.querySelectorAll === "function") {
      _applyAnnotationStrokes(target, correctionState);
    }
    await afterFinalPaint();
    if (requiredFailure) throw requiredFailure.error;
    return target;
  }

  global.StarplotScene = Object.assign(global.StarplotScene || {}, {
    layerToPlotlyTrace,
    layerToPlotlyTraces,
    layerToPlotlyLayoutEffects(trace) { return layoutEffects.get(trace) || {}; },
    renderScene,
    traceTypeForLayer,
    escapePlotlyText,
    // Exposed for unit testing
    _actualAxesSize,
    _collectTextStrokes,
    _polygonShapeIndices,
    _applyScaleCorrection,
    _applyAnnotationStrokes,
  });
})(typeof window !== "undefined" ? window : globalThis);
