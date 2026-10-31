import type { InfillPattern, SliceSettings, SupportMode } from "./types";

export interface ParsedParameters {
  patch: Partial<SliceSettings>;
  fields: Array<keyof SliceSettings>;
  summaries: string[];
}

const PATTERNS: Array<{ pattern: InfillPattern; label: string; words: RegExp }> = [
  { pattern: "grid", label: "网格", words: /网格|grid/i },
  { pattern: "lines", label: "直线", words: /直线|linear|lines?/i },
  { pattern: "gyroid", label: "螺旋", words: /螺旋|gyroid/i },
  { pattern: "honeycomb", label: "蜂窝", words: /蜂窝|honeycomb/i },
  { pattern: "cubic", label: "立方体", words: /立方体|立体|3d\s*蜂窝|cubic/i },
];

const SUPPORT_LABELS: Record<SupportMode, string> = {
  off: "不生成支撑",
  tree_plate: "树状支撑（仅打印板生成）",
  tree_all: "树状支撑（全模型生成）",
  normal_plate: "普通支撑（仅打印板生成）",
  normal_all: "普通支撑（全模型生成）",
};

function parseNumber(text: string, expression: RegExp, min: number, max: number) {
  const match = text.match(expression);
  if (!match) return null;
  const value = Number.parseFloat(match[1]);
  if (!Number.isFinite(value) || value < min || value > max) return null;
  return value;
}

export function parseParameterCommand(text: string): ParsedParameters {
  const normalized = text.replace(/[，,、；;]/g, " ").replace(/\s+/g, " ").trim();
  const patch: Partial<SliceSettings> = {};
  const summaries: string[] = [];

  const layerHeight = parseNumber(
    normalized,
    /(?:层高|layer\s*height)\s*(?:调到|调成|改成|改为|设为|设成|设置成|用|是|为|=|:)?\s*(\d+(?:\.\d+)?)/i,
    0.04,
    1,
  );
  if (layerHeight !== null) {
    patch.layerHeight = layerHeight.toFixed(2);
    summaries.push(`层高 ${patch.layerHeight} mm`);
  }

  const infill = parseNumber(
    normalized,
    /(?:填充|密度|infill)\s*(?:调到|调成|改成|改为|设为|设成|用|是|为|=|:)?\s*(\d{1,3})\s*%?/i,
    0,
    100,
  );
  if (infill !== null) {
    patch.infill = String(Math.round(infill));
    summaries.push(`填充 ${patch.infill}%`);
  }

  const pattern = PATTERNS.find((candidate) => candidate.words.test(normalized));
  if (pattern) {
    patch.pattern = pattern.pattern;
    summaries.push(`填充图案 ${pattern.label}`);
  }

  const materialMatch = normalized.match(
    /(?:耗材|材料)?\s*(pla-cf|petg-cf|abs-gf|pla|petg|abs|tpu|pa-cf|pa|pc)/i,
  );
  if (materialMatch) {
    const materialNames: Record<string, string> = {
      "pla": "PLA",
      "petg": "PETG",
      "abs": "ABS",
      "tpu": "TPU",
      "pla-cf": "碳纤维PLA",
      "petg-cf": "碳纤维PETG",
      "abs-gf": "玻纤ABS",
      "pa": "PA（尼龙）",
      "pa-cf": "碳纤维PA（尼龙）",
      "pc": "PC",
    };
    patch.material = materialNames[materialMatch[1].toLowerCase()];
    summaries.push(patch.material);
  }

  const bedMatch = normalized.match(/(纹理钢板|冷却板|高温板|工程板)/);
  if (bedMatch) {
    const bedNames: Record<string, string> = {
      "纹理钢板": "Textured PEI Plate",
      "冷却板": "Cool Plate",
      "高温板": "High Temp Plate",
      "工程板": "Engineering Plate",
    };
    patch.bedType = bedNames[bedMatch[1]];
    summaries.push(bedMatch[1]);
  }

  let supportMode: SupportMode | null = null;
  if (/(?:不|无需|不要|关闭|关掉|去掉|没有)\s*(?:生成)?\s*支撑/.test(normalized)) {
    supportMode = "off";
  } else if (/普通支撑/.test(normalized)) {
    supportMode = /(?:全模型|全部|整机|整件)/.test(normalized)
      ? "normal_all"
      : "normal_plate";
  } else if (/支撑/.test(normalized)) {
    supportMode = /(?:全模型|全部|整机|整件)/.test(normalized)
      ? "tree_all"
      : "tree_plate";
  }
  if (supportMode) {
    patch.supportMode = supportMode;
    summaries.push(SUPPORT_LABELS[supportMode]);
  }

  if (/(?:不要|不用|关闭|关掉|取消)\s*(?:自动)?\s*(?:摆盘|排列|拼盘)/.test(normalized)) {
    patch.autoArrange = false;
    summaries.push("关闭自动排列");
  } else if (/(?:自动排列|自动摆盘|拼盘|拼一板|同盘|放一起)/.test(normalized)) {
    patch.autoArrange = true;
    summaries.push("自动排列");
  }

  if (/(?:最省空间|紧凑|密排|紧致)/.test(normalized)) {
    patch.tightPacking = true;
    summaries.push("最省空间");
  } else if (/(?:不要最省空间|普通摆盘|宽松)/.test(normalized)) {
    patch.tightPacking = false;
    summaries.push("普通摆盘");
  }

  if (/(?:不要|不用|关闭|关掉)\s*最少支撑/.test(normalized)) {
    patch.minSupport = false;
    summaries.push("关闭最少支撑");
  } else if (/(?:最少支撑|省支撑)/.test(normalized)) {
    patch.minSupport = true;
    summaries.push("最少支撑");
  }

  if (/(?:不要|不用|关闭|关掉|保留)\s*(?:自动)?\s*(?:定向|朝向|方向)/.test(normalized)) {
    patch.orientation = false;
    summaries.push("保留原朝向");
  } else if (/(?:自动定向|调整朝向|找稳定方向|稳定朝向)/.test(normalized)) {
    patch.orientation = true;
    summaries.push("自动定向");
  }

  if (/(?:不要|不用|关闭|关掉)\s*(?:隐藏)?\s*z\s*缝/i.test(normalized)) {
    patch.hideSeam = false;
    summaries.push("关闭 Z 缝优化");
  } else if (/(?:隐藏\s*z\s*缝|z\s*缝\s*隐藏|斜拼接缝)/i.test(normalized)) {
    patch.hideSeam = true;
    summaries.push("隐藏 Z 缝");
  }

  if (/(?:不要|不用|关闭|关掉)\s*(?:顶面)?\s*熨烫/.test(normalized)) {
    patch.topIroning = false;
    summaries.push("关闭顶面熨烫");
  } else if (/(?:顶面熨烫|熨烫)/.test(normalized)) {
    patch.topIroning = true;
    summaries.push("顶面熨烫");
  }

  const printerMatch = normalized.match(/\b(h2s|p1s|x1c|a1m|h2dp|p1p|p2s|x2d|x1e)\b/i);
  if (printerMatch) {
    const names: Record<string, string> = {
      h2s: "Bambu Lab H2S",
      p1s: "Bambu Lab P1S",
      x1c: "Bambu Lab X1 Carbon",
      a1m: "Bambu Lab A1 mini",
      h2dp: "Bambu Lab H2D Pro",
      p1p: "Bambu Lab P1P",
      p2s: "Bambu Lab P2S",
      x2d: "Bambu Lab X2D",
      x1e: "Bambu Lab X1E",
    };
    patch.printer = names[printerMatch[1].toLowerCase()];
    summaries.push(patch.printer);
  }

  const cloneMatch = normalized.match(/(?:克隆|复制|打)\s*(\d{1,3})\s*个?/);
  if (cloneMatch) {
    const count = Math.min(100, Math.max(1, Number(cloneMatch[1])));
    patch.clone = String(count);
    summaries.push(`克隆 ${count} 个`);
  }

  const colorsMatch = normalized.match(/(?:最多|上限)\s*(\d+)\s*色/);
  if (colorsMatch) {
    const count = Number(colorsMatch[1]);
    if ([1, 2, 4].includes(count)) {
      patch.maxColors = String(count);
      summaries.push(`单盘最多 ${count} 色`);
    }
  }

  if (/(?:仅|只).{0,4}(?:可编辑\s*3mf|3mf)/i.test(normalized)) {
    patch.outputMode = "3mf";
    summaries.push("仅生成可编辑 3MF");
  } else if (/(?:直接打印|打印\s*g-?code|可打印包)/i.test(normalized)) {
    patch.outputMode = "gcode";
    summaries.push("生成可打印 G-code 3MF");
  }

  return {
    patch,
    fields: Object.keys(patch) as Array<keyof SliceSettings>,
    summaries,
  };
}
