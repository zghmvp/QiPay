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
    '查看骑手',
    'RiderSalaryRiderView',
    null,
    0,
    null,
    2,
    null,
    'rs:rider:view',
    1,
    0,
    1,
    '',
    null,
    (select id from sys_menu where name = 'RiderSalaryRider'),
    now(),
    null
where not exists (
    select 1 from sys_menu where perms = 'rs:rider:view' or name = 'RiderSalaryRiderView'
)
  and exists (select 1 from sys_menu where name = 'RiderSalaryRider');

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
    '查看奖惩',
    'RiderSalaryAdjustmentView',
    null,
    0,
    null,
    2,
    null,
    'rs:adjustment:view',
    1,
    0,
    1,
    '',
    null,
    (select id from sys_menu where name = 'RiderSalaryAdjustment'),
    now(),
    null
where not exists (
    select 1 from sys_menu where perms = 'rs:adjustment:view' or name = 'RiderSalaryAdjustmentView'
)
  and exists (select 1 from sys_menu where name = 'RiderSalaryAdjustment');

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
    '查看日标记',
    'RiderSalaryDayFlagView',
    null,
    0,
    null,
    2,
    null,
    'rs:dayflag:view',
    1,
    0,
    1,
    '',
    null,
    (select id from sys_menu where name = 'RiderSalaryDayFlag'),
    now(),
    null
where not exists (
    select 1 from sys_menu where perms = 'rs:dayflag:view' or name = 'RiderSalaryDayFlagView'
)
  and exists (select 1 from sys_menu where name = 'RiderSalaryDayFlag');

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
    '查看预支',
    'RiderSalaryAdvanceView',
    null,
    0,
    null,
    2,
    null,
    'rs:advance:view',
    1,
    0,
    1,
    '',
    null,
    (select id from sys_menu where name = 'RiderSalaryAdvance'),
    now(),
    null
where not exists (
    select 1 from sys_menu where perms = 'rs:advance:view' or name = 'RiderSalaryAdvanceView'
)
  and exists (select 1 from sys_menu where name = 'RiderSalaryAdvance');

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
    '查看公告',
    'RiderSalaryNoticeView',
    null,
    0,
    null,
    2,
    null,
    'rs:notice:view',
    1,
    0,
    1,
    '',
    null,
    (select id from sys_menu where name = 'RiderSalaryNotice'),
    now(),
    null
where not exists (
    select 1 from sys_menu where perms = 'rs:notice:view' or name = 'RiderSalaryNoticeView'
)
  and exists (select 1 from sys_menu where name = 'RiderSalaryNotice');

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
select r.id, m.id
from (
    values
        ('薪资管理员', 'rs:rider:view'),
        ('薪资管理员', 'rs:adjustment:view'),
        ('薪资管理员', 'rs:dayflag:view'),
        ('薪资管理员', 'rs:advance:view'),
        ('薪资管理员', 'rs:notice:view'),
        ('站点负责人', 'rs:rider:view'),
        ('站点负责人', 'rs:adjustment:view'),
        ('站点负责人', 'rs:dayflag:view'),
        ('站点负责人', 'rs:advance:view'),
        ('站点负责人', 'rs:notice:view'),
        ('站点副负责人', 'rs:rider:view'),
        ('站点副负责人', 'rs:adjustment:view'),
        ('站点副负责人', 'rs:dayflag:view'),
        ('站点副负责人', 'rs:advance:view'),
        ('站点副负责人', 'rs:notice:view')
) as spec(role_name, perm)
join sys_role r on r.name = spec.role_name and r.deleted = 0
join sys_menu m on m.perms = spec.perm
where not exists (
    select 1
    from sys_role_menu rm
    where rm.role_id = r.id
      and rm.menu_id = m.id
);
