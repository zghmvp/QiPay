"""无库：四份 init*.sql 角色×菜单×权限码合同。"""

from backend.plugin.rider_salary.tests.rbac_support import (
    ACCOUNT_BUTTON,
    REQUIRED_SEED_PERMS,
    REVERSE_BUTTON,
    ROLE_RIDER,
    ROLE_SALARY_ADMIN,
    ROLE_SITE_DEPUTY,
    ROLE_SITE_OWNER,
    ROLLBACK_BUTTON,
    SA_ONLY_BUTTONS,
    SA_ONLY_PAGES,
    init_sql_files,
    parse_seed,
    seed_perms,
)


def test_rbac_sql_role_codes() -> None:
    files = init_sql_files()
    assert len(files) == 4
    parsed = []
    for path in files:
        menus, roles, bindings = parse_seed(path.read_text(encoding='utf-8'))
        parsed.append((path, menus, roles, bindings))

    for path, menus, roles, bindings in parsed:
        assert roles[ROLE_SALARY_ADMIN].name == '薪资管理员', path
        assert roles[ROLE_SITE_OWNER].name == '站点负责人', path
        assert roles[ROLE_SITE_DEPUTY].name == '站点副负责人', path
        assert roles[ROLE_RIDER].name == '骑手', path

        sa = bindings[ROLE_SALARY_ADMIN]
        so = bindings[ROLE_SITE_OWNER]
        dp = bindings[ROLE_SITE_DEPUTY]
        rd = bindings[ROLE_RIDER]

        assert REVERSE_BUTTON in sa, f'{path} 薪资管理员必须有反冲 91135'
        assert ROLLBACK_BUTTON not in sa, f'{path} 薪资管理员不得绑回退 91121'
        assert sa >= SA_ONLY_PAGES, f'{path} 薪资管理员缺站点/编辑器页'
        assert ACCOUNT_BUTTON in sa, f'{path} 薪资管理员必须有开通账号'

        forbidden_so = SA_ONLY_PAGES | SA_ONLY_BUTTONS | {ROLLBACK_BUTTON}
        assert not (so & forbidden_so), f'{path} 负责人不应拥有 {sorted(so & forbidden_so)}'
        assert so == dp, f'{path} 92002 与 92003 菜单集合必须相等'
        assert rd == set(), f'{path} 骑手不得有 sys_role_menu，实际 {sorted(rd)}'

        for menu_id in sa | so | dp:
            assert menu_id in menus, f'{path} 角色绑了不存在的菜单 {menu_id}'


def test_rbac_sql_perm_codes() -> None:
    for path in init_sql_files():
        menus, _roles, _bindings = parse_seed(path.read_text(encoding='utf-8'))
        perms = seed_perms(menus)
        missing = REQUIRED_SEED_PERMS - perms
        assert not missing, f'{path} 种子缺权限码 {sorted(missing)}'
        me_star = {item for item in perms if item.startswith('rs:me:')}
        assert not me_star, f'{path} 不应出现 rs:me:*：{sorted(me_star)}'
        assert 'rs:period:delete' in perms
        assert 'rs:payroll:view' in perms
        assert 'rs:plan:rollback' in perms
