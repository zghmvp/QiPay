# 骑手薪资管理

面向即时配送站点的骑手薪资管理，提供公式引擎计薪、结算锁账、日历可视化与预支申请

## 插件类型

- 应用级插件

## 配置说明

配置只写在本目录 `plugin.toml` 的 `[settings]`。框架的 `PluginSettingsSource` 会在启动时把各插件的 `[settings]` 合并进 `settings`。`backend/core/conf.py` 的 `extra='allow'` 已经允许这些键，**不要修改 `backend/core/conf.py`**。

```toml
[settings]
RIDER_SALARY_ADVANCE_LIMIT_DEFAULT = 3000
RIDER_SALARY_IMPORT_MAX_ROWS = 20000
RIDER_SALARY_TRIAL_MAX_ORDERS = 5000
```

代码里读取：`from backend.core.conf import settings`，然后用 `settings.RIDER_SALARY_XXX`。

## 配置项说明

- `RIDER_SALARY_ADVANCE_LIMIT_DEFAULT`：控制骑手预支的全局默认上限
- `RIDER_SALARY_IMPORT_MAX_ROWS`：控制单次订单导入允许的最大行数
- `RIDER_SALARY_TRIAL_MAX_ORDERS`：控制方案试算允许的最大订单数

## 数据库

只支持 PostgreSQL。`plugin.toml` 的 `database` 只声明 `postgresql`。

`sql/mysql/` 下的 init / destroy 脚本仅供参考，不在支持范围。这些文件先保留：`tests/test_sql_scripts.py` 仍会比较 PostgreSQL 与 MySQL 四份 init 是否一致。是否删除 MySQL 脚本待决定；删除前，改菜单、权限或科目种子时仍要同步 `sql/mysql/`，否则该测试会失败。

## 使用方式

插件随仓库放在 `backend/plugin/rider_salary`，由框架按目录自动发现，不需要改框架源码。

1. 在 `fastapi-best-architecture` 目录安装本插件 `requirements.txt`（版本已锁定，不要升级）：`uv pip install -r backend/plugin/rider_salary/requirements.txt`
2. 确认 PostgreSQL 与 Redis 已在本机监听（端口见仓库 `docs/research/环境初始化记录.md`），再启动后端。SQLAlchemy `create_all` 会创建 `rs_*` 业务表
3. 按主键模式执行 `sql/postgresql/init.sql` 或 `init_snowflake.sql`，写入菜单、角色、内置科目和 `rs_role_anchor`
4. 已有库的增量用 `sql/patch/`，不要重跑整份 init
5. 在系统角色管理中为后台账号分配「薪资管理员」或站点负责人角色。全站数据范围看权限码 `rs:scope:all`，种子已绑给「薪资管理员」

## 卸载说明

- 先执行 `sql/postgresql/destroy.sql` 或 `destroy_snowflake.sql`，清理菜单、角色与插件表
- 再删除插件目录。配置在 `plugin.toml` 里，卸载时不要去改 `backend/core/conf.py`
- 如业务代码仍在引用本插件模型或工具函数，请同步清理对应集成

## 联系方式

- 作者：`QiPay`
- 反馈方式：提交 Issue 或 PR
