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
    '骑手档案',
    'RiderSalaryRiderDetail',
    '/rider-salary/rider/:id',
    15,
    'lucide:user-round',
    1,
    '/plugins/rider-salary/views/rider/detail',
    null,
    1,
    0,
    1,
    '',
    null,
    (select id from sys_menu where name = 'RiderSalary'),
    now(),
    null
where not exists (select 1 from sys_menu where name = 'RiderSalaryRiderDetail')
  and exists (select 1 from sys_menu where name = 'RiderSalary');

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
    (select id from sys_menu where name = 'RiderSalaryRiderDetail')
where not exists (
    select 1
    from sys_role_menu
    where role_id = (select id from sys_role where name = '薪资管理员' and deleted = 0)
      and menu_id = (select id from sys_menu where name = 'RiderSalaryRiderDetail')
)
  and (select id from sys_role where name = '薪资管理员' and deleted = 0) is not null
  and (select id from sys_menu where name = 'RiderSalaryRiderDetail') is not null;

insert into sys_role_menu (role_id, menu_id)
select
    (select id from sys_role where name = '站点负责人' and deleted = 0),
    (select id from sys_menu where name = 'RiderSalaryRiderDetail')
where not exists (
    select 1
    from sys_role_menu
    where role_id = (select id from sys_role where name = '站点负责人' and deleted = 0)
      and menu_id = (select id from sys_menu where name = 'RiderSalaryRiderDetail')
)
  and (select id from sys_role where name = '站点负责人' and deleted = 0) is not null
  and (select id from sys_menu where name = 'RiderSalaryRiderDetail') is not null;

insert into sys_role_menu (role_id, menu_id)
select
    (select id from sys_role where name = '站点副负责人' and deleted = 0),
    (select id from sys_menu where name = 'RiderSalaryRiderDetail')
where not exists (
    select 1
    from sys_role_menu
    where role_id = (select id from sys_role where name = '站点副负责人' and deleted = 0)
      and menu_id = (select id from sys_menu where name = 'RiderSalaryRiderDetail')
)
  and (select id from sys_role where name = '站点副负责人' and deleted = 0) is not null
  and (select id from sys_menu where name = 'RiderSalaryRiderDetail') is not null;
