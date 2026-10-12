import type {
  EngineFormulaTemplate,
  FormulaPlaceholder,
} from '../../types/engine';
import type {
  ConditionGroup,
  ConditionLeaf,
  FormulaKind,
  LadderTier,
  PlanItemDraft,
  PlanItemParam,
} from '../../types/plan';

import dayjs from 'dayjs';

let seq = 1;

export const PLAN_PRESET_COLORS = [
  '#1677ff',
  '#52c41a',
  '#faad14',
  '#f5222d',
  '#722ed1',
  '#13c2c2',
  '#eb2f96',
  '#fa8c16',
  '#2f54eb',
  '#a0d911',
  '#08979c',
  '#cf1322',
];

export const COLOR_PRESETS = [
  { colors: PLAN_PRESET_COLORS, label: '常用色板' },
];

export const STAGE_ORDER = ['per_order', 'daily', 'period'] as const;

export const FIELD_GROUPS = [
  {
    label: '订单',
    names: [
      '配送距离',
      '商品重量',
      '订单金额',
      '下单时刻',
      '送达时刻',
      '配送时长',
      '订单状态',
    ],
  },
  {
    label: '日期与标记',
    names: [
      '日期',
      '星期',
      '是否节假日',
      '是否周末',
      '是否恶劣天气',
      '是否高温',
      '是否大促',
    ],
  },
  {
    label: '聚合',
    names: [
      '日单量',
      '日总单量',
      '日有效单量',
      '日逐单金额',
      '周期单量',
      '周期总单量',
      '周期有效单量',
      '方案期内单量',
      '周期天数',
      '方案生效天数',
      '出勤天数',
      '本期已计金额',
      '本期逐单金额',
      '本期手工奖',
      '本期手工惩',
    ],
  },
  {
    label: '骑手',
    names: ['用工类型', '工龄月数', '入职天数'],
  },
];

export const RANGE_OPERATORS = new Set([
  '不在区间内',
  '不在时段内',
  '在区间内',
  '在时段内',
]);

export const MULTI_OPERATORS = new Set(['不属于', '属于']);

export function nextItemKey() {
  seq += 1;
  return `item-${Date.now()}-${seq}`;
}

export function emptyGroup(logic: ConditionGroup['逻辑'] = '且'): ConditionGroup {
  return { 条件: [], 逻辑: logic };
}

export function isGroup(
  node: ConditionGroup | ConditionLeaf | null | undefined,
): node is ConditionGroup {
  return !!node && typeof node === 'object' && '逻辑' in node;
}

export function isLeaf(
  node: ConditionGroup | ConditionLeaf | null | undefined,
): node is ConditionLeaf {
  return !!node && typeof node === 'object' && !('逻辑' in node);
}

export function fromConditionJson(
  json: null | Record<string, unknown> | undefined,
): ConditionGroup {
  if (!json || Object.keys(json).length === 0) return emptyGroup();
  if ('逻辑' in json) return json as unknown as ConditionGroup;
  if ('字段' in json) return { 条件: [json as unknown as ConditionLeaf], 逻辑: '且' };
  return emptyGroup();
}

function sanitizeNode(
  node: ConditionGroup | ConditionLeaf,
): ConditionGroup | ConditionLeaf | null {
  if (isGroup(node)) {
    const children = node.条件
      .map((child) => sanitizeNode(child))
      .filter((child): child is ConditionGroup | ConditionLeaf => child !== null);
    if (children.length === 0) return null;
    return { 条件: children, 逻辑: node.逻辑 };
  }
  if (!node.字段 || !node.运算符) return null;
  return node;
}

export function toConditionJson(
  group: ConditionGroup | null | undefined,
): null | Record<string, unknown> {
  if (!group) return {};
  const clean = sanitizeNode(group);
  if (!clean || !isGroup(clean)) return {};
  return clean as unknown as Record<string, unknown>;
}

export function lastNaturalMonth(): [string, string] {
  const start = dayjs().subtract(1, 'month').startOf('month');
  return [start.format('YYYY-MM-DD'), start.endOf('month').format('YYYY-MM-DD')];
}

export function defaultFormula(kind: FormulaKind): Record<string, unknown> {
  if (kind === '固定金额') return { 类型: '固定金额', 金额: 2 };
  if (kind === '字段乘单价') {
    return { 类型: '字段乘单价', 单价: 0.8, 字段: '配送距离', 起算值: 0 };
  }
  if (kind === '阶梯') {
    return {
      类型: '阶梯',
      字段: '配送距离',
      模式: '全量落档',
      计价: '固定金额',
      档位: [
        { 上限: 3, 下限: 0, 值: 1 },
        { 上限: 5, 下限: 3, 值: 2 },
        { 上限: null, 下限: 5, 值: 3 },
      ] satisfies LadderTier[],
    };
  }
  return { 类型: '表达式', 表达式: '' };
}

export function formulaKindOf(
  json: null | Record<string, unknown> | undefined,
): FormulaKind {
  const kind = json?.类型;
  if (kind === '字段乘单价' || kind === '阶梯' || kind === '表达式') return kind;
  return '固定金额';
}

export function createDraftItem(stage = 'per_order'): PlanItemDraft {
  return {
    _key: nextItemKey(),
    condition_json: {},
    enabled: true,
    formula_json: defaultFormula('固定金额'),
    name: '新方案项',
    remark: '',
    sort_order: 0,
    stage,
    subject_id: 0,
  };
}

export function toDraftItems(items: PlanItemParam[]): PlanItemDraft[] {
  return items.map((item, index) => ({
    ...item,
    _key: nextItemKey(),
    sort_order: item.sort_order ?? index,
    subject_id: item.subject_id,
  }));
}

export function toSaveItems(items: PlanItemDraft[]): PlanItemParam[] {
  const grouped = STAGE_ORDER.flatMap((stage) =>
    items.filter((item) => item.stage === stage),
  );
  return grouped.map((item, index) => ({
    condition_json: toConditionJson(fromConditionJson(item.condition_json)),
    enabled: item.enabled,
    formula_json: item.formula_json ?? defaultFormula('固定金额'),
    name: item.name,
    remark: item.remark || null,
    sort_order: index,
    stage: item.stage,
    subject_id: item.subject_id,
  }));
}

const STAGE_RANK: Record<string, number> = {
  daily: 1,
  per_order: 0,
  period: 2,
};

const SHA256_K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

function rotr(value: number, bits: number) {
  return (value >>> bits) | (value << (32 - bits));
}

function sha256Hex(text: string) {
  const bytes = new TextEncoder().encode(text);
  const bitLen = bytes.length * 8;
  const padded = new Uint8Array((((bytes.length + 9 + 63) >> 6) << 6));
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 4, bitLen >>> 0);

  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;
  const words = new Uint32Array(64);

  for (let offset = 0; offset < padded.length; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      words[index] = view.getUint32(offset + index * 4);
    }
    for (let index = 16; index < 64; index += 1) {
      const w15 = words[index - 15] ?? 0;
      const w2 = words[index - 2] ?? 0;
      const s0 = rotr(w15, 7) ^ rotr(w15, 18) ^ (w15 >>> 3);
      const s1 = rotr(w2, 17) ^ rotr(w2, 19) ^ (w2 >>> 10);
      words[index] = ((words[index - 16] ?? 0) + s0 + (words[index - 7] ?? 0) + s1) >>> 0;
    }
    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;
    for (let index = 0; index < 64; index += 1) {
      const s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const temp1 = (h + s1 + ch + (SHA256_K[index] ?? 0) + (words[index] ?? 0)) >>> 0;
      const s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (s0 + maj) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }
    h0 = (h0 + a) >>> 0;
    h1 = (h1 + b) >>> 0;
    h2 = (h2 + c) >>> 0;
    h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0;
    h5 = (h5 + f) >>> 0;
    h6 = (h6 + g) >>> 0;
    h7 = (h7 + h) >>> 0;
  }

  return [h0, h1, h2, h3, h4, h5, h6, h7]
    .map((part) => part.toString(16).padStart(8, '0'))
    .join('');
}

function canonicalJson(value: unknown): string {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return Number.isFinite(value) ? JSON.stringify(value) : 'null';
  if (typeof value === 'string') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(',')}]`;
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record)
    .filter((key) => record[key] !== undefined)
    .sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(',')}}`;
}

export function canonicalItemsJson(
  items: Array<{
    condition_json?: unknown;
    enabled?: boolean;
    formula_json?: unknown;
    name?: unknown;
    sort_order?: number;
    stage?: unknown;
    subject_id?: unknown;
  }>,
) {
  const payload = [...items]
    .sort((left, right) => {
      const stageGap = (STAGE_RANK[String(left.stage)] ?? 9) - (STAGE_RANK[String(right.stage)] ?? 9);
      if (stageGap !== 0) return stageGap;
      return (Number(left.sort_order) || 0) - (Number(right.sort_order) || 0);
    })
    .map((item) => ({
      condition_json: item.condition_json ?? null,
      enabled: item.enabled !== false,
      formula_json: item.formula_json ?? null,
      name: item.name ?? null,
      sort_order: Number(item.sort_order) || 0,
      stage: item.stage ?? null,
      subject_id: item.subject_id ?? null,
    }));
  return canonicalJson(payload);
}

export function itemsHashOf(
  items: Array<{
    condition_json?: unknown;
    enabled?: boolean;
    formula_json?: unknown;
    name?: unknown;
    sort_order?: number;
    stage?: unknown;
    subject_id?: unknown;
  }>,
) {
  return sha256Hex(canonicalItemsJson(items));
}

export function emptyPlanItemsHash() {
  return itemsHashOf([]);
}

export function planItemsHash(items: PlanItemDraft[]) {
  return itemsHashOf(toSaveItems(items));
}

export function isPlanItemsDirty(items: PlanItemDraft[], savedHash?: null | string) {
  const current = planItemsHash(items);
  if (!savedHash) return current !== emptyPlanItemsHash();
  return current !== savedHash;
}

export const LADDER_MODE_PROGRESSIVE = '分段累进';
export const LADDER_PRICING_FIXED = '固定金额';
export const ILLEGAL_LADDER_MESSAGE = '分段累进模式仅支持按单价计价';

export function isIllegalLadderCombo(mode: unknown, pricing: unknown) {
  return mode === LADDER_MODE_PROGRESSIVE && pricing === LADDER_PRICING_FIXED;
}

export function isIllegalLadderFormula(formula: unknown) {
  if (!formula || typeof formula !== 'object') return false;
  const record = formula as Record<string, unknown>;
  return record['类型'] === '阶梯' && isIllegalLadderCombo(record['模式'], record['计价']);
}

export function ladderModeDisabled(pricing: unknown, mode: string) {
  return mode === LADDER_MODE_PROGRESSIVE && pricing === LADDER_PRICING_FIXED;
}

export function ladderPricingDisabled(mode: unknown, pricing: string) {
  return pricing === LADDER_PRICING_FIXED && mode === LADDER_MODE_PROGRESSIVE;
}

export const UNSAVED_PLAN_LEAVE_MESSAGE = '方案项尚未保存，离开后本次修改会丢失';

const ACCRUED_AMOUNT_FIELD = '本期已计金额';

const PY_KEYWORDS = new Set([
  'False',
  'None',
  'True',
  'and',
  'as',
  'assert',
  'async',
  'await',
  'break',
  'class',
  'continue',
  'def',
  'del',
  'elif',
  'else',
  'except',
  'finally',
  'for',
  'from',
  'global',
  'if',
  'import',
  'in',
  'is',
  'lambda',
  'nonlocal',
  'not',
  'or',
  'pass',
  'raise',
  'return',
  'try',
  'while',
  'with',
  'yield',
]);

interface PyTok {
  t: 'kw' | 'name' | 'num' | 'op' | 'punct' | 'str';
  v: string;
}

function isPyIdentStart(ch: string) {
  return ch === '_' || /^\p{XID_Start}$/u.test(ch);
}

function isPyIdentContinue(ch: string) {
  return /^\p{XID_Continue}$/u.test(ch);
}

function isPySpace(ch: string) {
  return ch === ' ' || ch === '\t' || ch === '\n' || ch === '\r' || ch === '\f' || ch === '\v';
}

/** 与后端 `compiler._expr_references_field` 一致：成功解析时只认 ast.Name。 */
function pythonEvalNames(source: string): string[] | null {
  const tokens = tokenizePythonEval(source);
  if (!tokens) return null;
  let index = 0;
  const names: string[] = [];

  function peek(offset = 0) {
    return tokens?.[index + offset];
  }

  function eat() {
    const tok = tokens?.[index];
    index += 1;
    return tok;
  }

  function parseTest(): boolean {
    if (!parseOr()) return false;
    if (peek()?.t === 'kw' && peek()?.v === 'if') {
      eat();
      if (!parseOr()) return false;
      if (!(peek()?.t === 'kw' && peek()?.v === 'else')) return false;
      eat();
      return parseTest();
    }
    return true;
  }

  function parseOr(): boolean {
    if (!parseAnd()) return false;
    while (peek()?.t === 'kw' && peek()?.v === 'or') {
      eat();
      if (!parseAnd()) return false;
    }
    return true;
  }

  function parseAnd(): boolean {
    if (!parseNot()) return false;
    while (peek()?.t === 'kw' && peek()?.v === 'and') {
      eat();
      if (!parseNot()) return false;
    }
    return true;
  }

  function parseNot(): boolean {
    if (peek()?.t === 'kw' && peek()?.v === 'not' && !(peek(1)?.t === 'kw' && peek(1)?.v === 'in')) {
      eat();
      return parseNot();
    }
    return parseComparison();
  }

  function parseComparison(): boolean {
    if (!parseSum()) return false;
    while (isCompOp()) {
      const tok = eat();
      if (tok?.t === 'kw' && tok.v === 'not') eat();
      if (tok?.t === 'kw' && tok.v === 'is' && peek()?.t === 'kw' && peek()?.v === 'not') eat();
      if (!parseSum()) return false;
    }
    return true;
  }

  function isCompOp() {
    const tok = peek();
    if (!tok) return false;
    if (tok.t === 'op' && ['!=', '<', '<=', '==', '>', '>='].includes(tok.v)) return true;
    if (tok.t === 'kw' && (tok.v === 'in' || tok.v === 'is')) return true;
    return tok.t === 'kw' && tok.v === 'not' && peek(1)?.t === 'kw' && peek(1)?.v === 'in';
  }

  function parseSum(): boolean {
    if (!parseTerm()) return false;
    while (peek()?.t === 'op' && (peek()?.v === '+' || peek()?.v === '-')) {
      eat();
      if (!parseTerm()) return false;
    }
    return true;
  }

  function parseTerm(): boolean {
    if (!parseFactor()) return false;
    while (
      peek()?.t === 'op' &&
      (peek()?.v === '*' || peek()?.v === '/' || peek()?.v === '%' || peek()?.v === '//')
    ) {
      eat();
      if (!parseFactor()) return false;
    }
    return true;
  }

  function parseFactor(): boolean {
    const tok = peek();
    if (tok?.t === 'op' && (tok.v === '+' || tok.v === '-' || tok.v === '~')) {
      eat();
      return parseFactor();
    }
    if (!parsePrimary()) return false;
    if (peek()?.t === 'op' && peek()?.v === '**') {
      eat();
      return parseFactor();
    }
    return true;
  }

  function parsePrimary(): boolean {
    const tok = peek();
    if (!tok) return false;
    if (tok.t === 'name') {
      names.push(tok.v);
      eat();
      return parseTrailers();
    }
    if (tok.t === 'num' || tok.t === 'str') {
      eat();
      return parseTrailers();
    }
    if (tok.t === 'kw' && (tok.v === 'False' || tok.v === 'None' || tok.v === 'True')) {
      eat();
      return parseTrailers();
    }
    if (tok.t === 'punct' && tok.v === '(') return parseGroup('(', ')');
    if (tok.t === 'punct' && tok.v === '[') return parseGroup('[', ']');
    if (tok.t === 'punct' && tok.v === '{') return parseBrace();
    return false;
  }

  function parseGroup(open: string, close: string): boolean {
    if (peek()?.v !== open) return false;
    eat();
    if (peek()?.v === close) {
      eat();
      return parseTrailers();
    }
    while (true) {
      if (peek()?.t === 'op' && (peek()?.v === '*' || peek()?.v === '**')) eat();
      if (!parseTest()) return false;
      if (peek()?.v === ',') {
        eat();
        if (peek()?.v === close) break;
        continue;
      }
      break;
    }
    if (peek()?.v !== close) return false;
    eat();
    return parseTrailers();
  }

  function parseBrace(): boolean {
    eat();
    if (peek()?.v === '}') {
      eat();
      return parseTrailers();
    }
    if (peek()?.t === 'op' && peek()?.v === '**') eat();
    if (!parseTest()) return false;
    if (peek()?.v === ':') {
      eat();
      if (!parseTest()) return false;
      while (peek()?.v === ',') {
        eat();
        if (peek()?.v === '}') break;
        if (peek()?.t === 'op' && peek()?.v === '**') eat();
        if (!parseTest()) return false;
        if (peek()?.v !== ':') return false;
        eat();
        if (!parseTest()) return false;
      }
    } else {
      while (peek()?.v === ',') {
        eat();
        if (peek()?.v === '}') break;
        if (!parseTest()) return false;
      }
    }
    if (peek()?.v !== '}') return false;
    eat();
    return parseTrailers();
  }

  function parseTrailers(): boolean {
    while (true) {
      if (peek()?.v === '(' || peek()?.v === '[') {
        const open = peek()?.v === '(' ? '(' : '[';
        const close = open === '(' ? ')' : ']';
        eat();
        if (peek()?.v !== close) {
          while (true) {
            if (open === '(' && peek()?.t === 'op' && (peek()?.v === '*' || peek()?.v === '**')) {
              eat();
            }
            if (!parseTest()) return false;
            if (peek()?.v === ',') {
              eat();
              if (peek()?.v === close) break;
              continue;
            }
            break;
          }
        }
        if (peek()?.v !== close) return false;
        eat();
        continue;
      }
      if (peek()?.v === '.') {
        eat();
        if (peek()?.t !== 'name') return false;
        eat();
        continue;
      }
      return true;
    }
  }

  if (!parseTest() || index !== tokens.length) return null;
  return names;
}

function tokenizePythonEval(source: string): PyTok[] | null {
  const tokens: PyTok[] = [];
  let index = 0;

  while (index < source.length) {
    const ch = source.charAt(index);
    if (isPySpace(ch)) {
      index += 1;
      continue;
    }
    if (ch === '#') {
      while (index < source.length && source.charAt(index) !== '\n') index += 1;
      continue;
    }
    const prefix = stringPrefixLen(source, index);
    if (prefix > 0 || ch === '"' || ch === "'") {
      const start = index + prefix;
      const quote = source.charAt(start);
      const triple = source.slice(start, start + 3) === quote.repeat(3);
      index = start + (triple ? 3 : 1);
      const closer = triple ? quote.repeat(3) : quote;
      let closed = false;
      while (index < source.length) {
        if (source.charAt(index) === '\\') {
          index += 2;
          continue;
        }
        if (source.startsWith(closer, index)) {
          index += closer.length;
          closed = true;
          break;
        }
        if (!triple && (source.charAt(index) === '\n' || source.charAt(index) === '\r')) {
          return null;
        }
        index += 1;
      }
      if (!closed) return null;
      tokens.push({ t: 'str', v: '' });
      continue;
    }
    if (isDigit(ch) || (ch === '.' && isDigit(source.charAt(index + 1)))) {
      const start = index;
      if (ch === '.') index += 1;
      while (isDigit(source.charAt(index))) index += 1;
      if (ch !== '.' && source.charAt(index) === '.') {
        index += 1;
        while (isDigit(source.charAt(index))) index += 1;
      }
      const exp = source.charAt(index);
      if (exp === 'e' || exp === 'E') {
        let next = index + 1;
        if (source.charAt(next) === '+' || source.charAt(next) === '-') next += 1;
        if (!isDigit(source.charAt(next))) return null;
        index = next;
        while (isDigit(source.charAt(index))) index += 1;
      }
      tokens.push({ t: 'num', v: source.slice(start, index) });
      continue;
    }
    if (isPyIdentStart(ch)) {
      const start = index;
      index += 1;
      while (isPyIdentContinue(source.charAt(index))) index += 1;
      const word = source.slice(start, index);
      tokens.push({ t: PY_KEYWORDS.has(word) ? 'kw' : 'name', v: word });
      continue;
    }
    const two = source.slice(index, index + 2);
    if (['!=', '**', '//', '<=', '==', '>='].includes(two)) {
      tokens.push({ t: 'op', v: two });
      index += 2;
      continue;
    }
    if ('+-*/%<>=~'.includes(ch)) {
      tokens.push({ t: 'op', v: ch });
      index += 1;
      continue;
    }
    if ('()[]{}.,:'.includes(ch)) {
      tokens.push({ t: 'punct', v: ch });
      index += 1;
      continue;
    }
    return null;
  }
  return tokens;
}

function stringPrefixLen(source: string, index: number) {
  const two = source.slice(index, index + 2).toLowerCase();
  const afterTwo = source.charAt(index + 2);
  if (
    (two === 'br' || two === 'fr' || two === 'rb' || two === 'rf') &&
    (afterTwo === '"' || afterTwo === "'")
  ) {
    return 2;
  }
  const one = source.charAt(index).toLowerCase();
  const afterOne = source.charAt(index + 1);
  if (
    (one === 'b' || one === 'f' || one === 'r' || one === 'u') &&
    (afterOne === '"' || afterOne === "'")
  ) {
    return 1;
  }
  return 0;
}

function isDigit(ch: string) {
  return ch >= '0' && ch <= '9';
}

function exprReferencesAccrued(expr: unknown) {
  if (typeof expr !== 'string' || !expr.trim()) return false;
  const text = expr.replaceAll('×', '*').replaceAll('÷', '/');
  const names = pythonEvalNames(text);
  if (!names) return text.includes(ACCRUED_AMOUNT_FIELD);
  return names.includes(ACCRUED_AMOUNT_FIELD);
}

function jsonReferencesAccrued(node: unknown): boolean {
  if (Array.isArray(node)) return node.some((item) => jsonReferencesAccrued(item));
  if (!node || typeof node !== 'object') return false;
  const record = node as Record<string, unknown>;
  if (record['字段'] === ACCRUED_AMOUNT_FIELD) return true;
  if (exprReferencesAccrued(record['表达式'])) return true;
  return Object.entries(record).some(
    ([key, value]) => key !== '字段' && key !== '表达式' && jsonReferencesAccrued(value),
  );
}

export function itemReferencesAccrued(item: {
  condition_json?: null | Record<string, unknown>;
  formula_json?: null | Record<string, unknown>;
}) {
  return (
    jsonReferencesAccrued(item.condition_json) ||
    jsonReferencesAccrued(item.formula_json)
  );
}

export function accruedSortHint(items: PlanItemDraft[]) {
  const period = toSaveItems(items).filter(
    (item) => item.stage === 'period' && item.enabled,
  );
  if (period.length === 0) return '';
  const maxSort = Math.max(...period.map((item) => item.sort_order));
  const names = period
    .filter((item) => itemReferencesAccrued(item))
    .filter((item) => {
      const blocked = period.some(
        (other) =>
          other !== item &&
          other.sort_order >= item.sort_order &&
          !itemReferencesAccrued(other),
      );
      return item.sort_order !== maxSort || blocked;
    })
    .map((item) => item.name.trim() || '未命名');
  if (names.length === 0) return '';
  const label = names.map((name) => `「${name}」`).join('、');
  return `保底项${label}引用「本期已计金额」，必须排在周期阶段最后，否则补差会偏大`;
}

export function moveAccruedItemsLast(items: PlanItemDraft[]) {
  const referencing = items.filter(
    (item) =>
      item.stage === 'period' && item.enabled && itemReferencesAccrued(item),
  );
  if (referencing.length === 0) return items;
  const keys = new Set(referencing.map((item) => item._key));
  const rest = items.filter((item) => !keys.has(item._key));
  const lastPeriod = rest.reduce(
    (found, item, index) => (item.stage === 'period' ? index : found),
    -1,
  );
  if (lastPeriod < 0) {
    return STAGE_ORDER.flatMap((stage) =>
      stage === 'period' ? referencing : rest.filter((item) => item.stage === stage),
    );
  }
  return [
    ...rest.slice(0, lastPeriod + 1),
    ...referencing,
    ...rest.slice(lastPeriod + 1),
  ];
}

export function summarizeCondition(
  json: null | Record<string, unknown> | undefined,
  compiled?: null | string,
): string {
  if (compiled && compiled !== 'True') return compiled;
  const group = fromConditionJson(json);
  if (group.条件.length === 0) return '恒真（空条件）';
  return group.条件
    .map((node) => {
      if (isGroup(node)) {
        const inner = node.条件
          .map((child) =>
            isLeaf(child)
              ? `${child.字段 ?? ''} ${child.运算符 ?? ''} ${formatValue(child.值)}`
              : '…',
          )
          .join(` ${node.逻辑} `);
        return `(${inner})`;
      }
      return `${node.字段 ?? ''} ${node.运算符 ?? ''} ${formatValue(node.值)}`;
    })
    .join(` ${group.逻辑} `);
}

export function summarizeFormula(
  json: null | Record<string, unknown> | undefined,
  compiled?: null | string,
): string {
  if (compiled) return compiled;
  if (!json) return '—';
  const kind = formulaKindOf(json);
  if (kind === '固定金额') return `固定金额 ${json.金额 ?? ''}`;
  if (kind === '字段乘单价') {
    return `(${json.字段 ?? ''} − ${json.起算值 ?? 0}) × ${json.单价 ?? ''}`;
  }
  if (kind === '阶梯') {
    return `阶梯 ${json.字段 ?? ''} / ${json.模式 ?? ''} / ${json.计价 ?? ''}`;
  }
  return String(json.表达式 || '表达式');
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.join('~');
  if (typeof value === 'boolean') return value ? '是' : '否';
  return String(value);
}

export function canEditVersion(status?: string, isUsed?: boolean) {
  return status === 'draft' && !isUsed;
}

export function planEditorVersionId(raw: unknown) {
  const text = Array.isArray(raw) ? raw[0] : raw;
  if (typeof text !== 'string' && typeof text !== 'number') return 0;
  const value = Number(text);
  return Number.isInteger(value) && value > 0 ? value : 0;
}

export function shouldTrialWithoutSaving(versionId: number, dirty: boolean) {
  return versionId <= 0 || dirty;
}

export function newPlanEditorLocation(planId: number) {
  return {
    path: '/rider-salary/plan/editor/new',
    query: { plan_id: String(planId) },
  };
}

export function readUnsavedPlanDraft(state: unknown): {
  draftItems?: PlanItemParam[];
  modeTag?: string;
} {
  if (!state || typeof state !== 'object') return {};
  const record = state as {
    draftItems?: unknown;
    draftItemsJson?: unknown;
    modeTag?: unknown;
  };
  let draftItems: PlanItemParam[] | undefined;
  if (typeof record.draftItemsJson === 'string') {
    try {
      const parsed = JSON.parse(record.draftItemsJson) as unknown;
      if (Array.isArray(parsed)) draftItems = parsed as PlanItemParam[];
    } catch {
      draftItems = undefined;
    }
  } else if (Array.isArray(record.draftItems)) {
    draftItems = record.draftItems as PlanItemParam[];
  }
  return {
    draftItems,
    modeTag: typeof record.modeTag === 'string' ? record.modeTag : undefined,
  };
}

export function trialLabel(options: {
  dirty?: boolean;
  itemsHash?: null | string;
  trialHash?: null | string;
  trialPassed?: boolean;
}) {
  if (options.dirty) return { color: 'warning', text: '需重新试算' };
  if (options.trialPassed && options.trialHash && options.trialHash === options.itemsHash) {
    return { color: 'success', text: '试算通过 ✓' };
  }
  if (options.trialPassed && options.trialHash && options.trialHash !== options.itemsHash) {
    return { color: 'warning', text: '需重新试算' };
  }
  if (options.trialHash && !options.trialPassed) {
    return { color: 'error', text: '试算未通过' };
  }
  return { color: 'default', text: '未试算' };
}

export function activateHint(options: {
  dirty?: boolean;
  itemsHash?: null | string;
  trialHash?: null | string;
  trialPassed?: boolean;
}) {
  if (options.dirty) return '请先保存方案项';
  if (!options.trialPassed) return '请先完成试算再启用';
  if (options.trialHash !== options.itemsHash) return '方案内容已变更，请重新试算';
  return '';
}

export function operatorsForFieldType(
  type?: string,
  operatorsByType?: Record<string, string[]>,
) {
  const list = operatorsByType?.[type || 'number'];
  if (list?.length) return [...list];
  return ['='];
}

export function defaultOperatorForType(
  type?: string,
  operatorsByType?: Record<string, string[]>,
) {
  return operatorsForFieldType(type, operatorsByType)[0] ?? '=';
}

const BUILTIN_PLACEHOLDERS: FormulaPlaceholder[] = [
  {
    description: '底薪金额（元），保存前替换为具体数字',
    example: 2000,
    kind: 'number',
    label: '底薪金额',
    token: '{底薪金额}',
  },
];

const BASE_SALARY_SKELETON = '{底薪金额} * 方案生效天数 / 周期天数';

function isIdentChar(ch: string): boolean {
  return /[0-9A-Za-z_\u4e00-\u9fff]/.test(ch);
}

function containsLabel(text: string, label: string): boolean {
  if (!label) return false;
  let start = 0;
  while (start <= text.length) {
    const index = text.indexOf(label, start);
    if (index < 0) return false;
    const before = index > 0 ? (text[index - 1] ?? '') : '';
    const after = text[index + label.length] ?? '';
    if (!isIdentChar(before) && !isIdentChar(after)) return true;
    start = index + 1;
  }
  return false;
}

function replaceLabel(text: string, label: string, value: string): string {
  if (!label) return text;
  let result = '';
  let start = 0;
  while (start <= text.length) {
    const index = text.indexOf(label, start);
    if (index < 0) return result + text.slice(start);
    const before = index > 0 ? (text[index - 1] ?? '') : '';
    const after = text[index + label.length] ?? '';
    if (!isIdentChar(before) && !isIdentChar(after)) {
      result += text.slice(start, index) + value;
      start = index + label.length;
    } else {
      result += text.slice(start, index + 1);
      start = index + 1;
    }
  }
  return result;
}

export function formulaPlaceholders(
  templates?: EngineFormulaTemplate[] | null,
): FormulaPlaceholder[] {
  const declared = (templates ?? []).flatMap((item) => item.placeholders ?? []);
  return declared.length > 0 ? declared : BUILTIN_PLACEHOLDERS;
}

export function unreplacedPlaceholderLabels(
  formula: null | Record<string, unknown> | undefined,
  templates?: EngineFormulaTemplate[] | null,
): string[] {
  const expr = String(formula?.表达式 ?? '');
  if (!expr.trim()) return [];
  const labels: string[] = [];
  for (const item of formulaPlaceholders(templates)) {
    const token = item.token ?? '';
    const label = item.label || token;
    if (!label) continue;
    const hit = Boolean(token && expr.includes(token)) || containsLabel(expr, label);
    if (hit && !labels.includes(label)) labels.push(label);
  }
  return labels;
}

export function applyBaseSalaryTemplate(
  amount: number | string,
  templates?: EngineFormulaTemplate[] | null,
): string {
  const template = (templates ?? []).find((item) => item.type === '底薪分摊');
  const skeleton = String(template?.skeleton?.表达式 ?? BASE_SALARY_SKELETON);
  const placeholders = template?.placeholders?.length
    ? template.placeholders
    : BUILTIN_PLACEHOLDERS;
  let expr = skeleton;
  const text = String(amount);
  for (const item of placeholders) {
    if (item.token) expr = expr.split(item.token).join(text);
    if (item.label) expr = replaceLabel(expr, item.label, text);
  }
  return expr;
}

export function defaultValueFor(type?: string, operator?: string): unknown {
  if (operator && RANGE_OPERATORS.has(operator)) {
    return type === 'time' ? [undefined, undefined] : [undefined, undefined];
  }
  if (operator && MULTI_OPERATORS.has(operator)) return [];
  if (type === 'bool') return true;
  return undefined;
}
