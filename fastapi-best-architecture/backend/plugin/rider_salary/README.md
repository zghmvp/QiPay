# 骑手薪资管理

面向即时配送站点的骑手薪资管理，提供公式引擎计薪、结算锁账、日历可视化与预支申请

## 插件类型

- 应用级插件

## 配置说明

插件目录下 `plugin.toml` 的 `[settings]` 中包含以下内容：

```toml
[settings]
RIDER_SALARY_ADVANCE_LIMIT_DEFAULT = 3000
RIDER_SALARY_IMPORT_MAX_ROWS = 20000
RIDER_SALARY_TRIAL_MAX_ORDERS = 5000
```

在 `backend/core/conf.py` 中添加以下内容：

```python
##################################################
# [ Plugin ] rider_salary
##################################################
# 基础配置（in plugin.toml）
RIDER_SALARY_ADVANCE_LIMIT_DEFAULT: int
RIDER_SALARY_IMPORT_MAX_ROWS: int
RIDER_SALARY_TRIAL_MAX_ORDERS: int
```

## 配置项说明

- `RIDER_SALARY_ADVANCE_LIMIT_DEFAULT`：控制骑手预支的全局默认上限
- `RIDER_SALARY_IMPORT_MAX_ROWS`：控制单次订单导入允许的最大行数
- `RIDER_SALARY_TRIAL_MAX_ORDERS`：控制方案试算允许的最大订单数

## 使用方式

1. 将插件放入 `backend/plugin/rider_salary` 并安装 `requirements.txt` 依赖
2. 重启后端，由 SQLAlchemy `create_all` 自动创建 `rs_*` 业务表
3. 按主键模式执行 `sql/postgresql/init.sql` 或 `init_snowflake.sql` 写入菜单、角色与内置科目
4. 在系统角色管理中为后台账号勾选「后台管理」并分配「薪资管理员」或站点负责人角色

## 卸载说明

- 先执行对应数据库的 `destroy.sql` 或 `destroy_snowflake.sql` 清理菜单、角色与插件表
- 卸载插件后，建议同步移除相关插件基础配置和 `backend/core/conf.py` 中的插件配置
- 如业务代码仍在引用本插件模型或工具函数，请同步清理对应集成

## 联系方式

- 作者：`QiPay`
- 反馈方式：提交 Issue 或 PR
