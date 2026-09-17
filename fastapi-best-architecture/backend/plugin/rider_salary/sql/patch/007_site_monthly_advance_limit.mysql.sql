alter table rs_site add column if not exists monthly_advance_limit int not null default 1 comment '每月可预支次数（0=本站禁止预支）';
