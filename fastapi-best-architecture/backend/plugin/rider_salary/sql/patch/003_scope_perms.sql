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
    '全站范围',
    'RiderSalaryScopeAll',
    null,
    0,
    null,
    2,
    null,
    'rs:scope:all',
    1,
    0,
    1,
    '',
    null,
    (select id from sys_menu where name = 'RiderSalarySite'),
    now(),
    null
where not exists (
    select 1 from sys_menu where perms = 'rs:scope:all' or name = 'RiderSalaryScopeAll'
)
  and exists (select 1 from sys_menu where name = 'RiderSalarySite');

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
    (select id from sys_menu where perms = 'rs:scope:all')
where not exists (
    select 1
    from sys_role_menu
    where role_id = (select id from sys_role where name = '薪资管理员' and deleted = 0)
      and menu_id = (select id from sys_menu where perms = 'rs:scope:all')
)
  and (select id from sys_role where name = '薪资管理员' and deleted = 0) is not null
  and (select id from sys_menu where perms = 'rs:scope:all') is not null;

create table if not exists rs_role_anchor (
    id bigserial primary key,
    role_key varchar(64) not null,
    role_id bigint not null,
    created_time timestamptz not null default now(),
    updated_time timestamptz,
    deleted bigint not null default 0,
    deleted_time timestamptz
);

create unique index if not exists uk_rs_role_anchor_role_key_deleted on rs_role_anchor (role_key, deleted);

do $$
begin
    comment on table rs_role_anchor is '角色种子锚点表';
    comment on column rs_role_anchor.id is '主键 ID';
    comment on column rs_role_anchor.role_key is '业务键';
    comment on column rs_role_anchor.role_id is '角色 ID';
    comment on column rs_role_anchor.created_time is '创建时间';
    comment on column rs_role_anchor.updated_time is '更新时间';
    comment on column rs_role_anchor.deleted is '是否已删除（0：否；id：是）';
    comment on column rs_role_anchor.deleted_time is '删除时间';
end
$$;

select setval(
    pg_get_serial_sequence('rs_role_anchor', 'id'),
    greatest(
        (select coalesce(max(id), 1) from rs_role_anchor),
        coalesce(
            (
                select s.last_value
                from pg_sequences s
                where s.schemaname = split_part(pg_get_serial_sequence('rs_role_anchor', 'id'), '.', 1)
                  and s.sequencename = split_part(pg_get_serial_sequence('rs_role_anchor', 'id'), '.', 2)
            ),
            1
        )
    ),
    true
)
where pg_get_serial_sequence('rs_role_anchor', 'id') is not null;

insert into rs_role_anchor (id, role_key, role_id, created_time, updated_time)
select
    coalesce(
        (
            select nextval(seq_name.seq)
            from (select pg_get_serial_sequence('rs_role_anchor', 'id') as seq) as seq_name
            where seq_name.seq is not null
        ),
        (select coalesce(max(id), 0) + 1 from rs_role_anchor)
    ),
    'rs-role:rider',
    coalesce(
        (
            select r.id
            from sys_role r
            join sys_role_menu rm on rm.role_id = r.id
            join sys_menu m on m.id = rm.menu_id
            where r.deleted = 0
              and (m.perms = 'rs:scope:rider' or m.name = 'RiderSalaryScopeRider')
            order by r.id
            limit 1
        ),
        (
            select r.id
            from sys_role r
            where r.deleted = 0
              and r.name = '骑手'
            order by r.id
            limit 1
        )
    ),
    now(),
    null
where not exists (
    select 1 from rs_role_anchor where role_key = 'rs-role:rider' and deleted = 0
)
  and coalesce(
        (
            select r.id
            from sys_role r
            join sys_role_menu rm on rm.role_id = r.id
            join sys_menu m on m.id = rm.menu_id
            where r.deleted = 0
              and (m.perms = 'rs:scope:rider' or m.name = 'RiderSalaryScopeRider')
            order by r.id
            limit 1
        ),
        (
            select r.id
            from sys_role r
            where r.deleted = 0
              and r.name = '骑手'
            order by r.id
            limit 1
        )
    ) is not null;

do $$
begin
    delete from sys_role_menu
    where menu_id in (
        select id from sys_menu
        where perms = 'rs:scope:rider' or name = 'RiderSalaryScopeRider'
    );
    delete from sys_menu
    where perms = 'rs:scope:rider' or name = 'RiderSalaryScopeRider';
end
$$;
