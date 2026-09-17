-- 下线日标记 / 站点公告：卸菜单权限并删除插件业务表（不动其它 FBA 系统表结构）
-- 自增菜单 ID
delete from sys_role_menu where menu_id in (91009, 91013, 91130, 91145, 91146, 91147);
delete from sys_menu where id in (91009, 91013, 91130, 91145, 91146, 91147);

-- 雪花菜单 ID（若环境使用 snowflake init）
delete from sys_role_menu where menu_id in (
  2060000000000091009,
  2060000000000091013,
  2060000000000091130,
  2060000000000091145,
  2060000000000091146,
  2060000000000091147
);
delete from sys_menu where id in (
  2060000000000091009,
  2060000000000091013,
  2060000000000091130,
  2060000000000091145,
  2060000000000091146,
  2060000000000091147
);

drop table if exists rs_day_flag;
drop table if exists rs_notice;
