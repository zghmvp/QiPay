-- 骑手端菜单开关，以及后台「骑手端」菜单
CREATE TABLE IF NOT EXISTS rs_h5_menu (
    id BIGSERIAL PRIMARY KEY,
    site_id BIGINT NOT NULL,
    show_adjustments BOOLEAN NOT NULL DEFAULT TRUE,
    show_advance BOOLEAN NOT NULL DEFAULT TRUE,
    show_notices BOOLEAN NOT NULL DEFAULT TRUE,
    show_plan BOOLEAN NOT NULL DEFAULT TRUE,
    show_home BOOLEAN NOT NULL DEFAULT TRUE,
    show_home_pay BOOLEAN NOT NULL DEFAULT TRUE,
    show_day_amount BOOLEAN NOT NULL DEFAULT TRUE,
    show_estimate_net BOOLEAN NOT NULL DEFAULT TRUE,
    show_advance_inflight BOOLEAN NOT NULL DEFAULT TRUE,
    created_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_time TIMESTAMPTZ,
    deleted BIGINT NOT NULL DEFAULT 0,
    deleted_time TIMESTAMPTZ,
    CONSTRAINT uk_rs_h5_menu_site_deleted UNIQUE (site_id, deleted)
);

COMMENT ON TABLE rs_h5_menu IS '骑手端菜单开关';
COMMENT ON COLUMN rs_h5_menu.site_id IS '站点 ID，0 表示全局默认';
COMMENT ON COLUMN rs_h5_menu.show_adjustments IS '是否开放奖惩';
COMMENT ON COLUMN rs_h5_menu.show_advance IS '是否开放预支';
COMMENT ON COLUMN rs_h5_menu.show_notices IS '是否开放公告';
COMMENT ON COLUMN rs_h5_menu.show_plan IS '是否开放当前方案';
COMMENT ON COLUMN rs_h5_menu.show_home IS '是否开放首页';
COMMENT ON COLUMN rs_h5_menu.show_home_pay IS '是否显示首页工资';
COMMENT ON COLUMN rs_h5_menu.show_day_amount IS '是否显示当日金额';
COMMENT ON COLUMN rs_h5_menu.show_estimate_net IS '是否显示预估实发';
COMMENT ON COLUMN rs_h5_menu.show_advance_inflight IS '是否显示在途占用';

UPDATE sys_menu SET sort = 16 WHERE id = 91014 AND title = '操作日志';

INSERT INTO sys_menu (id, title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
SELECT 91016, '骑手端', 'RiderSalaryH5Menu', '/rider-salary/h5-menu', 14, 'lucide:smartphone', 1, '/plugins/rider-salary/views/h5-menu/index', null, 1, 1, 1, '', null, 91000, now(), null
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE id = 91016);

INSERT INTO sys_menu (id, title, name, path, sort, icon, type, component, perms, status, display, cache, link, remark, parent_id, created_time, updated_time)
SELECT 91150, '管理骑手端', 'RiderSalaryH5MenuEdit', null, 0, null, 2, null, 'rs:h5:menu', 1, 0, 1, '', null, 91016, now(), null
WHERE NOT EXISTS (SELECT 1 FROM sys_menu WHERE id = 91150);

INSERT INTO sys_role_menu (id, role_id, menu_id)
SELECT 93157, 92001, 91016
WHERE NOT EXISTS (SELECT 1 FROM sys_role_menu WHERE role_id = 92001 AND menu_id = 91016);

INSERT INTO sys_role_menu (id, role_id, menu_id)
SELECT 93158, 92002, 91016
WHERE NOT EXISTS (SELECT 1 FROM sys_role_menu WHERE role_id = 92002 AND menu_id = 91016);

INSERT INTO sys_role_menu (id, role_id, menu_id)
SELECT 93159, 92003, 91016
WHERE NOT EXISTS (SELECT 1 FROM sys_role_menu WHERE role_id = 92003 AND menu_id = 91016);

INSERT INTO sys_role_menu (id, role_id, menu_id)
SELECT 93160, 92001, 91150
WHERE NOT EXISTS (SELECT 1 FROM sys_role_menu WHERE role_id = 92001 AND menu_id = 91150);

INSERT INTO sys_role_menu (id, role_id, menu_id)
SELECT 93161, 92002, 91150
WHERE NOT EXISTS (SELECT 1 FROM sys_role_menu WHERE role_id = 92002 AND menu_id = 91150);

INSERT INTO sys_role_menu (id, role_id, menu_id)
SELECT 93162, 92003, 91150
WHERE NOT EXISTS (SELECT 1 FROM sys_role_menu WHERE role_id = 92003 AND menu_id = 91150);
