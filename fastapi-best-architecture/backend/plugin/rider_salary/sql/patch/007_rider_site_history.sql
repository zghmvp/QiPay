-- 骑手站点履历（C2）：调岗后仍能把业务日归属到当时所在站点。已有库执行一次即可
CREATE TABLE IF NOT EXISTS rs_rider_site_history (
    id BIGSERIAL PRIMARY KEY,
    rider_id BIGINT NOT NULL,
    site_id BIGINT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,
    created_time TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_time TIMESTAMP WITH TIME ZONE,
    deleted INTEGER NOT NULL DEFAULT 0,
    deleted_time TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS ix_rs_rider_site_history_rider_date ON rs_rider_site_history (rider_id, start_date);
CREATE INDEX IF NOT EXISTS ix_rs_rider_site_history_site_id ON rs_rider_site_history (site_id);
COMMENT ON TABLE rs_rider_site_history IS '骑手站点履历表';
COMMENT ON COLUMN rs_rider_site_history.end_date IS '结束日期，空表示至今';
