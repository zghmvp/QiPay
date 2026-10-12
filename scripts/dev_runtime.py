#!/usr/bin/env python3
"""QiPay 本地三服务的跨平台启停辅助（macOS / Linux）。

本模块不拉起、不停止 PostgreSQL 与 Redis，只检测它们是否已在监听。
pidfile 记录 pid、cwd、cmdline、启动时间；停止前四项必须全部吻合。
端口检测使用 /proc/net/tcp、ss 或 TCP 连接，不依赖 lsof。
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

START_TOLERANCE_SECONDS = 2
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_KEEP = 5
PIDFILE_KEYS = ("pid", "cwd", "started_at", "cmdline")


@dataclass
class ProcMeta:
    pid: int
    cwd: str
    started_at: int
    cmdline: str


def parse_version(text: str) -> tuple[int, ...]:
    """从 `v22.18.0` 或 `uv 0.11.31` 这类文本里取出数字版本。"""
    match = re.search(r"(\d+(?:\.\d+)*)", text or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def node_matches_engines(version: str) -> bool:
    """管理端 engines：^22.18.0 或 ^24.0.0。"""
    parts = parse_version(version)
    if not parts:
        return False
    major = parts[0]
    minor = parts[1] if len(parts) > 1 else 0
    patch = parts[2] if len(parts) > 2 else 0
    if major == 22:
        return (minor, patch) >= (18, 0)
    return major == 24


def pnpm_matches_engines(version: str) -> bool:
    """管理端 engines：pnpm >= 11，锁定 pnpm@11.7.0。"""
    parts = parse_version(version)
    return bool(parts) and parts[0] >= 11


def tcp_connect(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def listening_inodes(port: int) -> set[str] | None:
    """从 /proc/net/tcp 找出处于 LISTEN 的 inode。没有该文件时返回 None。"""
    files = (Path("/proc/net/tcp"), Path("/proc/net/tcp6"))
    if not files[0].exists():
        return None
    inodes: set[str] = set()
    for path in files:
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 10 or ":" not in parts[1]:
                continue
            if parts[3] != "0A":
                continue
            try:
                local_port = int(parts[1].rsplit(":", 1)[1], 16)
            except ValueError:
                continue
            if local_port == port:
                inodes.add(parts[9])
    return inodes


def pids_for_inodes(inodes: set[str]) -> list[int]:
    if not inodes:
        return []
    targets = {f"socket:[{inode}]" for inode in inodes}
    found: list[int] = []
    proc_root = Path("/proc")
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        fd_dir = entry / "fd"
        try:
            fds = list(fd_dir.iterdir())
        except (OSError, PermissionError):
            continue
        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if target in targets:
                found.append(int(entry.name))
                break
    return found


def parse_ss_pids(text: str) -> list[int]:
    return [int(item) for item in re.findall(r"pid=(\d+)", text)]


def ss_listener_pids(port: int) -> list[int] | None:
    ss_bin = shutil.which("ss")
    if not ss_bin:
        return None
    try:
        proc = subprocess.run(
            [ss_bin, "-ltnp", f"sport = :{port}"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return parse_ss_pids(proc.stdout)


def darwin_lsof_listener_pids(port: int) -> list[int] | None:
    """仅 macOS 使用，用于在报错时显示监听进程。Linux 不走这条路径。"""
    if sys.platform != "darwin":
        return None
    lsof_bin = shutil.which("lsof")
    if not lsof_bin:
        return None
    try:
        proc = subprocess.run(
            [lsof_bin, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1):
        return None
    return [int(item) for item in proc.stdout.split() if item.isdigit()]


def listener_pids(port: int) -> list[int] | None:
    """返回监听该端口的 pid。无法判断时返回 None，空列表表示没有监听者。"""
    inodes = listening_inodes(port)
    if inodes is not None:
        if not inodes:
            return []
        return pids_for_inodes(inodes)
    ss_pids = ss_listener_pids(port)
    if ss_pids is not None:
        return ss_pids
    return darwin_lsof_listener_pids(port)


def port_listening(port: int) -> bool:
    inodes = listening_inodes(port)
    if inodes is not None:
        return bool(inodes)
    ss_bin = shutil.which("ss")
    if ss_bin:
        try:
            proc = subprocess.run(
                [ss_bin, "-ltn", f"sport = :{port}"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc is not None and proc.returncode == 0:
            for line in proc.stdout.splitlines():
                lowered = line.strip().lower()
                if not lowered or lowered.startswith("state") or lowered.startswith("netid"):
                    continue
                return True
            return False
    return tcp_connect("127.0.0.1", port) or tcp_connect("::1", port)


def pid_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    stat = Path(f"/proc/{pid}/stat")
    if stat.exists():
        try:
            raw = stat.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return True
        fields = raw[raw.rfind(")") + 2 :].split()
        if fields and fields[0] == "Z":
            return False
    return True


def _linux_start_epoch(pid: int) -> int | None:
    stat = Path(f"/proc/{pid}/stat")
    proc_stat = Path("/proc/stat")
    if not stat.exists() or not proc_stat.exists():
        return None
    try:
        raw = stat.read_text(encoding="utf-8", errors="replace")
        fields = raw[raw.rfind(")") + 2 :].split()
        start_ticks = int(fields[19])
        clk = os.sysconf("SC_CLK_TCK")
        btime = None
        for line in proc_stat.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("btime "):
                btime = int(line.split()[1])
                break
        if btime is None or clk <= 0:
            return None
        return btime + start_ticks // clk
    except (OSError, IndexError, ValueError):
        return None


def _ps_start_epoch(pid: int) -> int | None:
    """macOS 以及没有 /proc 时，用 ps 的已运行秒数反推启动时间。"""
    for flag in ("etimes=", "etime="):
        try:
            proc = subprocess.run(
                ["ps", "-p", str(pid), "-o", flag],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        text = (proc.stdout or "").strip()
        if proc.returncode != 0 or not text:
            continue
        if flag == "etimes=" and text.isdigit():
            return int(time.time()) - int(text)
        parsed = _parse_etime(text)
        if parsed is not None:
            return int(time.time()) - parsed
    return None


def _parse_etime(text: str) -> int | None:
    """解析 ps etime：[[dd-]hh:]mm:ss。"""
    text = text.strip()
    if not text:
        return None
    days = 0
    if "-" in text:
        day_text, text = text.split("-", 1)
        if not day_text.isdigit():
            return None
        days = int(day_text)
    parts = text.split(":")
    if not all(part.isdigit() for part in parts):
        return None
    nums = [int(part) for part in parts]
    if len(nums) == 2:
        minutes, seconds = nums
        hours = 0
    elif len(nums) == 3:
        hours, minutes, seconds = nums
    else:
        return None
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def process_start_epoch(pid: int) -> int | None:
    linux_epoch = _linux_start_epoch(pid)
    if linux_epoch is not None:
        return linux_epoch
    return _ps_start_epoch(pid)


def read_cmdline(pid: int) -> str | None:
    proc_cmd = Path(f"/proc/{pid}/cmdline")
    if proc_cmd.exists():
        try:
            raw = proc_cmd.read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except OSError:
            raw = ""
        if raw:
            return raw
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-ww", "-o", "command="],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (proc.stdout or "").strip()
    if proc.returncode != 0 or not text:
        return None
    return text


def read_cwd(pid: int) -> str | None:
    link = Path(f"/proc/{pid}/cwd")
    if link.exists():
        try:
            return os.path.realpath(os.readlink(link))
        except OSError:
            return None
    if sys.platform != "darwin":
        return None
    lsof_bin = shutil.which("lsof")
    if not lsof_bin:
        return None
    try:
        proc = subprocess.run(
            [lsof_bin, "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("n"):
            return os.path.realpath(line[1:])
    return None


def snapshot(pid: int) -> ProcMeta | None:
    if not pid_alive(pid):
        return None
    cmdline = read_cmdline(pid)
    cwd = read_cwd(pid)
    started_at = process_start_epoch(pid)
    if not cmdline or not cwd or started_at is None:
        return None
    return ProcMeta(pid=pid, cwd=os.path.realpath(cwd), started_at=started_at, cmdline=cmdline)


def normalize_cmdline(text: str) -> str:
    return " ".join(text.split())


def _strip_env_wrapper(parts: list[str]) -> list[str]:
    """shebang 的 `/usr/bin/env node ...` 在进程改写 argv 后会变成 `node ...`。"""
    if parts and os.path.basename(parts[0]) == "env":
        return parts[1:]
    return parts


def _same_argv(left: list[str], right: list[str]) -> bool:
    if not left or not right or len(left) != len(right):
        return False
    if os.path.basename(left[0]) != os.path.basename(right[0]):
        return False
    return left[1:] == right[1:]


def cmdline_equivalent(actual: str, recorded: str) -> bool:
    actual_norm = normalize_cmdline(actual)
    recorded_norm = normalize_cmdline(recorded)
    if not actual_norm or not recorded_norm:
        return False
    if actual_norm == recorded_norm:
        return True
    actual_parts = _strip_env_wrapper(actual_norm.split(" "))
    recorded_parts = _strip_env_wrapper(recorded_norm.split(" "))
    return _same_argv(actual_parts, recorded_parts)


def identity_matches(meta: ProcMeta) -> tuple[bool, str]:
    if meta.pid <= 1:
        return False, "拒绝操作系统进程"
    current = snapshot(meta.pid)
    if current is None:
        return False, "无法读取进程的 cmdline、cwd 或启动时间"
    if os.path.realpath(current.cwd) != os.path.realpath(meta.cwd):
        return False, "工作目录不一致"
    if cmdline_equivalent(current.cmdline, meta.cmdline):
        if abs(current.started_at - meta.started_at) > START_TOLERANCE_SECONDS:
            return False, "启动时间不一致"
        return True, "ok"
    # exec 或 shebang 会改写 argv，但 pid 与内核启动时间不变，仍是本脚本拉起的进程。
    if current.started_at == meta.started_at:
        return True, "ok"
    return False, "命令行不一致"


def read_pidfile(path: Path) -> ProcMeta | None:
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    data: dict[str, str] = {}
    for line in lines:
        if not line or "=" not in line:
            return None
        key, value = line.split("=", 1)
        data[key.strip()] = value
    if any(key not in data or data[key] == "" for key in PIDFILE_KEYS):
        return None
    try:
        pid = int(data["pid"].strip())
        started_at = int(data["started_at"].strip())
    except ValueError:
        return None
    if pid <= 1:
        return None
    return ProcMeta(
        pid=pid,
        cwd=data["cwd"],
        started_at=started_at,
        cmdline=data["cmdline"],
    )


def write_pidfile(path: Path, meta: ProcMeta) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        f"pid={meta.pid}\n"
        f"cwd={meta.cwd}\n"
        f"started_at={meta.started_at}\n"
        f"cmdline={meta.cmdline}\n"
    )
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def process_tree(pid: int) -> set[int]:
    try:
        proc = subprocess.run(
            ["ps", "-ax", "-o", "pid=,ppid="],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {pid} if pid > 1 else set()
    children: dict[int, list[int]] = {}
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        child = int(parts[0])
        parent = int(parts[1])
        children.setdefault(parent, []).append(child)
    found: set[int] = set()
    queue = [pid]
    while queue:
        current = queue.pop()
        if current in found or current <= 1:
            continue
        found.add(current)
        queue.extend(children.get(current, []))
    return found


def _signal_members(pid: int, sig: int) -> None:
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return
    if pgid == pid and pgid > 1:
        try:
            os.killpg(pgid, sig)
            return
        except (ProcessLookupError, PermissionError):
            pass
    for member in process_tree(pid):
        try:
            os.kill(member, sig)
        except (ProcessLookupError, PermissionError):
            continue


def terminate_tree(pid: int, grace: float) -> bool:
    if pid <= 1 or not pid_alive(pid):
        return True
    _signal_members(pid, signal.SIGTERM)
    deadline = time.time() + grace
    while time.time() < deadline:
        if not pid_alive(pid):
            _reap(pid)
            return True
        time.sleep(0.1)
    if pid_alive(pid):
        _signal_members(pid, signal.SIGKILL)
        time.sleep(0.2)
    _reap(pid)
    return not pid_alive(pid)


def _reap(pid: int) -> None:
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        return


def rotate_log(path: Path, max_bytes: int = LOG_MAX_BYTES, keep: int = LOG_KEEP) -> None:
    if keep < 1 or not path.is_file():
        return
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size < max_bytes:
        return
    oldest = Path(f"{path}.{keep}")
    if oldest.exists():
        oldest.unlink()
    index = keep - 1
    while index >= 1:
        source = Path(f"{path}.{index}")
        target = Path(f"{path}.{index + 1}")
        if source.exists():
            source.replace(target)
        index -= 1
    path.replace(Path(f"{path}.1"))


def log_tail(path: Path, lines: int = 40) -> str:
    if not path.is_file():
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


@contextmanager
def file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def classify_port(port: int, pidfile: Path) -> str:
    """返回 free、ours、ours-starting、conflict。"""
    meta = read_pidfile(pidfile)
    ours = False
    if meta is not None:
        if not pid_alive(meta.pid):
            try:
                pidfile.unlink()
            except OSError:
                pass
            meta = None
        else:
            matched, _reason = identity_matches(meta)
            ours = matched
    listening = port_listening(port)
    if ours and meta is not None:
        if not listening:
            return "ours-starting"
        holders = listener_pids(port)
        if not holders:
            return "ours"
        if process_tree(meta.pid) & set(holders):
            return "ours"
        return "conflict"
    if listening:
        return "conflict"
    return "free"


def describe_listeners(port: int) -> str:
    holders = listener_pids(port)
    if holders is None:
        return "无法解析监听进程编号。端口仍被占用，未结束任何进程。"
    if not holders:
        return "端口处于监听状态，但没有映射到可读取的进程。未结束任何进程。"
    rows: list[str] = []
    for pid in holders:
        current = snapshot(pid)
        if current is None:
            rows.append(f"pid={pid}（无法读取 cmdline / cwd / 启动时间）")
            continue
        rows.append(
            f"pid={current.pid} cwd={current.cwd} cmdline={current.cmdline}"
        )
    return "监听进程：" + "；".join(rows)


def daemonize(
    pidfile: Path,
    logfile: Path,
    cwd: Path,
    argv: list[str],
    max_bytes: int = LOG_MAX_BYTES,
    keep: int = LOG_KEEP,
) -> ProcMeta:
    if not cwd.is_dir():
        raise RuntimeError(f"工作目录不存在：{cwd}")
    if not argv:
        raise RuntimeError("缺少启动命令")
    logfile.parent.mkdir(parents=True, exist_ok=True)
    rotate_log(logfile, max_bytes=max_bytes, keep=keep)
    log = logfile.open("ab", buffering=0)
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=os.environ.copy(),
        )
    except OSError as exc:
        log.close()
        raise RuntimeError(f"无法执行命令：{shlex.join(argv)}（{exc}）") from exc
    log.close()
    deadline = time.time() + 1.0
    meta = None
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        meta = snapshot(proc.pid)
        if meta is not None:
            break
        time.sleep(0.02)
    if proc.poll() is not None:
        tail = log_tail(logfile)
        detail = f"进程启动后立即退出，退出码 {proc.returncode}。"
        if tail:
            detail = f"{detail}\n{tail}"
        raise RuntimeError(detail)
    if meta is None:
        terminate_tree(proc.pid, grace=1)
        raise RuntimeError("无法读取刚启动进程的 cmdline、cwd 或启动时间，已结束该进程。")
    write_pidfile(pidfile, meta)
    return meta


def ensure_started(
    name: str,
    port: int,
    pidfile: Path,
    logfile: Path,
    cwd: Path,
    argv: list[str],
    max_bytes: int = LOG_MAX_BYTES,
    keep: int = LOG_KEEP,
) -> int:
    lock_path = pidfile.parent / "dev.lock"
    with file_lock(lock_path):
        status = classify_port(port, pidfile)
        if status in ("ours", "ours-starting"):
            meta = read_pidfile(pidfile)
            pid_text = str(meta.pid) if meta else "?"
            print(f"[skip] {name} 已由本脚本启动（pidfile 校验通过）pid={pid_text}")
            return 0
        if status == "conflict":
            print(
                f"[error] 端口 {port} 已被其他进程占用，{name}启动失败。本脚本不会结束该进程。",
                file=sys.stderr,
            )
            print(f"[error] {describe_listeners(port)}", file=sys.stderr)
            return 1
        try:
            meta = daemonize(pidfile, logfile, cwd, argv, max_bytes=max_bytes, keep=keep)
        except RuntimeError as exc:
            print(f"[error] {name}启动失败：{exc}", file=sys.stderr)
            return 1
        print(f"[ok] {name}已后台启动 pid={meta.pid}")
        return 0


def stop_verified(name: str, pidfile: Path, grace: float = 8) -> int:
    if not pidfile.exists():
        print(f"[skip] {name} 没有 pidfile：{pidfile}")
        return 0
    meta = read_pidfile(pidfile)
    if meta is None:
        print(
            f"[warn] {name} 的 pidfile 缺少 cmdline、cwd 或启动时间，已拒绝停止，避免误杀：{pidfile}",
            file=sys.stderr,
        )
        return 2
    if not pid_alive(meta.pid):
        try:
            pidfile.unlink()
        except OSError:
            pass
        print(f"[skip] {name} 进程已不在，已清理 pidfile")
        return 0
    matched, reason = identity_matches(meta)
    if not matched:
        print(
            f"[warn] 拒绝停止{name} pid={meta.pid}：{reason}。不会结束该进程。",
            file=sys.stderr,
        )
        return 2
    print(f"==> 停止{name} pid={meta.pid}")
    if not terminate_tree(meta.pid, grace=grace):
        print(f"[error] {name} pid={meta.pid} 未能退出", file=sys.stderr)
        return 1
    try:
        pidfile.unlink()
    except OSError:
        pass
    print(f"[ok] 已停止{name}")
    return 0


def wait_http(url: str, name: str, tries: int = 90, timeout: float = 2) -> int:
    import urllib.request

    attempt = 0
    while attempt < tries:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                if 200 <= getattr(response, "status", 200) < 400:
                    print(f"[ok] {name}已就绪：{url}")
                    return 0
        except Exception:
            pass
        attempt += 1
        if attempt < tries:
            time.sleep(1)
    print(f"[error] 等待{name}超时：{url}", file=sys.stderr)
    return 1


def command_version(argv: list[str], cwd: Path | None = None) -> str:
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    text = (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0] if text else ""


def command_first_line(argv: list[str]) -> str:
    return command_version(argv)


def find_compatible_node_bin(
    search_root: Path | None = None,
    current_version: str | None = None,
) -> str | None:
    """当前 node 不满足管理端 engines 时，在 nvm 目录里找一个符合要求的 bin。

    返回要放到 PATH 最前面的目录；当前 node 已符合要求时返回 None。
    """
    if current_version is None:
        node = shutil.which("node")
        current_version = command_first_line([node, "--version"]) if node else ""
    if node_matches_engines(current_version):
        return None
    root = search_root if search_root is not None else Path.home() / ".nvm" / "versions" / "node"
    if not root.is_dir():
        return None
    matches: list[tuple[tuple[int, ...], Path]] = []
    for bin_dir in root.glob("*/bin"):
        node = bin_dir / "node"
        if not node.is_file() or not os.access(node, os.X_OK):
            continue
        version = command_first_line([str(node), "--version"])
        if node_matches_engines(version):
            matches.append((parse_version(version), bin_dir))
    if not matches:
        return None
    matches.sort()
    return str(matches[-1][1])


def check_tools(frontend: Path | None = None) -> int:
    missing: list[str] = []
    print(f"[info] python3 {sys.version.split()[0]}（启停脚本）")
    print("[info] 后端命令：uv run --python 3.12（需要 Python 3.12）")
    version_commands = {
        "uv": (["uv", "--version"], None),
        "node": (["node", "--version"], None),
        # 管理端目录里 corepack 会按 packageManager 切到锁定的 pnpm。
        "pnpm": (["pnpm", "--version"], frontend if frontend and frontend.is_dir() else None),
    }
    for name, version_args in (
        ("uv", version_commands["uv"]),
        ("node", version_commands["node"]),
        ("pnpm", version_commands["pnpm"]),
    ):
        path = shutil.which(name)
        if not path:
            missing.append(name)
            print(f"[error] 未找到命令：{name}", file=sys.stderr)
            continue
        argv, cwd = version_args
        version = command_version(argv, cwd)
        print(f"[info] {name} {version} ({path})")
        if name == "node" and version and not node_matches_engines(version):
            print(
                f"[warn] 当前 Node 为 {version}，管理端要求 ^22.18.0 或 ^24.0.0",
                file=sys.stderr,
            )
        if name == "pnpm" and version and not pnpm_matches_engines(version):
            print(
                f"[warn] 当前 pnpm 为 {version}，管理端要求 >=11（仓库锁定 pnpm@11.7.0）",
                file=sys.stderr,
            )
    if missing:
        print(
            "[error] 请先安装缺少的命令并加入 PATH。本脚本不会改用写死的 Homebrew 路径。",
            file=sys.stderr,
        )
        return 1
    return 0


def postgres_ready() -> tuple[bool, str]:
    pg_isready = shutil.which("pg_isready")
    if pg_isready:
        try:
            proc = subprocess.run(
                [pg_isready, "-h", "127.0.0.1", "-p", "5432"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False, "PostgreSQL 检测超时"
        if proc.returncode == 0:
            return True, "PostgreSQL 已在 127.0.0.1:5432 接受连接"
        return False, "PostgreSQL 未在 127.0.0.1:5432 接受连接"
    if port_listening(5432):
        return True, "5432 已监听（未找到 pg_isready，仅做端口检测）"
    return False, "PostgreSQL 未在 127.0.0.1:5432 监听"


def redis_ready() -> tuple[bool, str]:
    redis_cli = shutil.which("redis-cli")
    if redis_cli:
        try:
            proc = subprocess.run(
                [redis_cli, "-h", "127.0.0.1", "-p", "6379", "ping"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False, "Redis 检测超时"
        if proc.returncode == 0 and "PONG" in (proc.stdout or "").upper():
            return True, "Redis 已响应 PONG（127.0.0.1:6379）"
        return False, "Redis 未响应 PONG"
    if port_listening(6379):
        return True, "6379 已监听（未找到 redis-cli，仅做端口检测）"
    return False, "Redis 未在 127.0.0.1:6379 监听"


def check_deps() -> int:
    ok = True
    for ready, message in (postgres_ready(), redis_ready()):
        if ready:
            print(f"[ok] {message}")
        else:
            print(
                f"[error] {message}。本脚本只检测、不拉起 PostgreSQL / Redis。",
                file=sys.stderr,
            )
            ok = False
    return 0 if ok else 1


def report_ports(ports: list[int]) -> int:
    for port in ports:
        if port_listening(port):
            print(
                f"[warn] 端口 {port} 仍被占用。占用者不是已校验通过的本项目进程，未结束它。"
            )
            print(f"[warn] {describe_listeners(port)}")
        else:
            print(f"[ok] 端口 {port} 未被占用")
    return 0


def _positive_port(value: str) -> int:
    port = int(value)
    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError("端口必须在 1 到 65535 之间")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QiPay 本地三服务启停辅助")
    sub = parser.add_subparsers(dest="cmd", required=True)

    tools = sub.add_parser("check-tools", help="检查 uv、node、pnpm 是否在 PATH 中")
    tools.add_argument("--frontend", type=Path, default=None)
    sub.add_parser("suggest-node-bin", help="打印应符合 engines 的 Node bin 目录")
    sub.add_parser("check-deps", help="只检测 PostgreSQL 与 Redis，不拉起")

    started = sub.add_parser("ensure-started", help="端口空闲才启动，冲突则失败且不杀进程")
    started.add_argument("--name", required=True)
    started.add_argument("--port", required=True, type=_positive_port)
    started.add_argument("--pidfile", required=True, type=Path)
    started.add_argument("--logfile", required=True, type=Path)
    started.add_argument("--cwd", required=True, type=Path)
    started.add_argument("--max-bytes", type=int, default=LOG_MAX_BYTES)
    started.add_argument("--keep", type=int, default=LOG_KEEP)
    started.add_argument("argv", nargs=argparse.REMAINDER)

    stop = sub.add_parser("stop", help="校验 pidfile 后停止进程")
    stop.add_argument("--name", required=True)
    stop.add_argument("--pidfile", required=True, type=Path)
    stop.add_argument("--grace", type=float, default=8)

    waiting = sub.add_parser("wait-http", help="等待 HTTP 就绪，超时返回非 0")
    waiting.add_argument("--url", required=True)
    waiting.add_argument("--name", required=True)
    waiting.add_argument("--tries", type=int, default=90)
    waiting.add_argument("--timeout", type=float, default=2)

    ports = sub.add_parser("report-ports", help="报告端口占用，不结束进程")
    ports.add_argument("--ports", required=True, help="逗号分隔的端口")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "check-tools":
        return check_tools(args.frontend)
    if args.cmd == "suggest-node-bin":
        suggested = find_compatible_node_bin()
        if suggested:
            print(suggested)
        return 0
    if args.cmd == "check-deps":
        return check_deps()
    if args.cmd == "ensure-started":
        command = list(args.argv)
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            print("[error] ensure-started 缺少启动命令", file=sys.stderr)
            return 1
        return ensure_started(
            name=args.name,
            port=args.port,
            pidfile=args.pidfile,
            logfile=args.logfile,
            cwd=args.cwd,
            argv=command,
            max_bytes=args.max_bytes,
            keep=args.keep,
        )
    if args.cmd == "stop":
        return stop_verified(args.name, args.pidfile, grace=args.grace)
    if args.cmd == "wait-http":
        return wait_http(args.url, args.name, tries=args.tries, timeout=args.timeout)
    if args.cmd == "report-ports":
        ports = [_positive_port(item) for item in args.ports.split(",") if item]
        return report_ports(ports)
    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    sys.exit(main())
