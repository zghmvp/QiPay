alter table if exists rs_audit_log add column if not exists site_id bigint;

do $$
begin
    if to_regclass('public.rs_audit_log') is null then
        return;
    end if;

    comment on column rs_audit_log.site_id is '站点 ID';
    create index if not exists ix_rs_audit_log_site_id on rs_audit_log (site_id);

    -- 日标记、生成周期、导出订单的对象 ID 就是站点 ID。只填仍然为空的行，重复执行不改已回填的值。
    update rs_audit_log
    set site_id = target_id::bigint
    where site_id is null
      and target_id ~ '^[0-9]+$'
      and (
          target_type in ('site', 'day_flag')
          or (target_type = 'period' and action = '生成周期')
          or (target_type = 'order' and action = '导出订单')
      );

    if to_regclass('public.rs_rider') is not null then
        update rs_audit_log as log
        set site_id = rider.site_id
        from rs_rider as rider
        where log.site_id is null
          and log.target_type = 'rider'
          and log.target_id ~ '^[0-9]+$'
          and rider.id = log.target_id::bigint;
    end if;

    if to_regclass('public.rs_rider') is not null and to_regclass('public.rs_rider_plan_binding') is not null then
        update rs_audit_log as log
        set site_id = rider.site_id
        from rs_rider_plan_binding as binding
        join rs_rider as rider on rider.id = binding.rider_id
        where log.site_id is null
          and log.target_type in ('rider_plan_binding', 'binding')
          and log.target_id ~ '^[0-9]+$'
          and binding.id = log.target_id::bigint;
    end if;

    if to_regclass('public.rs_rider') is not null and to_regclass('public.rs_rider_employ_history') is not null then
        update rs_audit_log as log
        set site_id = rider.site_id
        from rs_rider_employ_history as history
        join rs_rider as rider on rider.id = history.rider_id
        where log.site_id is null
          and log.target_type = 'rider_employ_history'
          and log.target_id ~ '^[0-9]+$'
          and history.id = log.target_id::bigint;
    end if;

    if to_regclass('public.rs_order') is not null then
        update rs_audit_log as log
        set site_id = item.site_id
        from rs_order as item
        where log.site_id is null
          and log.target_type = 'order'
          and log.target_id ~ '^[0-9]+$'
          and item.id = log.target_id::bigint;
    end if;

    if to_regclass('public.rs_payroll') is not null and to_regclass('public.rs_settle_period') is not null then
        update rs_audit_log as log
        set site_id = period.site_id
        from rs_payroll as payroll
        join rs_settle_period as period on period.id = payroll.period_id
        where log.site_id is null
          and log.target_type = 'payroll'
          and log.target_id ~ '^[0-9]+$'
          and payroll.id = log.target_id::bigint;
    end if;

    if to_regclass('public.rs_settle_period') is not null then
        update rs_audit_log as log
        set site_id = period.site_id
        from rs_settle_period as period
        where log.site_id is null
          and log.target_type = 'period'
          and log.target_id ~ '^[0-9]+$'
          and period.id = log.target_id::bigint;
    end if;

    if to_regclass('public.rs_import_batch') is not null then
        update rs_audit_log as log
        set site_id = batch.site_id
        from rs_import_batch as batch
        where log.site_id is null
          and log.target_type = 'import_batch'
          and log.target_id ~ '^[0-9]+$'
          and batch.id = log.target_id::bigint;
    end if;

    if to_regclass('public.rs_advance') is not null then
        update rs_audit_log as log
        set site_id = item.site_id
        from rs_advance as item
        where log.site_id is null
          and log.target_type = 'advance'
          and log.target_id ~ '^[0-9]+$'
          and item.id = log.target_id::bigint;
    end if;

    if to_regclass('public.rs_adjustment') is not null then
        update rs_audit_log as log
        set site_id = item.site_id
        from rs_adjustment as item
        where log.site_id is null
          and log.target_type = 'adjustment'
          and log.target_id ~ '^[0-9]+$'
          and item.id = log.target_id::bigint;
    end if;

    if to_regclass('public.rs_notice') is not null then
        update rs_audit_log as log
        set site_id = notice.site_id
        from rs_notice as notice
        where log.site_id is null
          and log.target_type = 'notice'
          and log.target_id ~ '^[0-9]+$'
          and notice.id = log.target_id::bigint
          and notice.site_id is not null;
    end if;
end
$$;
