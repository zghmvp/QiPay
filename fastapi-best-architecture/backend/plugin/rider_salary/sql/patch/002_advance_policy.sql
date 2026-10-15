-- 预支规则：按站点或全局控制可预支额度、次数和资格
CREATE TABLE IF NOT EXISTS rs_advance_policy (
    id BIGSERIAL PRIMARY KEY,
    site_id BIGINT NOT NULL,
    amount_mode VARCHAR(20) NOT NULL DEFAULT 'percent',
    percent NUMERIC(5, 2) NOT NULL DEFAULT 50,
    fixed_amount NUMERIC(12, 2) NOT NULL DEFAULT 3000,
    max_amount NUMERIC(12, 2),
    monthly_max_count INTEGER NOT NULL DEFAULT 2,
    min_tenure_days INTEGER NOT NULL DEFAULT 7,
    min_completed_orders INTEGER NOT NULL DEFAULT 1,
    min_amount NUMERIC(12, 2) NOT NULL DEFAULT 1,
    created_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_time TIMESTAMPTZ,
    deleted BIGINT NOT NULL DEFAULT 0,
    deleted_time TIMESTAMPTZ,
    CONSTRAINT uk_rs_advance_policy_site_deleted UNIQUE (site_id, deleted)
);

COMMENT ON TABLE rs_advance_policy IS '预支规则';
COMMENT ON COLUMN rs_advance_policy.site_id IS '站点 ID，0 表示全局默认';
COMMENT ON COLUMN rs_advance_policy.amount_mode IS '额度方式：percent 按预估实发百分比，fixed 固定额度';
COMMENT ON COLUMN rs_advance_policy.percent IS '预估实发百分比';
COMMENT ON COLUMN rs_advance_policy.fixed_amount IS '固定额度';
COMMENT ON COLUMN rs_advance_policy.max_amount IS '绝对封顶，空表示不额外封顶';
COMMENT ON COLUMN rs_advance_policy.monthly_max_count IS '每月预支次数上限';
COMMENT ON COLUMN rs_advance_policy.min_tenure_days IS '入职满多少天才能预支';
COMMENT ON COLUMN rs_advance_policy.min_completed_orders IS '当前周期至少完成订单数';
COMMENT ON COLUMN rs_advance_policy.min_amount IS '单笔最低金额';
