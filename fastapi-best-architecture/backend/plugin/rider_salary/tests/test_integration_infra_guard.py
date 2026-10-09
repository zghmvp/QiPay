"""集成测试在 PostgreSQL 或 Redis 不可达时不能静默成功。"""

import os
import subprocess
import sys

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
INTEGRATION_DIR = 'backend/plugin/rider_salary/tests/integration'
PURE_TEST = 'backend/plugin/rider_salary/tests/test_sql_scripts.py'


def _run(*targets: str) -> subprocess.CompletedProcess[str]:
    """用不可达的数据库和 Redis 端口跑 pytest，不停止本机服务。

    :param targets: 传给 pytest 的路径
    :return: 子进程结果
    """
    env = os.environ.copy()
    env['DATABASE_HOST'] = '127.0.0.1'
    env['DATABASE_PORT'] = '1'
    env['REDIS_HOST'] = '127.0.0.1'
    env['REDIS_PORT'] = '1'
    env['REDIS_TIMEOUT'] = '1'
    command = [sys.executable, '-m', 'pytest', *targets, '-q', '-p', 'no:cacheprovider']
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_integration_only_exits_nonzero_when_infra_down() -> None:
    result = _run(INTEGRATION_DIR, '-m', 'integration')
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert '不可达' in output, output


def test_full_run_skips_integration_when_infra_down() -> None:
    result = _run(PURE_TEST, INTEGRATION_DIR)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert '已跳过' in output, output
    assert '不可达' in output, output
    assert 'passed' in output, output
