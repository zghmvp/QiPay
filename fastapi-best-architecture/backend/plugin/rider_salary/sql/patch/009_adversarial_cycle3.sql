-- 对抗循环 Cycle 3：最近一次算薪成功骑手 ID，供算薪页 ② 本次成功表 F5 还原（幂等）

alter table rs_settle_period
    add column if not exists last_calc_success_ids json;

comment on column rs_settle_period.last_calc_success_ids is '最近一次算薪成功骑手 ID 列表';
