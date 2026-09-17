# 周期计算单测不依赖应用容器。权限饱和活 API 用 @pytest.mark.integration。

from typing import Any


def pytest_configure(config: Any) -> None:
    config.addinivalue_line('markers', 'integration: 权限饱和活 API（需后端）')
