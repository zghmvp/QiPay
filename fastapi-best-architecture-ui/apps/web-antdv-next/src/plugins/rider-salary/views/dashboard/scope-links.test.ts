import { describe, expect, it } from 'vitest';

import { noPlanBindingTarget, noPlanViewAllTarget } from './scope-links';

describe('no-plan dashboard targets', () => {
  it('该行走档案绑定时间轴，不是日历', () => {
    const target = noPlanBindingTarget(88, 3, '2026-09');
    expect(target.path).toBe('/rider-salary/rider/88');
    expect(target.query.tab).toBe('binding');
    expect(target.path).not.toContain('calendar');
  });

  it('查看全部走骑手名单 from=no_plan，不是空日历', () => {
    const target = noPlanViewAllTarget(3, '2026-09');
    expect(target.path).toBe('/rider-salary/rider');
    expect(target.query.from).toBe('no_plan');
    expect(target.query.site_id).toBe('3');
    expect(target.path).not.toContain('calendar');
  });
});
