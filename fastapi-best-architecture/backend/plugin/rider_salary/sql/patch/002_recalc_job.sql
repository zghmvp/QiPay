-- 插件内轻量重算任务表（导入后可观测 / 本站本月批量重算）
-- 幂等：已存在则跳过
create table if not exists rs_recalc_job (
    id bigserial primary key,
    site_id bigint not null,
    source varchar(20) not null default 'import_batch',
    source_id bigint,
    status varchar(20) not null default 'queued',
    message text,
    month varchar(7),
    total_periods integer not null default 0,
    done_periods integer not null default 0,
    rider_count integer not null default 0,
    operator_id bigint not null default 0,
    started_time timestamptz,
    finished_time timestamptz,
    payload json,
    created_time timestamptz not null default now(),
    updated_time timestamptz,
    deleted smallint not null default 0,
    deleted_time timestamptz
);

create index if not exists ix_rs_recalc_job_site_id on rs_recalc_job (site_id);
create index if not exists ix_rs_recalc_job_source on rs_recalc_job (source);
create index if not exists ix_rs_recalc_job_source_id on rs_recalc_job (source_id);
create index if not exists ix_rs_recalc_job_status on rs_recalc_job (status);
create index if not exists ix_rs_recalc_job_operator_id on rs_recalc_job (operator_id);
