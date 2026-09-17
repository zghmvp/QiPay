alter table rs_site add column if not exists monthly_advance_limit integer not null default 1;
comment on column rs_site.monthly_advance_limit is '每月可预支次数（0=本站禁止预支）';
