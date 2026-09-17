-- 操作日志加所属站点并回填（幂等）。现网执行一次。
-- 回填失败保持 NULL：站点负责人不可见（失败封闭）。

alter table rs_audit_log
    add column if not exists site_id bigint;

comment on column rs_audit_log.site_id is '所属站点；空表示全局目录或无法归属';

create index if not exists ix_rs_audit_log_site_id on rs_audit_log (site_id);

-- 1) 快照 JSON
update rs_audit_log
set site_id = (before ->> 'site_id')::bigint
where site_id is null
  and before ->> 'site_id' ~ '^[0-9]+$';

update rs_audit_log
set site_id = (after ->> 'site_id')::bigint
where site_id is null
  and after ->> 'site_id' ~ '^[0-9]+$';

-- 2) 动作特例：生成周期 / 导出订单 的 target_id 是站点 id
update rs_audit_log a
set site_id = s.id
from rs_site s
where a.site_id is null
  and a.action = '生成周期'
  and a.target_type = 'period'
  and a.target_id ~ '^[0-9]+$'
  and s.id = a.target_id::bigint
  and s.deleted = 0;

update rs_audit_log a
set site_id = s.id
from rs_site s
where a.site_id is null
  and a.action = '导出订单'
  and a.target_type = 'order'
  and a.target_id ~ '^[0-9]+$'
  and s.id = a.target_id::bigint
  and s.deleted = 0;

-- 3) 按对象表回填
update rs_audit_log a
set site_id = s.id
from rs_site s
where a.site_id is null
  and a.target_type = 'site'
  and a.target_id ~ '^[0-9]+$'
  and s.id = a.target_id::bigint
  and s.deleted = 0;

update rs_audit_log a
set site_id = r.site_id
from rs_rider r
where a.site_id is null
  and a.target_type = 'rider'
  and a.target_id ~ '^[0-9]+$'
  and r.id = a.target_id::bigint
  and r.deleted = 0;

update rs_audit_log a
set site_id = o.site_id
from rs_order o
where a.site_id is null
  and a.target_type = 'order'
  and a.target_id ~ '^[0-9]+$'
  and o.id = a.target_id::bigint
  and o.deleted = 0;

update rs_audit_log a
set site_id = adj.site_id
from rs_adjustment adj
where a.site_id is null
  and a.target_type = 'adjustment'
  and a.target_id ~ '^[0-9]+$'
  and adj.id = a.target_id::bigint
  and adj.deleted = 0;

update rs_audit_log a
set site_id = adv.site_id
from rs_advance adv
where a.site_id is null
  and a.target_type = 'advance'
  and a.target_id ~ '^[0-9]+$'
  and adv.id = a.target_id::bigint
  and adv.deleted = 0;

update rs_audit_log a
set site_id = p.site_id
from rs_settle_period p
where a.site_id is null
  and a.target_type = 'period'
  and a.target_id ~ '^[0-9]+$'
  and p.id = a.target_id::bigint
  and p.deleted = 0;

update rs_audit_log a
set site_id = p.site_id
from rs_payroll pay
join rs_settle_period p on p.id = pay.period_id and p.deleted = 0
where a.site_id is null
  and a.target_type = 'payroll'
  and a.target_id ~ '^[0-9]+$'
  and pay.id = a.target_id::bigint
  and pay.deleted = 0;

update rs_audit_log a
set site_id = b.site_id
from rs_import_batch b
where a.site_id is null
  and a.target_type = 'import_batch'
  and a.target_id ~ '^[0-9]+$'
  and b.id = a.target_id::bigint
  and b.deleted = 0;

update rs_audit_log a
set site_id = r.site_id
from rs_rider_plan_binding bind
join rs_rider r on r.id = bind.rider_id and r.deleted = 0
where a.site_id is null
  and a.target_type in ('rider_plan_binding', 'binding')
  and a.target_id ~ '^[0-9]+$'
  and bind.id = a.target_id::bigint
  and bind.deleted = 0;

update rs_audit_log a
set site_id = r.site_id
from rs_rider_employ_history h
join rs_rider r on r.id = h.rider_id and r.deleted = 0
where a.site_id is null
  and a.target_type = 'rider_employ_history'
  and a.target_id ~ '^[0-9]+$'
  and h.id = a.target_id::bigint
  and h.deleted = 0;
