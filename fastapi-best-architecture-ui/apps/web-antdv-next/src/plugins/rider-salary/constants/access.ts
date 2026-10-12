/** 列表页只读权限。写按钮继续用各自的写码，不看这里。 */
export const LIST_VIEW_CODE = {
  adjustment: 'rs:adjustment:view',
  advance: 'rs:advance:view',
  dayflag: 'rs:dayflag:view',
  notice: 'rs:notice:view',
  rider: 'rs:rider:view',
} as const;

export type ListPage = keyof typeof LIST_VIEW_CODE;

/**
 * 各列表 GET 在引入 view 码之前使用的那个写码。
 * 与后端 RequestAnyPermission(view, 原写码) 的第二参数同一份映射。
 * 下一个版本删除原写码兼容，只保留 LIST_VIEW_CODE。
 */
export const LIST_LEGACY_OPEN_CODE = {
  adjustment: 'rs:adjustment:add',
  advance: 'rs:advance:approve',
  dayflag: 'rs:dayflag:edit',
  notice: 'rs:notice:add',
  rider: 'rs:rider:add',
} as const satisfies Record<ListPage, string>;

/**
 * 过渡期列表放行码：view 或原写码，有其一即可。
 * 下一个版本删除原写码兼容，PageContainer 改回只传 LIST_VIEW_CODE。
 */
export const LIST_OPEN_CODES: Record<ListPage, readonly [string, string]> = {
  adjustment: [LIST_VIEW_CODE.adjustment, LIST_LEGACY_OPEN_CODE.adjustment],
  advance: [LIST_VIEW_CODE.advance, LIST_LEGACY_OPEN_CODE.advance],
  dayflag: [LIST_VIEW_CODE.dayflag, LIST_LEGACY_OPEN_CODE.dayflag],
  notice: [LIST_VIEW_CODE.notice, LIST_LEGACY_OPEN_CODE.notice],
  rider: [LIST_VIEW_CODE.rider, LIST_LEGACY_OPEN_CODE.rider],
};

/** 各列表页的写操作权限。只有这些码能看到对应写按钮。 */
export const LIST_WRITE_CODES: Record<ListPage, readonly string[]> = {
  adjustment: ['rs:adjustment:add', 'rs:adjustment:edit', 'rs:adjustment:del'],
  advance: [
    'rs:advance:approve',
    'rs:advance:reject',
    'rs:advance:mark-paid',
    'rs:advance:cancel',
    'rs:advance:export',
  ],
  dayflag: ['rs:dayflag:edit'],
  notice: ['rs:notice:add', 'rs:notice:edit', 'rs:notice:del'],
  rider: [
    'rs:rider:add',
    'rs:rider:edit',
    'rs:rider:del',
    'rs:rider:binding',
    'rs:rider:employ',
    'rs:rider:account',
  ],
};

/** 过渡期：view 码或 LIST_LEGACY_OPEN_CODE 都能打开列表。下一个版本只认 view 码。 */
export function canOpenList(
  granted: readonly string[],
  page: ListPage,
): boolean {
  const allowed = new Set<string>(LIST_OPEN_CODES[page]);
  return granted.some((code) => allowed.has(code));
}

export function visibleWriteCodes(
  granted: readonly string[],
  page: ListPage,
): string[] {
  const owned = new Set(granted);
  return LIST_WRITE_CODES[page].filter((code) => owned.has(code));
}
