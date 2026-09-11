delete from sys_role_menu
where role_id in (select id from sys_role where name in ('薪资管理员', '站点负责人', '站点副负责人', '骑手'))
   or menu_id in (select id from sys_menu where name like 'RiderSalary%');

delete from sys_user_role
where role_id in (select id from sys_role where name in ('薪资管理员', '站点负责人', '站点副负责人', '骑手'));

delete from sys_menu where name like 'RiderSalary%';

delete from sys_role where name in ('薪资管理员', '站点负责人', '站点副负责人', '骑手');

drop table if exists rs_payroll_detail;
drop table if exists rs_payroll_daily;
drop table if exists rs_payroll;
drop table if exists rs_adjustment;
drop table if exists rs_order;
drop table if exists rs_import_batch;
drop table if exists rs_advance;
drop table if exists rs_day_flag;
drop table if exists rs_plan_item;
drop table if exists rs_rider_plan_binding;
drop table if exists rs_plan_version;
drop table if exists rs_plan;
drop table if exists rs_rider_employ_history;
drop table if exists rs_site_manager;
drop table if exists rs_notice;
drop table if exists rs_audit_log;
drop table if exists rs_settle_period;
drop table if exists rs_subject;
drop table if exists rs_rider;
drop table if exists rs_site;

select setval(pg_get_serial_sequence('sys_menu', 'id'), coalesce(max(id), 0) + 1, true) from sys_menu;
select setval(pg_get_serial_sequence('sys_role', 'id'), coalesce(max(id), 0) + 1, true) from sys_role;
select setval(pg_get_serial_sequence('sys_role_menu', 'id'), coalesce(max(id), 0) + 1, true) from sys_role_menu;
