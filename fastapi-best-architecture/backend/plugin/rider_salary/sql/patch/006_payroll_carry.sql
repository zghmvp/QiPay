-- 实发最低为 0，欠款结转下期（纲要 §10 #32）。已有库执行一次即可
ALTER TABLE rs_payroll ADD COLUMN IF NOT EXISTS carry_in NUMERIC(12, 2) NOT NULL DEFAULT 0;
ALTER TABLE rs_payroll ADD COLUMN IF NOT EXISTS carry_out NUMERIC(12, 2) NOT NULL DEFAULT 0;
COMMENT ON COLUMN rs_payroll.carry_in IS '本期扣回的上期欠款（负数为多扣退回）';
COMMENT ON COLUMN rs_payroll.carry_out IS '结转下期的欠款';
