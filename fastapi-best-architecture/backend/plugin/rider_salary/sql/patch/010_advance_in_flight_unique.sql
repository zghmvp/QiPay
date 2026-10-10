do $$
begin
    if exists (
        select 1
        from rs_advance
        where status in ('pending', 'to_pay')
          and deleted = 0
        group by rider_id
        having count(*) > 1
    ) then
        raise exception 'rs_advance 存在同一骑手多笔在途预支，未建唯一索引';
    end if;
end
$$;

create unique index if not exists uq_rs_advance_one_in_flight
    on rs_advance (rider_id)
    where status in ('pending', 'to_pay') and deleted = 0;
