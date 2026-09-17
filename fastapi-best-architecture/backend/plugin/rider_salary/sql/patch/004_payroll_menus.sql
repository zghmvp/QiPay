-- 薪资结果列表 + 隐藏明细页；查看权限挂到列表菜单；日历/预支排序后移
-- 已有库幂等执行一次即可

insert into sys_menu (id, title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
select 91016, '薪资结果', 'RiderSalaryPayroll', '/rider-salary/payroll', 11, 'lucide:wallet', 1, '/plugins/rider-salary/views/payroll/index', null, 1, 1, 1, '', null, 91000, now(), null
where not exists (select 1 from sys_menu where id = 91016);

insert into sys_menu (id, title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
select 91017, '薪资明细', 'RiderSalaryPayrollDetail', '/rider-salary/payroll/:id', 16, 'lucide:file-text', 1, '/plugins/rider-salary/views/payroll/detail', null, 1, 0, 1, '', null, 91000, now(), null
where not exists (select 1 from sys_menu where id = 91017);

update sys_menu set parent_id = 91016, updated_time = now()
where id = 91137 and perms = 'rs:payroll:view';

update sys_menu set sort = 12, updated_time = now() where id = 91011 and path = '/rider-salary/calendar';
update sys_menu set sort = 13, updated_time = now() where id = 91012 and path = '/rider-salary/advance';

insert into sys_role_menu (role_id, menu_id)
select 92001, 91016
where not exists (select 1 from sys_role_menu where role_id = 92001 and menu_id = 91016);

insert into sys_role_menu (role_id, menu_id)
select 92002, 91016
where not exists (select 1 from sys_role_menu where role_id = 92002 and menu_id = 91016);

insert into sys_role_menu (role_id, menu_id)
select 92003, 91016
where not exists (select 1 from sys_role_menu where role_id = 92003 and menu_id = 91016);

insert into sys_role_menu (role_id, menu_id)
select 92001, 91017
where not exists (select 1 from sys_role_menu where role_id = 92001 and menu_id = 91017);

insert into sys_role_menu (role_id, menu_id)
select 92002, 91017
where not exists (select 1 from sys_role_menu where role_id = 92002 and menu_id = 91017);

insert into sys_role_menu (role_id, menu_id)
select 92003, 91017
where not exists (select 1 from sys_role_menu where role_id = 92003 and menu_id = 91017);
