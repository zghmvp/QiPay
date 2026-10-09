create extension if not exists btree_gist;

do $$
declare
    def text;
begin
    select pg_get_constraintdef(oid)
    into def
    from pg_constraint
    where conname = 'ex_rs_settle_period_no_overlap'
      and conrelid = 'rs_settle_period'::regclass;

    if def is not null and position('rider_id' in def) = 0 then
        alter table rs_settle_period drop constraint ex_rs_settle_period_no_overlap;
        def := null;
    end if;

    if def is null then
        alter table rs_settle_period
            add constraint ex_rs_settle_period_no_overlap
            exclude using gist (
                site_id with =,
                rider_id with =,
                daterange(start_date, end_date, '[]') with &&
            )
            where (deleted = 0);
    end if;
end
$$;
