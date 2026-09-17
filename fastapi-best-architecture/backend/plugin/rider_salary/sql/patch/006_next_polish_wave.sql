-- 下一波抛光：周期失败清单列 + 天气科目下线（幂等）
-- 已有库执行一次即可。有方案项引用天气科目时只停用，不 DELETE。

alter table rs_settle_period
    add column if not exists last_calc_failures json;

update rs_subject
set status = 'disable',
    remark = coalesce(
        nullif(remark, ''),
        '已下线：引擎无天气/大促字段，请改用节假日或周末条件'
    ),
    updated_time = now()
where code in ('BONUS_BAD_WEATHER', 'BONUS_HIGH_TEMP', 'BONUS_PROMO')
  and deleted = 0
  and status <> 'disable';
