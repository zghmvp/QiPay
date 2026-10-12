do $$
begin
    if to_regclass('public.rs_adjustment') is null or to_regclass('public.rs_subject') is null then
        return;
    end if;

    update rs_adjustment as adj
    set signed_amount = case
            when subject.direction = 'bonus' then adj.amount
            else -adj.amount
        end
    from rs_subject as subject
    where subject.id = adj.subject_id
      and subject.deleted = 0
      and adj.signed_amount is null;
end
$$;
