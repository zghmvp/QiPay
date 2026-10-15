-- 去掉现有数据判断不了的预支条件：预估实发门槛、锁账后禁止
ALTER TABLE rs_advance_policy DROP COLUMN IF EXISTS min_estimate_net;
ALTER TABLE rs_advance_policy DROP COLUMN IF EXISTS block_when_locked;
