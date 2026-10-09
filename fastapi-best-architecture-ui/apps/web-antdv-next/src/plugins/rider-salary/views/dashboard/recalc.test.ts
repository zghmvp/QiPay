import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it, vi } from 'vitest';

import type { CalcJobSnapshot } from '../period/calc-progress';

import {
  errorText,
  recalcProgressText,
  resolveStaleTargets,
  runStaleRecalc,
  showStaleRecalc,
  stalePeriodListQuery,
  STALE_BLOCK_KEY,
  STALE_RECALC_PERM,
} from './recalc';

const here = dirname(fileURLToPath(import.meta.url));
const listSource = readFileSync(resolve(here, 'components/AttentionList.vue'), 'utf8');
const pageSource = readFileSync(resolve(here, 'index.vue'), 'utf8');

function job(status: string, extra: Partial<CalcJobSnapshot> = {}): CalcJobSnapshot {
  return {
    done_count: extra.done_count ?? 2,
    failed_count: extra.failed_count ?? 0,
    status,
    success_count: extra.success_count ?? 2,
    total_count: extra.total_count ?? 2,
    ...extra,
  };
}

describe('工作台一键重算', () => {
  it('只有需重算块且有算薪权限时显示按钮', () => {
    expect(showStaleRecalc(STALE_BLOCK_KEY, true)).toBe(true);
    expect(showStaleRecalc(STALE_BLOCK_KEY, false)).toBe(false);
    expect(showStaleRecalc('due_periods', true)).toBe(false);
    expect(STALE_RECALC_PERM).toBe('rs:period:calculate');
  });

  it('预览已经列全时不再请求周期列表，并跳过不可算状态', async () => {
    const listPage = vi.fn();
    const resolved = await resolveStaleTargets({
      count: 2,
      items: [
        { period_id: 11, range: '09-01~09-15', status: 'open' },
        { period_id: 12, range: '09-01~09-15', status: 'locked' },
      ],
      listPage,
    });
    expect(listPage).not.toHaveBeenCalled();
    expect(resolved.targets).toEqual([{ label: '09-01~09-15', periodId: 11 }]);
    expect(resolved.skipped).toEqual(['09-01~09-15 当前状态不可重算']);
  });

  it('预览被截断时按开放和补发中补齐全部需重算周期', async () => {
    const listPage = vi.fn().mockResolvedValue({
      items: [
        { id: 11, start_date: '2026-09-01', end_date: '2026-09-15', status: 'open' },
        { id: 21, start_date: '2026-09-16', end_date: '2026-09-30', status: 'reopened' },
      ],
      total: 2,
    });
    const resolved = await resolveStaleTargets({
      count: 2,
      items: [{ period_id: 11, range: '09-01~09-15', status: 'open' }],
      listPage,
    });
    expect(listPage).toHaveBeenCalledWith(1, 200);
    expect(resolved.targets.map((item) => item.periodId)).toEqual([11, 21]);
    expect(resolved.targets[0]?.label).toBe('09-01~09-15');
    expect(
      stalePeriodListQuery({ month: '2026-09', page: 1, siteId: 3 }),
    ).toEqual({
      month: '2026-09',
      page: 1,
      site_id: 3,
      size: 200,
      stale: true,
      status: 'open,reopened',
    });
    expect(stalePeriodListQuery({ page: 2 }).site_id).toBeUndefined();
  });

  it('轮询作业到终态后要求刷新需重算计数', async () => {
    const ticks: string[] = [];
    const loadJob = vi
      .fn()
      .mockResolvedValueOnce(
        job('running', { done_count: 1, success_count: 0, total_count: 4 }),
      )
      .mockResolvedValueOnce(job('succeeded', { done_count: 4, success_count: 4, total_count: 4 }));
    const result = await runStaleRecalc({
      calculate: vi.fn().mockResolvedValue({
        calculated: 0,
        job_id: 9,
        queued: true,
      }),
      intervalMs: 0,
      loadJob,
      onProgress: (text) => {
        ticks.push(text);
      },
      targets: [{ label: '09-01~09-15', periodId: 11 }],
    });
    expect(loadJob).toHaveBeenCalledTimes(2);
    expect(loadJob).toHaveBeenCalledWith(9);
    expect(ticks.some((text) => text.includes('正在计算 1/4'))).toBe(true);
    expect(result.shouldRefresh).toBe(true);
    expect(result.level).toBe('success');
    expect(result.text).toBe('已重算 1 个周期，共 4 名骑手');
  });

  it('作业失败时保留原因，并仍然刷新', async () => {
    const result = await runStaleRecalc({
      calculate: vi.fn().mockResolvedValue({
        calculated: 0,
        job_id: 3,
        queued: true,
      }),
      intervalMs: 0,
      loadJob: vi.fn().mockResolvedValue(
        job('failed', {
          done_count: 1,
          error_message: '算薪失败',
          failed_count: 1,
          success_count: 0,
          total_count: 1,
        }),
      ),
      targets: [{ label: '09-16~09-30', periodId: 12 }],
    });
    expect(result.level).toBe('error');
    expect(result.shouldRefresh).toBe(true);
    expect(result.text).toContain('算薪失败');
  });

  it('当场算完不必轮询，接口错误不刷新', async () => {
    const loadJob = vi.fn();
    const inline = await runStaleRecalc({
      calculate: vi.fn().mockResolvedValue({ calculated: 2, queued: false }),
      loadJob,
      targets: [{ label: '周期 8', periodId: 8 }],
    });
    expect(loadJob).not.toHaveBeenCalled();
    expect(inline).toEqual({
      level: 'success',
      shouldRefresh: true,
      text: '已重算 1 个周期，共 2 名骑手',
    });

    const failed = await runStaleRecalc({
      calculate: vi.fn().mockRejectedValue({ msg: '结算周期正在计算中' }),
      loadJob,
      targets: [{ label: '周期 8', periodId: 8 }],
    });
    expect(failed.shouldRefresh).toBe(false);
    expect(failed.text).toContain('结算周期正在计算中');
    expect(errorText(new Error('网络中断'))).toBe('网络中断');
  });

  it('进度文案带上已完成周期数', () => {
    expect(
      recalcProgressText({
        done: 1,
        label: '09-01~09-15',
        phase: 'submit',
        total: 3,
      }),
    ).toBe('正在重算 1/3：正在提交 09-01~09-15');
  });

  it('需重算块挂权限按钮，终态后刷新工作台', () => {
    expect(listSource).toContain('showStaleRecalc(block.key, canCalculate)');
    expect(listSource).toContain(`v-access:code="'${STALE_RECALC_PERM}'"`);
    expect(listSource).toContain('一键重算');
    expect(listSource).toContain('getCalcJobApi');
    expect(listSource).toContain('runStaleRecalc');
    expect(listSource).toContain("emit('done')");
    expect(pageSource).toContain('@done="load"');
  });
});
