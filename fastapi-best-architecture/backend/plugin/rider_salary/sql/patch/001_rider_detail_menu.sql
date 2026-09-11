-- 骑手档案页（隐藏菜单路由），已有库执行一次即可
insert into sys_menu (id, title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
select 91015, '骑手档案', 'RiderSalaryRiderDetail', '/rider-salary/rider/:id', 15, 'lucide:user-round', 1, '/plugins/rider-salary/views/rider/detail', null, 1, 0, 1, '', null, 91000, now(), null
where not exists (select 1 from sys_menu where id = 91015);

insert into sys_role_menu (role_id, menu_id)
select 92001, 91015
where not exists (select 1 from sys_role_menu where role_id = 92001 and menu_id = 91015);

insert into sys_role_menu (role_id, menu_id)
select 92002, 91015
where not exists (select 1 from sys_role_menu where role_id = 92002 and menu_id = 91015);

insert into sys_role_menu (role_id, menu_id)
select 92003, 91015
where not exists (select 1 from sys_role_menu where role_id = 92003 and menu_id = 91015);
