-- 对抗循环 Cycle 2：周期算薪态（排队中/计算中）供算薪页刷新（幂等）

alter table rs_settle_period
    add column if not exists last_calc_status varchar(20);

alter table rs_settle_period
    add column if not exists last_calc_status_message text;

comment on column rs_settle_period.last_calc_status is '最近一次算薪态 queued/running/done/failed';
comment on column rs_settle_period.last_calc_status_message is '最近一次算薪态说明';
