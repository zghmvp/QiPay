do $$
begin
    if to_regclass('public.rs_notice') is null then
        return;
    end if;
    if not exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'rs_notice'
          and column_name = 'is_top'
    ) then
        alter table rs_notice
            add column is_top boolean not null default false;
    end if;
    comment on column rs_notice.is_top is '是否置顶';
end
$$;

select setval(
    pg_get_serial_sequence('sys_menu', 'id'),
    greatest(
        (select coalesce(max(id), 1) from sys_menu),
        coalesce(
            (
                select s.last_value
                from pg_sequences s
                where s.schemaname = split_part(pg_get_serial_sequence('sys_menu', 'id'), '.', 1)
                  and s.sequencename = split_part(pg_get_serial_sequence('sys_menu', 'id'), '.', 2)
            ),
            1
        )
    ),
    true
)
where pg_get_serial_sequence('sys_menu', 'id') is not null;

insert into sys_menu (id, title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
select
    coalesce(
        (
            select nextval(seq_name.seq)
            from (select pg_get_serial_sequence('sys_menu', 'id') as seq) as seq_name
            where seq_name.seq is not null
        ),
        (select coalesce(max(id), 0) + 1 from sys_menu)
    ),
    '成本报表',
    'RiderSalaryReport',
    '/rider-salary/report',
    16,
    'lucide:pie-chart',
    1,
    '/plugins/rider-salary/views/report/index',
    null,
    1,
    1,
    1,
    '',
    null,
    (select id from sys_menu where name = 'RiderSalary'),
    now(),
    null
where not exists (select 1 from sys_menu where name = 'RiderSalaryReport')
  and exists (select 1 from sys_menu where name = 'RiderSalary');

insert into sys_menu (id, title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
select
    coalesce(
        (
            select nextval(seq_name.seq)
            from (select pg_get_serial_sequence('sys_menu', 'id') as seq) as seq_name
            where seq_name.seq is not null
        ),
        (select coalesce(max(id), 0) + 1 from sys_menu)
    ),
    '导出日志',
    'RiderSalaryAuditExport',
    null,
    0,
    null,
    2,
    null,
    'rs:audit:export',
    1,
    0,
    1,
    '',
    null,
    (select id from sys_menu where name = 'RiderSalaryAudit'),
    now(),
    null
where not exists (select 1 from sys_menu where perms = 'rs:audit:export')
  and exists (select 1 from sys_menu where name = 'RiderSalaryAudit');

insert into sys_menu (id, title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
select
    coalesce(
        (
            select nextval(seq_name.seq)
            from (select pg_get_serial_sequence('sys_menu', 'id') as seq) as seq_name
            where seq_name.seq is not null
        ),
        (select coalesce(max(id), 0) + 1 from sys_menu)
    ),
    '查看成本',
    'RiderSalaryReportView',
    null,
    0,
    null,
    2,
    null,
    'rs:report:view',
    1,
    0,
    1,
    '',
    null,
    (select id from sys_menu where name = 'RiderSalaryReport'),
    now(),
    null
where not exists (select 1 from sys_menu where perms = 'rs:report:view')
  and exists (select 1 from sys_menu where name = 'RiderSalaryReport');

select setval(
    pg_get_serial_sequence('sys_role_menu', 'id'),
    greatest(
        (select coalesce(max(id), 1) from sys_role_menu),
        coalesce(
            (
                select s.last_value
                from pg_sequences s
                where s.schemaname = split_part(pg_get_serial_sequence('sys_role_menu', 'id'), '.', 1)
                  and s.sequencename = split_part(pg_get_serial_sequence('sys_role_menu', 'id'), '.', 2)
            ),
            1
        )
    ),
    true
)
where pg_get_serial_sequence('sys_role_menu', 'id') is not null;

insert into sys_role_menu (role_id, menu_id)
select
    (select id from sys_role where name = '薪资管理员' and deleted = 0),
    (select id from sys_menu where name = 'RiderSalaryReport')
where not exists (
    select 1
    from sys_role_menu
    where role_id = (select id from sys_role where name = '薪资管理员' and deleted = 0)
      and menu_id = (select id from sys_menu where name = 'RiderSalaryReport')
)
  and (select id from sys_role where name = '薪资管理员' and deleted = 0) is not null
  and (select id from sys_menu where name = 'RiderSalaryReport') is not null;

insert into sys_role_menu (role_id, menu_id)
select
    (select id from sys_role where name = '站点负责人' and deleted = 0),
    (select id from sys_menu where name = 'RiderSalaryReport')
where not exists (
    select 1
    from sys_role_menu
    where role_id = (select id from sys_role where name = '站点负责人' and deleted = 0)
      and menu_id = (select id from sys_menu where name = 'RiderSalaryReport')
)
  and (select id from sys_role where name = '站点负责人' and deleted = 0) is not null
  and (select id from sys_menu where name = 'RiderSalaryReport') is not null;

insert into sys_role_menu (role_id, menu_id)
select
    (select id from sys_role where name = '站点副负责人' and deleted = 0),
    (select id from sys_menu where name = 'RiderSalaryReport')
where not exists (
    select 1
    from sys_role_menu
    where role_id = (select id from sys_role where name = '站点副负责人' and deleted = 0)
      and menu_id = (select id from sys_menu where name = 'RiderSalaryReport')
)
  and (select id from sys_role where name = '站点副负责人' and deleted = 0) is not null
  and (select id from sys_menu where name = 'RiderSalaryReport') is not null;

insert into sys_role_menu (role_id, menu_id)
select
    (select id from sys_role where name = '薪资管理员' and deleted = 0),
    (select id from sys_menu where perms = 'rs:audit:export')
where not exists (
    select 1
    from sys_role_menu
    where role_id = (select id from sys_role where name = '薪资管理员' and deleted = 0)
      and menu_id = (select id from sys_menu where perms = 'rs:audit:export')
)
  and (select id from sys_role where name = '薪资管理员' and deleted = 0) is not null
  and (select id from sys_menu where perms = 'rs:audit:export') is not null;

insert into sys_role_menu (role_id, menu_id)
select
    (select id from sys_role where name = '站点负责人' and deleted = 0),
    (select id from sys_menu where perms = 'rs:audit:export')
where not exists (
    select 1
    from sys_role_menu
    where role_id = (select id from sys_role where name = '站点负责人' and deleted = 0)
      and menu_id = (select id from sys_menu where perms = 'rs:audit:export')
)
  and (select id from sys_role where name = '站点负责人' and deleted = 0) is not null
  and (select id from sys_menu where perms = 'rs:audit:export') is not null;

insert into sys_role_menu (role_id, menu_id)
select
    (select id from sys_role where name = '站点副负责人' and deleted = 0),
    (select id from sys_menu where perms = 'rs:audit:export')
where not exists (
    select 1
    from sys_role_menu
    where role_id = (select id from sys_role where name = '站点副负责人' and deleted = 0)
      and menu_id = (select id from sys_menu where perms = 'rs:audit:export')
)
  and (select id from sys_role where name = '站点副负责人' and deleted = 0) is not null
  and (select id from sys_menu where perms = 'rs:audit:export') is not null;

insert into sys_role_menu (role_id, menu_id)
select
    (select id from sys_role where name = '薪资管理员' and deleted = 0),
    (select id from sys_menu where perms = 'rs:report:view')
where not exists (
    select 1
    from sys_role_menu
    where role_id = (select id from sys_role where name = '薪资管理员' and deleted = 0)
      and menu_id = (select id from sys_menu where perms = 'rs:report:view')
)
  and (select id from sys_role where name = '薪资管理员' and deleted = 0) is not null
  and (select id from sys_menu where perms = 'rs:report:view') is not null;

insert into sys_role_menu (role_id, menu_id)
select
    (select id from sys_role where name = '站点负责人' and deleted = 0),
    (select id from sys_menu where perms = 'rs:report:view')
where not exists (
    select 1
    from sys_role_menu
    where role_id = (select id from sys_role where name = '站点负责人' and deleted = 0)
      and menu_id = (select id from sys_menu where perms = 'rs:report:view')
)
  and (select id from sys_role where name = '站点负责人' and deleted = 0) is not null
  and (select id from sys_menu where perms = 'rs:report:view') is not null;

insert into sys_role_menu (role_id, menu_id)
select
    (select id from sys_role where name = '站点副负责人' and deleted = 0),
    (select id from sys_menu where perms = 'rs:report:view')
where not exists (
    select 1
    from sys_role_menu
    where role_id = (select id from sys_role where name = '站点副负责人' and deleted = 0)
      and menu_id = (select id from sys_menu where perms = 'rs:report:view')
)
  and (select id from sys_role where name = '站点副负责人' and deleted = 0) is not null
  and (select id from sys_menu where perms = 'rs:report:view') is not null;
