-- 骑手端增加首页、工资和预支数字开关。已有行默认全部开放。
ALTER TABLE rs_h5_menu ADD COLUMN IF NOT EXISTS show_home BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE rs_h5_menu ADD COLUMN IF NOT EXISTS show_home_pay BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE rs_h5_menu ADD COLUMN IF NOT EXISTS show_day_amount BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE rs_h5_menu ADD COLUMN IF NOT EXISTS show_estimate_net BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE rs_h5_menu ADD COLUMN IF NOT EXISTS show_advance_inflight BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN rs_h5_menu.show_home IS '是否开放首页';
COMMENT ON COLUMN rs_h5_menu.show_home_pay IS '是否显示首页工资';
COMMENT ON COLUMN rs_h5_menu.show_day_amount IS '是否显示当日金额';
COMMENT ON COLUMN rs_h5_menu.show_estimate_net IS '是否显示预估实发';
COMMENT ON COLUMN rs_h5_menu.show_advance_inflight IS '是否显示在途占用';
