-- 周期算薪独立隐藏页（91018）；三角色绑定；幂等
-- 已有库执行一次即可

insert into sys_menu (id, title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
select 91018, '周期算薪', 'RiderSalaryPeriodCalculate', '/rider-salary/period/:id/calculate', 17, 'lucide:calculator', 1, '/plugins/rider-salary/views/period/calculate', null, 1, 0, 1, '', null, 91000, now(), null
where not exists (select 1 from sys_menu where id = 91018);

insert into sys_role_menu (role_id, menu_id)
select 92001, 91018
where not exists (select 1 from sys_role_menu where role_id = 92001 and menu_id = 91018);

insert into sys_role_menu (role_id, menu_id)
select 92002, 91018
where not exists (select 1 from sys_role_menu where role_id = 92002 and menu_id = 91018);

insert into sys_role_menu (role_id, menu_id)
select 92003, 91018
where not exists (select 1 from sys_role_menu where role_id = 92003 and menu_id = 91018);
