import { describe, expect, it, vi } from 'vitest';

import {
  calcProgressText,
  describeCalcJob,
  isCalcJobFinished,
  waitForCalcJob,
} from './calc-progress';

describe('算薪作业进度', () => {
  it('终态为成功、失败和部分成功', () => {
    expect(isCalcJobFinished('queued')).toBe(false);
    expect(isCalcJobFinished('running')).toBe(false);
    expect(isCalcJobFinished('succeeded')).toBe(true);
    expect(isCalcJobFinished('failed')).toBe(true);
    expect(isCalcJobFinished('partial')).toBe(true);
  });

  it('按终态给出中文结果', () => {
    expect(
      describeCalcJob({
        done_count: 2,
        failed_count: 0,
        status: 'succeeded',
        success_count: 2,
        total_count: 2,
      }),
    ).toEqual({ level: 'success', text: '已计算 2 名骑手' });
    expect(
      describeCalcJob({
        done_count: 1,
        error_message: '结算周期当前状态为已锁账，后台算薪已跳过，未新增草稿',
        failed_count: 0,
        status: 'failed',
        success_count: 0,
        total_count: 1,
      }).text,
    ).toContain('未新增草稿');
    expect(
      describeCalcJob({
        done_count: 2,
        failed_count: 1,
        failures: [{ job_no: 'R2', reason: '模拟失败', rider_id: 2 }],
        status: 'partial',
        success_count: 1,
        total_count: 2,
      }).text,
    ).toContain('R2：模拟失败');
  });

  it('轮询到终态后停止', async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce({
        done_count: 1,
        failed_count: 0,
        status: 'running',
        success_count: 0,
        total_count: 2,
      })
      .mockResolvedValueOnce({
        done_count: 2,
        failed_count: 1,
        status: 'partial',
        success_count: 1,
        total_count: 2,
      });
    const ticks: string[] = [];
    const job = await waitForCalcJob(9, load, {
      intervalMs: 0,
      onTick: (item) => {
        ticks.push(calcProgressText(item));
      },
    });
    expect(load).toHaveBeenCalledTimes(2);
    expect(job.status).toBe('partial');
    expect(ticks).toEqual(['正在计算 1/2', '正在计算 2/2']);
  });
});
