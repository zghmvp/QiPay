do $$
begin
    if exists (
        select 1
        from rs_rider
        where user_id is not null
          and deleted = 0
        group by user_id
        having count(*) > 1
    ) then
        raise exception 'rs_rider.user_id 存在重复绑定，未建唯一索引';
    end if;

    if exists (
        select 1
        from rs_site_manager
        where role = 'owner'
          and deleted = 0
        group by site_id
        having count(*) > 1
    ) then
        raise exception 'rs_site_manager 存在多名负责人，未建唯一索引';
    end if;
end
$$;

create unique index if not exists uq_rs_rider_one_user
    on rs_rider (user_id)
    where user_id is not null and deleted = 0;

create unique index if not exists uq_rs_site_manager_one_owner
    on rs_site_manager (site_id)
    where role = 'owner' and deleted = 0;
