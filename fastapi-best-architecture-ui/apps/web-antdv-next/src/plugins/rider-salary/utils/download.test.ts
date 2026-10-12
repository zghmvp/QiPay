// @vitest-environment node
// 插件单测（不改框架 vitest 配置）。在 fastapi-best-architecture-ui 目录执行：
// pnpm exec vitest run apps/web-antdv-next/src/plugins/rider-salary
//
// 框架 vitest 没有配置 `#/` 别名，直接 import `./download` 会在解析
// `#/api/request` 时失败。文件名解析本身不依赖请求客户端，这里装载源码里的
// headerValue 与 parseContentDisposition，与 downloadNamedBlob 使用的是同一段实现。
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

import { describe, expect, it } from 'vitest';

const require = createRequire(import.meta.url);

function loadFilenameParsers() {
  const source = readFileSync(new URL('./download.ts', import.meta.url), 'utf8');
  const start = source.indexOf('function headerValue');
  const end = source.indexOf('export async function downloadNamedBlob');
  if (start < 0 || end < start) {
    throw new Error('download.ts 里文件名解析函数的位置变了');
  }
  const chunk = source
    .slice(start, end)
    .replace(
      'export function parseContentDisposition',
      'function parseContentDisposition',
    );
  const ts = require('typescript') as {
    ModuleKind: { ESNext: number };
    ScriptTarget: { ES2022: number };
    transpileModule: (
      input: string,
      options: { compilerOptions: { module: number; target: number } },
    ) => { outputText: string };
  };
  const { outputText } = ts.transpileModule(chunk, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
  });
  const factory = new Function(
    `${outputText}\nreturn { headerValue, parseContentDisposition };`,
  );
  return factory() as {
    headerValue: (headers: unknown, name: string) => string | undefined;
    parseContentDisposition: (header?: null | string) => string | undefined;
  };
}

const { headerValue, parseContentDisposition } = loadFilenameParsers();

const PAYROLL = '周期薪资-12.xlsx';
const TEMPLATE = '订单导入模板.xlsx';

function starHeader(filename: string, asciiName?: string) {
  const encoded = `filename*=UTF-8''${encodeURIComponent(filename)}`;
  if (!asciiName) return `attachment; ${encoded}`;
  return `attachment; filename="${asciiName}"; ${encoded}`;
}

function fileNameFrom(headers: unknown, fallbackName: string) {
  return (
    parseContentDisposition(headerValue(headers, 'content-disposition')) ||
    fallbackName
  );
}

describe('parseContentDisposition', () => {
  it('空头和不含文件名时没有结果', () => {
    expect(parseContentDisposition(undefined)).toBeUndefined();
    expect(parseContentDisposition(null)).toBeUndefined();
    expect(parseContentDisposition('')).toBeUndefined();
    expect(parseContentDisposition('attachment')).toBeUndefined();
  });

  it('优先解析 RFC 5987 filename*，中文百分号编码还原', () => {
    expect(parseContentDisposition(starHeader(PAYROLL, 'payroll.xlsx'))).toBe(
      PAYROLL,
    );
    expect(parseContentDisposition(starHeader(TEMPLATE))).toBe(TEMPLATE);
    expect(
      parseContentDisposition(
        `attachment; filename*=utf-8''${encodeURIComponent(TEMPLATE)}`,
      ),
    ).toBe(TEMPLATE);
  });

  it('没有 filename* 时回退 filename=，去掉引号和首尾空白', () => {
    expect(parseContentDisposition('attachment; filename="payroll.xlsx"')).toBe(
      'payroll.xlsx',
    );
    expect(parseContentDisposition('attachment; filename=payroll.xlsx')).toBe(
      'payroll.xlsx',
    );
    expect(
      parseContentDisposition('attachment; filename="周期薪资-12.xlsx"'),
    ).toBe(PAYROLL);
    expect(
      parseContentDisposition('attachment; filename="  spaced.xlsx  "'),
    ).toBe('spaced.xlsx');
  });

  it('百分号编码非法时保留 filename* 原文，不改用 filename=', () => {
    expect(
      parseContentDisposition(
        'attachment; filename="payroll.xlsx"; filename*=UTF-8\'\'100%ZZ.xlsx',
      ),
    ).toBe('100%ZZ.xlsx');
  });
});

describe('响应头里的文件名', () => {
  it('从 Headers 或普通对象取出 Content-Disposition 再解析', () => {
    const headers = new Headers();
    headers.set('Content-Disposition', starHeader(TEMPLATE));
    expect(fileNameFrom(headers, '兜底.xlsx')).toBe(TEMPLATE);

    expect(
      fileNameFrom(
        { 'content-disposition': starHeader(PAYROLL, 'payroll.xlsx') },
        '周期薪资-12.xlsx',
      ),
    ).toBe(PAYROLL);

    expect(
      fileNameFrom(
        { 'Content-Disposition': 'attachment; filename="payroll.xlsx"' },
        '兜底.xlsx',
      ),
    ).toBe('payroll.xlsx');
  });

  it('没有头、头不是字符串、或解析失败时用兜底名', () => {
    expect(headerValue(null, 'content-disposition')).toBeUndefined();
    expect(headerValue(undefined, 'content-disposition')).toBeUndefined();
    expect(headerValue('nope', 'content-disposition')).toBeUndefined();
    expect(
      headerValue({ 'content-disposition': 1 }, 'content-disposition'),
    ).toBeUndefined();
    expect(fileNameFrom(null, '预支明细.xlsx')).toBe('预支明细.xlsx');
    expect(fileNameFrom({}, '预支明细.xlsx')).toBe('预支明细.xlsx');
    expect(fileNameFrom({ 'content-disposition': 'attachment' }, '预支明细.xlsx')).toBe(
      '预支明细.xlsx',
    );
  });
});
