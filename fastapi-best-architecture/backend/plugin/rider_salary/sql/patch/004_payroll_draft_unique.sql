do $$
begin
    -- 重复草稿清理规则（只软删除，不物理删除，也不改成作废）：
    -- 同一 period_id、rider_id、kind 下，status 为 draft 且 deleted 为 0 的薪资单，
    -- 只保留 id 最大的一张（与取草稿时按 id 倒序一致）。
    -- 其余重复草稿：deleted 写成该行 id，deleted_time 写成当前时间。
    -- 这些草稿上 deleted 仍为 0 的明细同样软删除；日汇总按骑手和日期共用，不改。
    update rs_payroll_detail as detail
    set deleted = detail.id,
        deleted_time = now()
    where detail.deleted = 0
      and detail.payroll_id in (
          select stale.id
          from rs_payroll as stale
          where stale.deleted = 0
            and stale.status = 'draft'
            and exists (
                select 1
                from rs_payroll as newer
                where newer.period_id = stale.period_id
                  and newer.rider_id = stale.rider_id
                  and newer.kind = stale.kind
                  and newer.status = 'draft'
                  and newer.deleted = 0
                  and newer.id > stale.id
            )
      );

    update rs_payroll as stale
    set deleted = stale.id,
        deleted_time = now()
    where stale.deleted = 0
      and stale.status = 'draft'
      and exists (
          select 1
          from rs_payroll as newer
          where newer.period_id = stale.period_id
            and newer.rider_id = stale.rider_id
            and newer.kind = stale.kind
            and newer.status = 'draft'
            and newer.deleted = 0
            and newer.id > stale.id
      );
end
$$;

create unique index if not exists uq_rs_payroll_one_draft
    on rs_payroll (period_id, rider_id, kind)
    where status = 'draft' and deleted = 0;
