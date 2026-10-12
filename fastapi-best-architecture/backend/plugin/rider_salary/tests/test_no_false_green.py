"""Redis 不可达时，插件纯函数测试仍要跑完，收集数为 0 时不得成功退出。"""

import os
import re
import shutil
import subprocess
import sys

from collections.abc import Generator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PROBE_DIR = Path(__file__).resolve().parent / '_p102_probe'
PROBE_FILE = PROBE_DIR / 'test_pure.py'
PROBE_SOURCE = 'def test_pure() -> None:\n    assert 1 + 1 == 2\n'


@pytest.fixture
def redis_probe() -> Generator[None]:
    """在插件目录放一个不导入应用的探针用例，跑完即删。"""
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    PROBE_FILE.write_text(PROBE_SOURCE, encoding='utf-8')
    try:
        yield
    finally:
        shutil.rmtree(PROBE_DIR, ignore_errors=True)


def _run_probe(*extra: str) -> subprocess.CompletedProcess[str]:
    """用不可达 Redis 端口跑探针，不停止本机 Redis。

    :param extra: 追加给 pytest 的参数
    :return: 子进程结果
    """
    env = os.environ.copy()
    env['REDIS_HOST'] = '127.0.0.1'
    env['REDIS_PORT'] = '1'
    env['REDIS_TIMEOUT'] = '1'
    command = [
        sys.executable,
        '-m',
        'pytest',
        str(PROBE_FILE.relative_to(PROJECT_ROOT)),
        *extra,
        '-p',
        'no:cacheprovider',
    ]
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_unreachable_redis_still_runs_pure_tests(redis_probe: None) -> None:
    result = _run_probe()
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert re.search(r'[1-9]\d* passed', output), output
    assert re.search(r'已收集 [1-9]\d* 个用例', output), output
    assert 'configfile: pytest.ini' in output
    rootdir = re.search(r'rootdir: (\S+)', output)
    assert rootdir is not None, output
    assert rootdir.group(1).endswith('plugin/rider_salary'), rootdir.group(1)


def test_zero_collected_is_not_success(redis_probe: None) -> None:
    result = _run_probe('-k', '___definitely_absent___')
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert '未收集到任何测试用例' in output
