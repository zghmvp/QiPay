#!/usr/bin/env python3
"""P4-01 启停脚本验收：进程归属、端口冲突不误杀、日志轮转、健康检查失败。"""

from __future__ import annotations

import os
import socket
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import urllib.request
from pathlib import Path

import dev_runtime

SCRIPTS = Path(__file__).resolve().parent
HELPER = SCRIPTS / "dev_runtime.py"
ROOT = SCRIPTS.parent
POSTGRES_WAS_UP = False
REDIS_WAS_UP = False


def setUpModule() -> None:
    global POSTGRES_WAS_UP, REDIS_WAS_UP
    POSTGRES_WAS_UP = dev_runtime.port_listening(5432)
    REDIS_WAS_UP = dev_runtime.port_listening(6379)


def tearDownModule() -> None:
    if POSTGRES_WAS_UP and not dev_runtime.port_listening(5432):
        raise AssertionError("测试过程中 PostgreSQL 5432 被关掉了")
    if REDIS_WAS_UP and not dev_runtime.port_listening(6379):
        raise AssertionError("测试过程中 Redis 6379 被关掉了")


class RuntimeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.procs: list[subprocess.Popen[bytes]] = []
        self.addCleanup(self._stop_owned)

    def _stop_owned(self) -> None:
        for proc in self.procs:
            if proc.poll() is not None:
                continue
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except (ProcessLookupError, ChildProcessError):
                continue
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=3)
                except (ProcessLookupError, ChildProcessError, subprocess.TimeoutExpired):
                    continue

    def _track(self, proc: subprocess.Popen[bytes]) -> subprocess.Popen[bytes]:
        self.procs.append(proc)
        return proc

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _wait_listen(self, port: int, timeout: float = 5) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if dev_runtime.port_listening(port):
                return
            time.sleep(0.05)
        self.fail(f"端口 {port} 没有进入监听")

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(HELPER), *args],
            capture_output=True,
            text=True,
            check=False,
        )


class PortDetectionTests(RuntimeTestCase):
    def test_bound_socket_is_listening_and_closed_port_is_not(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(sock.close)
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
        self.assertFalse(dev_runtime.port_listening(port))
        sock.listen(1)
        self.assertTrue(dev_runtime.port_listening(port))
        holders = dev_runtime.listener_pids(port)
        self.assertIsNotNone(holders)
        assert holders is not None
        self.assertIn(os.getpid(), holders)

    def test_ss_pid_parser(self) -> None:
        sample = textwrap.dedent(
            """
            State Recv-Q Send-Q Local Address:Port Peer Address:PortProcess
            LISTEN 0 128 127.0.0.1:8000 0.0.0.0:* users:(("python",pid=4321,fd=5))
            """
        )
        self.assertEqual(dev_runtime.parse_ss_pids(sample), [4321])

    def test_suggests_nvm_node_when_current_is_too_old(self) -> None:
        root = self.root / "node"
        old = root / "v22.14.0" / "bin"
        good = root / "v22.22.2" / "bin"
        newer = root / "v24.1.0" / "bin"
        for directory, version in ((old, "v22.14.0"), (good, "v22.22.2"), (newer, "v24.1.0")):
            directory.mkdir(parents=True)
            node = directory / "node"
            node.write_text(f"#!/bin/sh\necho {version}\n", encoding="utf-8")
            node.chmod(0o755)
        suggested = dev_runtime.find_compatible_node_bin(root, current_version="v22.14.0")
        self.assertEqual(suggested, str(newer))
        self.assertIsNone(dev_runtime.find_compatible_node_bin(root, current_version="v22.18.0"))

    def test_node_and_pnpm_version_rules(self) -> None:
        self.assertTrue(dev_runtime.node_matches_engines("v22.18.0"))
        self.assertTrue(dev_runtime.node_matches_engines("v22.22.2"))
        self.assertTrue(dev_runtime.node_matches_engines("v24.0.0"))
        self.assertFalse(dev_runtime.node_matches_engines("v22.14.0"))
        self.assertFalse(dev_runtime.node_matches_engines("v23.1.0"))
        self.assertTrue(dev_runtime.pnpm_matches_engines("11.7.0"))
        self.assertFalse(dev_runtime.pnpm_matches_engines("10.33.3"))


class PidfileIdentityTests(RuntimeTestCase):
    def test_snapshot_roundtrip_matches(self) -> None:
        proc = self._track(
            subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                start_new_session=True,
            )
        )
        meta = None
        for _ in range(50):
            meta = dev_runtime.snapshot(proc.pid)
            if meta is not None:
                break
            time.sleep(0.02)
        self.assertIsNotNone(meta)
        assert meta is not None
        matched, reason = dev_runtime.identity_matches(meta)
        self.assertTrue(matched, reason)
        again = dev_runtime.snapshot(proc.pid)
        self.assertIsNotNone(again)
        assert again is not None
        self.assertLessEqual(abs(again.started_at - meta.started_at), dev_runtime.START_TOLERANCE_SECONDS)

    def test_mismatch_does_not_kill(self) -> None:
        proc = self._track(
            subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                start_new_session=True,
            )
        )
        meta = None
        for _ in range(50):
            meta = dev_runtime.snapshot(proc.pid)
            if meta is not None:
                break
            time.sleep(0.02)
        self.assertIsNotNone(meta)
        assert meta is not None
        pidfile = self.root / "foreign.pid"
        cases = [
            dev_runtime.ProcMeta(meta.pid, "/tmp/not-the-cwd", meta.started_at, meta.cmdline),
            dev_runtime.ProcMeta(meta.pid, meta.cwd, meta.started_at + 10000, meta.cmdline),
            dev_runtime.ProcMeta(meta.pid, meta.cwd, meta.started_at + 10000, "definitely-not-this-command"),
        ]
        for index, forged in enumerate(cases):
            dev_runtime.write_pidfile(pidfile, forged)
            code = dev_runtime.stop_verified(f"用例{index}", pidfile, grace=1)
            self.assertEqual(code, 2)
            self.assertIsNone(proc.poll())
            self.assertTrue(pidfile.exists())

    def test_shebang_rewrite_still_matches_and_stops(self) -> None:
        self.assertTrue(
            dev_runtime.cmdline_equivalent(
                "node /opt/pnpm run dev",
                "/usr/bin/env node /opt/pnpm run dev",
            )
        )
        proc = self._track(
            subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                start_new_session=True,
            )
        )
        meta = None
        for _ in range(50):
            meta = dev_runtime.snapshot(proc.pid)
            if meta is not None:
                break
            time.sleep(0.02)
        self.assertIsNotNone(meta)
        assert meta is not None
        rewritten = dev_runtime.ProcMeta(
            meta.pid,
            meta.cwd,
            meta.started_at,
            "/usr/bin/env " + meta.cmdline,
        )
        execed = dev_runtime.ProcMeta(meta.pid, meta.cwd, meta.started_at, "totally-rewritten-argv")
        matched, reason = dev_runtime.identity_matches(execed)
        self.assertTrue(matched, reason)
        pidfile = self.root / "rewritten.pid"
        dev_runtime.write_pidfile(pidfile, rewritten)
        code = dev_runtime.stop_verified("改写命令行", pidfile, grace=3)
        self.assertEqual(code, 0)
        self.assertFalse(dev_runtime.pid_alive(proc.pid))

    def test_legacy_bare_pid_is_refused(self) -> None:
        proc = self._track(
            subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                start_new_session=True,
            )
        )
        pidfile = self.root / "legacy.pid"
        pidfile.write_text(f"{proc.pid}\n", encoding="utf-8")
        code = dev_runtime.stop_verified("旧格式", pidfile, grace=1)
        self.assertEqual(code, 2)
        self.assertIsNone(proc.poll())
        self.assertTrue(pidfile.exists())

    def test_matched_stop_kills_only_that_process(self) -> None:
        keep = self._track(
            subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                start_new_session=True,
            )
        )
        victim = self._track(
            subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                start_new_session=True,
            )
        )
        meta = None
        for _ in range(50):
            meta = dev_runtime.snapshot(victim.pid)
            if meta is not None:
                break
            time.sleep(0.02)
        self.assertIsNotNone(meta)
        assert meta is not None
        pidfile = self.root / "victim.pid"
        dev_runtime.write_pidfile(pidfile, meta)
        code = dev_runtime.stop_verified("目标进程", pidfile, grace=3)
        self.assertEqual(code, 0)
        self.assertFalse(dev_runtime.pid_alive(victim.pid))
        self.assertIsNone(keep.poll())
        self.assertFalse(pidfile.exists())


class ConflictAndRotateTests(RuntimeTestCase):
    def test_occupied_port_does_not_spawn_or_kill(self) -> None:
        port = self._free_port()
        server = self._track(
            subprocess.Popen(
                [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        )
        self._wait_listen(port)
        marker = self.root / "should-not-spawn"
        pidfile = self.root / "backend.pid"
        result = self._run(
            [
                "ensure-started",
                "--name",
                "后端",
                "--port",
                str(port),
                "--pidfile",
                str(pidfile),
                "--logfile",
                str(self.root / "backend.log"),
                "--cwd",
                str(self.root),
                "--",
                sys.executable,
                "-c",
                f"open({str(marker)!r}, 'w').write('spawned')",
            ]
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("不会结束该进程", result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse(pidfile.exists())
        self.assertIsNone(server.poll())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            self.assertEqual(response.status, 200)
        stop = self._run(["stop", "--name", "后端", "--pidfile", str(pidfile), "--grace", "1"])
        self.assertEqual(stop.returncode, 0, stop.stderr)
        self.assertIsNone(server.poll())

    def test_ensure_started_then_stop_roundtrip(self) -> None:
        port = self._free_port()
        pidfile = self.root / "h5.pid"
        logfile = self.root / "h5.log"
        started = self._run(
            [
                "ensure-started",
                "--name",
                "骑手 H5",
                "--port",
                str(port),
                "--pidfile",
                str(pidfile),
                "--logfile",
                str(logfile),
                "--cwd",
                str(SCRIPTS),
                "--",
                sys.executable,
                "-m",
                "http.server",
                str(port),
                "--bind",
                "127.0.0.1",
            ]
        )
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertIn("已后台启动", started.stdout)
        self._wait_listen(port)
        meta = dev_runtime.read_pidfile(pidfile)
        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertTrue(meta.cmdline)
        self.assertTrue(meta.cwd)
        self.assertGreater(meta.started_at, 0)
        status = dev_runtime.classify_port(port, pidfile)
        self.assertEqual(status, "ours")
        again = self._run(
            [
                "ensure-started",
                "--name",
                "骑手 H5",
                "--port",
                str(port),
                "--pidfile",
                str(pidfile),
                "--logfile",
                str(logfile),
                "--cwd",
                str(SCRIPTS),
                "--",
                sys.executable,
                "-c",
                "raise SystemExit('不应再次启动')",
            ]
        )
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("校验通过", again.stdout)
        self.assertTrue(dev_runtime.pid_alive(meta.pid))
        waited = self._run(
            ["wait-http", "--url", f"http://127.0.0.1:{port}/", "--name", "骑手 H5", "--tries", "10"]
        )
        self.assertEqual(waited.returncode, 0, waited.stderr)
        stopped = self._run(["stop", "--name", "骑手 H5", "--pidfile", str(pidfile), "--grace", "3"])
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertFalse(dev_runtime.pid_alive(meta.pid))
        self.assertFalse(dev_runtime.port_listening(port))

    def test_wait_http_failure_is_nonzero(self) -> None:
        result = self._run(
            ["wait-http", "--url", "http://127.0.0.1:1/", "--name", "不存在的服务", "--tries", "1", "--timeout", "0.2"]
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("超时", result.stderr)

    def test_log_rotates_by_size(self) -> None:
        path = self.root / "backend.log"
        path.write_bytes(b"a" * 100)
        dev_runtime.rotate_log(path, max_bytes=50, keep=2)
        self.assertFalse(path.exists())
        self.assertEqual(Path(f"{path}.1").read_bytes(), b"a" * 100)
        path.write_bytes(b"b" * 80)
        dev_runtime.rotate_log(path, max_bytes=50, keep=2)
        self.assertEqual(Path(f"{path}.1").read_bytes(), b"b" * 80)
        self.assertEqual(Path(f"{path}.2").read_bytes(), b"a" * 100)
        path.write_bytes(b"c" * 80)
        dev_runtime.rotate_log(path, max_bytes=50, keep=2)
        self.assertFalse(Path(f"{path}.3").exists())
        self.assertEqual(Path(f"{path}.1").read_bytes(), b"c" * 80)
        self.assertEqual(Path(f"{path}.2").read_bytes(), b"b" * 80)


class ScriptContractTests(unittest.TestCase):
    def test_shell_syntax_and_executable(self) -> None:
        for name in ("start_all.sh", "stop_all.sh"):
            path = SCRIPTS / name
            mode = path.stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, name)
            result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_scripts_do_not_hardcode_macos_or_kill_by_port(self) -> None:
        combined = "\n".join(
            (SCRIPTS / name).read_text(encoding="utf-8")
            for name in ("start_all.sh", "stop_all.sh", "dev_runtime.py")
        )
        for forbidden in ("FlyEnv", "postgresql@18", "/Users/", "pkill", "pg_ctl", "redis-server"):
            self.assertNotIn(forbidden, combined)
        shell_lines = []
        for name in ("start_all.sh", "stop_all.sh"):
            for line in (SCRIPTS / name).read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                shell_lines.append(line)
        shell = "\n".join(shell_lines)
        self.assertNotIn("lsof", shell)
        self.assertIn("dev_runtime.py", shell)
        self.assertIn("scripts/start_all.sh", (SCRIPTS / "start_all.sh").read_text(encoding="utf-8"))
        self.assertIn("Python 3.12", (SCRIPTS / "start_all.sh").read_text(encoding="utf-8"))
        self.assertIn("pnpm@11.7.0", (SCRIPTS / "start_all.sh").read_text(encoding="utf-8"))

    def test_darwin_lsof_helper_is_not_used_on_linux(self) -> None:
        if sys.platform == "darwin":
            self.skipTest("当前就是 macOS")
        self.assertIsNone(dev_runtime.darwin_lsof_listener_pids(9))


class DepsStaySharedTests(unittest.TestCase):
    def test_check_deps_does_not_print_that_it_started_them(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HELPER), "check-deps"],
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertNotIn("已启动", output)
        self.assertNotIn("拉起", output.split("只检测、不拉起")[0] if "只检测、不拉起" in output else output)
        if result.returncode == 0:
            self.assertIn("PostgreSQL", result.stdout)
            self.assertIn("Redis", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
