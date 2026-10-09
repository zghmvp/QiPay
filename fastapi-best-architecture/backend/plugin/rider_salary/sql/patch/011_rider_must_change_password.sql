do $$
begin
    if to_regclass('public.rs_rider') is null then
        return;
    end if;
    if not exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'rs_rider'
          and column_name = 'must_change_password'
    ) then
        alter table rs_rider
            add column must_change_password boolean not null default false;
    end if;
    comment on column rs_rider.must_change_password is '是否必须修改密码';
end
$$;
