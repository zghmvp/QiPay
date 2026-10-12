import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  LIST_LEGACY_OPEN_CODE,
  LIST_OPEN_CODES,
  LIST_VIEW_CODE,
  LIST_WRITE_CODES,
  canOpenList,
  visibleWriteCodes,
  type ListPage,
} from './access';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PAGES: ListPage[] = [
  'rider',
  'adjustment',
  'advance',
  'notice',
  'dayflag',
];

const PAGE_FILES: Record<ListPage, string[]> = {
  adjustment: ['views/adjustment/index.vue', 'views/adjustment/data.ts'],
  advance: ['views/advance/index.vue', 'views/advance/data.ts'],
  dayflag: ['views/day-flag/index.vue'],
  notice: ['views/notice/index.vue', 'views/notice/data.ts'],
  rider: [
    'views/rider/index.vue',
    'views/rider/data.ts',
    'views/rider/detail.vue',
    'views/rider/components/EmployPanel.vue',
    'views/rider/components/BindingPanel.vue',
  ],
};

function literalCodes(source: string): string[] {
  const found = new Set<string>();
  for (const match of source.matchAll(/v-access:code="'([^']+)'"/g)) {
    found.add(match[1] ?? '');
  }
  for (const match of source.matchAll(/hasAccessByCodes\(\[([^\]]*)\]\)/g)) {
    for (const code of (match[1] ?? '').matchAll(/'([^']+)'/g)) {
      found.add(code[1] ?? '');
    }
  }
  return [...found];
}

describe('列表页 view 码与写按钮', () => {
  it('只有 view 码时能打开列表，看不到写按钮', () => {
    for (const page of PAGES) {
      expect(canOpenList([LIST_VIEW_CODE[page]], page)).toBe(true);
      expect(visibleWriteCodes([LIST_VIEW_CODE[page]], page)).toEqual([]);
    }
  });

  it('只有原写码也能打开列表页', () => {
    for (const page of PAGES) {
      const legacy = LIST_LEGACY_OPEN_CODE[page];
      expect(LIST_OPEN_CODES[page]).toEqual([LIST_VIEW_CODE[page], legacy]);
      expect(canOpenList([legacy], page)).toBe(true);
      expect(visibleWriteCodes([legacy], page)).toEqual([legacy]);
    }
  });

  it('页面用过渡期放行码包住列表，字面权限码都是写码', () => {
    for (const page of PAGES) {
      const sources = PAGE_FILES[page].map((file) =>
        readFileSync(resolve(ROOT, file), 'utf8'),
      );
      const pageSource = sources[0] ?? '';
      expect(pageSource).toContain(`v-access:code="LIST_OPEN_CODES.${page}"`);
      const literals = sources.flatMap((source) => literalCodes(source));
      expect(literals.length).toBeGreaterThan(0);
      for (const code of literals) {
        expect(LIST_WRITE_CODES[page]).toContain(code);
        expect(code.endsWith(':view')).toBe(false);
      }
    }
  });
});
