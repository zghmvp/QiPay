import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  BINDING_WRITE_PERM,
  EMPLOY_WRITE_PERM,
  bindingRemoveContent,
  employRemoveContent,
  formatAffectedSpan,
  mergePlanVersionOptions,
  showHistoryActions,
  toBindingUpdate,
  toEmployUpdate,
} from './history-actions';

const here = dirname(fileURLToPath(import.meta.url));

function sourceOf(name: string): string {
  return readFileSync(resolve(here, 'components', name), 'utf8');
}

function functionBlock(source: string, name: string): string {
  const start = source.indexOf(`async function ${name}`);
  const next = source.indexOf('\nasync function ', start + 1);
  const end = next === -1 ? source.indexOf('\nwatch(', start) : next;
  return source.slice(start, end === -1 ? undefined : end);
}

describe('绑定和用工历史的编辑与删除确认', () => {
  it('确认文案带上受影响区间和重算后果', () => {
    const binding = bindingRemoveContent({
      end_date: null,
      plan_short_name: '纯按单',
      plan_version_id: 12,
      start_date: '2026-09-01',
    });
    expect(binding).toContain('纯按单');
    expect(binding).toContain('受影响区间：2026-09-01 ~ 长期');
    expect(binding).toContain('需重算');

    const closed = bindingRemoveContent({
      end_date: '2026-09-30',
      plan_version_id: 8,
      start_date: '2026-09-15',
    });
    expect(closed).toContain('版本 8');
    expect(closed).toContain('2026-09-15 ~ 2026-09-30');

    const employ = employRemoveContent({
      employ_type: 'part_time',
      employ_type_label: '兼职',
      end_date: '2026-10-31',
      start_date: '2026-10-01',
    });
    expect(employ).toContain('兼职');
    expect(employ).toContain('受影响区间：2026-10-01 ~ 2026-10-31');
    expect(employ).toContain('需重算');
    expect(formatAffectedSpan('2026-01-01', '  ', '至今')).toBe(
      '2026-01-01 ~ 至今',
    );
  });

  it('编辑提交完整区间，空结束日写成 null', () => {
    expect(
      toBindingUpdate({
        binding_type: 'override',
        end_date: '2026-12-31',
        plan_version_id: 3,
        remark: '  ',
        start_date: '2026-10-01',
      }),
    ).toEqual({
      binding_type: 'override',
      end_date: '2026-12-31',
      plan_version_id: 3,
      remark: null,
      start_date: '2026-10-01',
    });
    expect(
      toBindingUpdate({
        binding_type: 'default',
        end_date: '',
        plan_version_id: 9,
        start_date: '2026-11-01',
      }).end_date,
    ).toBeNull();
    expect(
      toEmployUpdate({
        employ_type: 'full_time',
        end_date: null,
        remark: '转全职',
        start_date: '2026-08-01',
      }),
    ).toEqual({
      employ_type: 'full_time',
      end_date: null,
      remark: '转全职',
      start_date: '2026-08-01',
    });
  });

  it('当前绑定的版本不在启用列表时仍保留', () => {
    const active = [{ label: '底薪 · C02 v2', value: 2 }];
    expect(
      mergePlanVersionOptions(active, {
        plan_short_name: '纯按单',
        plan_version_id: 1,
      })[0],
    ).toEqual({ label: '纯按单（当前绑定）', value: 1 });
    expect(
      mergePlanVersionOptions(active, {
        plan_short_name: '底薪',
        plan_version_id: 2,
      }),
    ).toEqual(active);
  });

  it('没有写权限时不显示编辑和删除', () => {
    expect(showHistoryActions(true)).toBe(true);
    expect(showHistoryActions(false)).toBe(false);
    expect(BINDING_WRITE_PERM).toBe('rs:rider:binding');
    expect(EMPLOY_WRITE_PERM).toBe('rs:rider:employ');
  });

  it('绑定面板先确认再解除，编辑走 PUT 且不改写后端错误', () => {
    const source = sourceOf('BindingPanel.vue');
    expect(source).toContain('BINDING_WRITE_PERM');
    expect(source).toContain('v-access:code="BINDING_WRITE_PERM"');
    expect(source).toContain('updateRiderBindingApi');
    expect(source).toContain('toBindingUpdate');
    expect(source).toContain('编辑');
    const remove = functionBlock(source, 'removeBinding');
    expect(remove.indexOf('bindingRemoveContent')).toBeGreaterThan(-1);
    expect(remove.indexOf('bindingRemoveContent')).toBeLessThan(
      remove.indexOf('deleteRiderBindingApi'),
    );
    expect(remove).not.toContain('message.error');
    const save = functionBlock(source, 'saveEdit');
    expect(save).toContain('updateRiderBindingApi');
    expect(save).not.toContain('message.error');
  });

  it('用工历史面板先确认再删除，编辑走 PUT', () => {
    const source = sourceOf('EmployPanel.vue');
    expect(source).toContain('EMPLOY_WRITE_PERM');
    expect(source).toContain('v-access:code="EMPLOY_WRITE_PERM"');
    expect(source).toContain('updateRiderEmployHistoryApi');
    expect(source).toContain('toEmployUpdate');
    expect(source).toContain('编辑');
    const remove = functionBlock(source, 'removeRow');
    expect(remove.indexOf('employRemoveContent')).toBeGreaterThan(-1);
    expect(remove.indexOf('employRemoveContent')).toBeLessThan(
      remove.indexOf('deleteRiderEmployHistoryApi'),
    );
    expect(remove).not.toContain('message.error');
  });
});
