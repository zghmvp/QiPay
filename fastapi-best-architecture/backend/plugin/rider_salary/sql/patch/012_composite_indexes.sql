create index concurrently if not exists ix_rs_order_site_biz_date on rs_order (site_id, biz_date);

create index concurrently if not exists ix_rs_import_batch_site_dates on rs_import_batch (site_id, date_from, date_to);

create index concurrently if not exists ix_rs_audit_log_operate_time on rs_audit_log (operate_time);

create index concurrently if not exists ix_rs_payroll_detail_plan_version_id on rs_payroll_detail (plan_version_id);
