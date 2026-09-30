#!/usr/bin/env python3
"""
diagnose_slowdown.py — 电脑变慢诊断脚本 (Linux)
================================================

用法:
    python3 diagnose_slowdown.py                  # 默认跑一次诊断
    python3 diagnose_slowdown.py --interval 3      # 采样窗口拉长到 3 秒 (更准确)
    python3 diagnose_slowdown.py --top 15          # 显示更多进程
    python3 diagnose_slowdown.py --full            # 额外显示单个进程明细(不只是按程序名汇总)
    python3 diagnose_slowdown.py --log ~/slowdown.csv   # 把本次结果追加写入 CSV,方便以后对比趋势
    python3 diagnose_slowdown.py --no-color        # 关闭彩色输出(比如输出重定向到文件时)

依赖:
    pip3 install psutil     (如果没装,脚本会提示)

这个脚本会检查:
    1. CPU 负载 / 每核使用率
    2. 内存 & swap 使用情况
    3. 磁盘空间占用(哪个分区快满了)
    4. 磁盘 I/O 速率(整体 + 按进程/程序名汇总的读写大户)
    5. 按 CPU / 内存占用汇总的"程序分组"(例如把所有 firefox 子进程合并统计,
       因为浏览器开很多 tab 时,单个进程占用看起来不高,但加起来非常吓人)
    6. 温度传感器(有没有过热/降频风险,需要系统装了 lm-sensors)
    7. 僵尸(zombie)进程数量
    8. 最近的 OOM(内存耗尽被杀进程)记录,来自 dmesg
    9. 一个"结论 / 可能原因"总结,给出具体可执行的建议

脚本只做只读检测,不会自动杀进程或删文件。
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict

try:
    import psutil
except ImportError:
    print("需要安装 psutil 才能运行本脚本:\n\n    pip3 install psutil\n")
    sys.exit(1)


# --------------------------------------------------------------------------
# 输出辅助 (简单的 ANSI 颜色,不依赖第三方库)
# --------------------------------------------------------------------------

class C:
    enabled = True

    @classmethod
    def wrap(cls, code, text):
        if not cls.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    @classmethod
    def bold(cls, t):
        return cls.wrap("1", t)

    @classmethod
    def red(cls, t):
        return cls.wrap("31", t)

    @classmethod
    def yellow(cls, t):
        return cls.wrap("33", t)

    @classmethod
    def green(cls, t):
        return cls.wrap("32", t)

    @classmethod
    def cyan(cls, t):
        return cls.wrap("36", t)


def header(title):
    line = "=" * 78
    print(f"\n{C.cyan(line)}")
    print(C.bold(C.cyan(f"  {title}")))
    print(C.cyan(line))


def human_bytes(n):
    n = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024.0:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"


def severity(pct, warn=70, bad=90):
    """根据百分比返回带颜色的字符串"""
    s = f"{pct:.1f}%"
    if pct >= bad:
        return C.red(C.bold(s))
    if pct >= warn:
        return C.yellow(s)
    return C.green(s)


ISSUES = []  # 收集发现的问题,最后统一打印结论


def flag(msg, level="warn"):
    ISSUES.append((level, msg))


# --------------------------------------------------------------------------
# 1. CPU
# --------------------------------------------------------------------------

def check_cpu(interval):
    header("1. CPU 负载")
    n_cores = psutil.cpu_count(logical=True)
    n_physical = psutil.cpu_count(logical=False)
    load1, load5, load15 = (os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0))
    print(f"逻辑核心数: {n_cores}  (物理核心: {n_physical})")
    print(f"Load average (1/5/15 分钟): {load1:.2f} / {load5:.2f} / {load15:.2f}")

    per_core = psutil.cpu_percent(interval=interval, percpu=True)
    overall = sum(per_core) / len(per_core)
    print(f"整体 CPU 使用率 (采样 {interval}s): {severity(overall)}")
    bar_width = 30
    for i, pct in enumerate(per_core):
        filled = int(bar_width * pct / 100)
        bar = "█" * filled + "░" * (bar_width - filled)
        print(f"  核心{i:>2}: [{bar}] {severity(pct)}")

    if load1 > n_cores * 1.5:
        flag(f"1分钟平均负载 {load1:.2f} 远超核心数({n_cores}),系统在排队等 CPU,会明显卡顿。", "bad")
    elif load1 > n_cores:
        flag(f"1分钟平均负载 {load1:.2f} 超过核心数({n_cores}),CPU 有一定压力。", "warn")

    return overall


# --------------------------------------------------------------------------
# 2. 内存 & Swap
# --------------------------------------------------------------------------

def check_memory():
    header("2. 内存 & Swap")
    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()

    print(f"物理内存: 总共 {human_bytes(vm.total)}, 已用 {human_bytes(vm.used)}, "
          f"可用 {human_bytes(vm.available)}, 使用率 {severity(vm.percent)}")
    print(f"Swap:     总共 {human_bytes(sm.total)}, 已用 {human_bytes(sm.used)}, "
          f"使用率 {severity(sm.percent)}")

    if vm.percent >= 90:
        flag(f"物理内存使用率高达 {vm.percent:.1f}%,可用内存只有 {human_bytes(vm.available)},"
             f"系统很可能正在疯狂换页(swap),这是卡顿最常见的原因之一。", "bad")
    elif vm.percent >= 80:
        flag(f"物理内存使用率 {vm.percent:.1f}%,偏高,建议关掉一些程序/浏览器标签页。", "warn")

    if sm.percent >= 30 and sm.used > 512 * 1024 * 1024:
        flag(f"Swap 已使用 {human_bytes(sm.used)} ({sm.percent:.1f}%),"
             f"说明真实内存不够用,系统在用磁盘/zram 顶替内存,速度会大幅下降。", "bad")

    return vm, sm


# --------------------------------------------------------------------------
# 3. 磁盘空间
# --------------------------------------------------------------------------

SKIP_FSTYPES = {"squashfs", "tmpfs", "devtmpfs", "overlay", "efivarfs"}


def check_disk_space():
    header("3. 磁盘空间占用")
    seen = set()
    rows = []
    for part in psutil.disk_partitions(all=False):
        if part.device in seen:
            continue
        seen.add(part.device)
        # squashfs 是 snap 包只读镜像,永远显示 100% 占用但没有意义,过滤掉
        if part.fstype in SKIP_FSTYPES:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        rows.append((part.device, part.mountpoint, usage))

    for device, mount, usage in sorted(rows, key=lambda r: -r[2].percent):
        print(f"  {device:<18} {mount:<35} 总{human_bytes(usage.total):>9}  "
              f"已用{human_bytes(usage.used):>9}  剩余{human_bytes(usage.free):>9}  "
              f"{severity(usage.percent)}")
        if usage.percent >= 95:
            flag(f"磁盘 {mount} 已用 {usage.percent:.1f}%,只剩 {human_bytes(usage.free)}!"
                 f"空间几乎耗尽会导致写入变慢、程序无法创建临时文件、浏览器缓存异常等问题。", "bad")
        elif usage.percent >= 90:
            flag(f"磁盘 {mount} 已用 {usage.percent:.1f}%,剩余空间偏少,建议清理。", "warn")


# --------------------------------------------------------------------------
# 4. 磁盘 I/O
# --------------------------------------------------------------------------

def check_disk_io(interval):
    header("4. 磁盘 I/O 速率")
    d0 = psutil.disk_io_counters()
    time.sleep(0)  # 复用外部已经睡过的时间会更好,这里独立采样
    d0 = psutil.disk_io_counters()
    t0 = time.time()
    time.sleep(interval)
    d1 = psutil.disk_io_counters()
    t1 = time.time()
    dt_s = max(t1 - t0, 0.001)

    read_rate = (d1.read_bytes - d0.read_bytes) / dt_s
    write_rate = (d1.write_bytes - d0.write_bytes) / dt_s
    print(f"整机磁盘读取速率: {human_bytes(read_rate)}/s")
    print(f"整机磁盘写入速率: {human_bytes(write_rate)}/s")

    if write_rate > 50 * 1024 * 1024 or read_rate > 100 * 1024 * 1024:
        flag(f"磁盘 I/O 较高 (读 {human_bytes(read_rate)}/s, 写 {human_bytes(write_rate)}/s),"
             f"如果磁盘是机械盘或已快满,高 I/O 会明显拖慢整机响应。", "warn")


# --------------------------------------------------------------------------
# 5. 进程占用(按程序名汇总 + 明细)
# --------------------------------------------------------------------------

def snapshot_processes():
    procs = {}
    for p in psutil.process_iter(["pid", "name", "username"]):
        try:
            p.cpu_percent(None)  # 预热计数器
            io = p.io_counters() if p.io_counters else None
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            io = None
        procs[p.pid] = {"proc": p, "io0": io}
    return procs


def check_processes(interval, top_n, show_full, procs0):
    header("5. 进程占用排行 (CPU / 内存 / 磁盘)")
    time.sleep(interval)

    rows = []
    zombie_count = 0
    for pid, data in procs0.items():
        p = data["proc"]
        try:
            if p.status() == psutil.STATUS_ZOMBIE:
                zombie_count += 1
                continue
            cpu = p.cpu_percent(None)
            mem_pct = p.memory_percent()
            rss = p.memory_info().rss
            name = p.name()
            try:
                # 用真正的可执行文件路径来分组更准确:比如 Firefox/Chrome 的沙盒子
                # 进程在 `ps`/`top` 里常显示成通用名字(如 "Isolated Web Co"),
                # 但它们的 exe() 都指向同一个浏览器二进制,这样才能看出
                # "浏览器总共占了多少资源",而不是被拆成一堆看似不起眼的小进程。
                group_key = p.exe() or name
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                group_key = name
            user = p.username()
            io1 = None
            try:
                io1 = p.io_counters()
            except Exception:
                pass
            read_rate = write_rate = 0.0
            if data["io0"] is not None and io1 is not None:
                read_rate = max(io1.read_bytes - data["io0"].read_bytes, 0) / interval
                write_rate = max(io1.write_bytes - data["io0"].write_bytes, 0) / interval
            rows.append({
                "pid": pid, "name": name, "group": group_key, "user": user, "cpu": cpu,
                "mem_pct": mem_pct, "rss": rss,
                "read_rate": read_rate, "write_rate": write_rate,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if zombie_count:
        flag(f"发现 {zombie_count} 个僵尸(zombie)进程,通常无害,但数量很多时说明有程序没有正确回收子进程。", "info")

    # --- 按"真正的可执行文件"汇总(更能反映"浏览器开了太多tab"这种情况) ---
    # 例如 Firefox/Chrome 的每个标签页子进程在 ps/top 里都显示成通用名字
    # (比如 "Isolated Web Co"),但它们的可执行文件都是同一个浏览器二进制,
    # 按 exe 路径分组才能看出"这个浏览器/程序总共占了多少资源"。
    grouped = defaultdict(lambda: {"cpu": 0.0, "mem_pct": 0.0, "rss": 0, "count": 0,
                                    "read_rate": 0.0, "write_rate": 0.0, "display": None})
    for r in rows:
        g = grouped[r["group"]]
        g["cpu"] += r["cpu"]
        g["mem_pct"] += r["mem_pct"]
        g["rss"] += r["rss"]
        g["read_rate"] += r["read_rate"]
        g["write_rate"] += r["write_rate"]
        g["count"] += 1
        # 用出现次数最多/最新的那个真实进程名作为展示用名字(basename 更好读)
        g["display"] = os.path.basename(r["group"]) if os.sep in r["group"] else r["group"]

    print(C.bold(f"\n按程序汇总 — CPU 占用最高的前 {top_n} 组:"))
    print(f"  {'程序':<28}{'进程数':>6}{'总CPU%':>10}{'总内存%':>10}{'总RSS':>12}")
    for _, g in sorted(grouped.items(), key=lambda x: -x[1]["cpu"])[:top_n]:
        print(f"  {g['display']:<28}{g['count']:>6}{severity(g['cpu'], warn=50, bad=100):>10}"
              f"{severity(g['mem_pct'], warn=20, bad=40):>10}{human_bytes(g['rss']):>12}")

    print(C.bold(f"\n按程序汇总 — 内存占用最高的前 {top_n} 组:"))
    print(f"  {'程序':<28}{'进程数':>6}{'总内存%':>10}{'总RSS':>12}{'总CPU%':>10}")
    for _, g in sorted(grouped.items(), key=lambda x: -x[1]["rss"])[:top_n]:
        print(f"  {g['display']:<28}{g['count']:>6}{severity(g['mem_pct'], warn=20, bad=40):>10}"
              f"{human_bytes(g['rss']):>12}{severity(g['cpu'], warn=50, bad=100):>10}")

    io_groups = [g for g in grouped.items() if g[1]["read_rate"] + g[1]["write_rate"] > 0]
    if io_groups:
        print(C.bold(f"\n按程序汇总 — 磁盘 I/O 最高的前 {min(top_n, 10)} 组:"))
        print(f"  {'程序':<28}{'读速率':>12}{'写速率':>12}")
        for _, g in sorted(io_groups, key=lambda x: -(x[1]["read_rate"] + x[1]["write_rate"]))[:top_n]:
            print(f"  {g['display']:<28}{human_bytes(g['read_rate']) + '/s':>12}{human_bytes(g['write_rate']) + '/s':>12}")

    if show_full:
        print(C.bold(f"\n单个进程明细 — CPU 占用最高的前 {top_n} 个:"))
        print(f"  {'PID':>8}{'用户':<12}{'CPU%':>8}{'内存%':>8}{'RSS':>10}  命令")
        for r in sorted(rows, key=lambda x: -x["cpu"])[:top_n]:
            print(f"  {r['pid']:>8}{r['user']:<12}{r['cpu']:>8.1f}{r['mem_pct']:>8.1f}"
                  f"{human_bytes(r['rss']):>10}  {r['name']}")

    # --- 结论用的判断 ---
    top_cpu_group = max(grouped.items(), key=lambda x: x[1]["cpu"], default=None)
    if top_cpu_group and top_cpu_group[1]["cpu"] >= 60:
        _, g = top_cpu_group
        flag(f"「{g['display']}」共 {g['count']} 个进程合计占用 CPU {g['cpu']:.0f}%,是当前最大的 CPU 消耗者。", "warn")

    top_mem_group = max(grouped.items(), key=lambda x: x[1]["mem_pct"], default=None)
    if top_mem_group and top_mem_group[1]["mem_pct"] >= 25:
        _, g = top_mem_group
        flag(f"「{g['display']}」共 {g['count']} 个进程合计占用内存 {g['mem_pct']:.0f}% "
             f"({human_bytes(g['rss'])}),是当前最大的内存消耗者。", "warn")

    single_hog = max(rows, key=lambda r: r["cpu"], default=None)
    if single_hog and single_hog["cpu"] >= 90:
        cores_used = single_hog["cpu"] / 100.0
        flag(f"进程 {single_hog['name']} (PID {single_hog['pid']}) 单独占用 CPU 高达 "
             f"{single_hog['cpu']:.0f}% (相当于跑满 {cores_used:.1f} 个核心),"
             f"值得关注是否卡死/死循环/负载过重。", "warn")


# --------------------------------------------------------------------------
# 6. 温度
# --------------------------------------------------------------------------

def check_temperature():
    header("6. 温度传感器")
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        temps = {}

    if not temps:
        print("未检测到温度传感器数据(可能需要: sudo apt install lm-sensors && sudo sensors-detect)")
        return

    max_temp = 0.0
    for name, entries in temps.items():
        for e in entries:
            label = e.label or name
            crit = e.critical or e.high or None
            crit_str = f" (临界值 {crit:.0f}°C)" if crit else ""
            print(f"  {label:<25} {e.current:.1f}°C{crit_str}")
            max_temp = max(max_temp, e.current)
            if crit and e.current >= crit * 0.95:
                flag(f"传感器「{label}」温度 {e.current:.1f}°C 接近临界值 {crit:.0f}°C,"
                     f"CPU 可能已经在降频(thermal throttling)以避免过热,这会让系统变慢。", "bad")

    if max_temp >= 85:
        flag(f"检测到最高温度 {max_temp:.1f}°C,偏高,建议检查散热(风扇/灰尘/贴合硅脂)。", "warn")


# --------------------------------------------------------------------------
# 7. 最近的 OOM (内存耗尽杀进程) 记录
# --------------------------------------------------------------------------

def check_oom():
    header("7. 最近的 OOM (内存耗尽) 记录")
    lines = []
    try:
        out = subprocess.run(["dmesg", "-T"], capture_output=True, text=True, timeout=5)
        lines = [l for l in out.stdout.splitlines() if "Out of memory" in l or "oom-kill" in l or "Killed process" in l]
    except Exception:
        pass

    if not lines:
        print("最近没有发现 OOM killer 杀掉进程的记录 (或没有权限读取 dmesg)。")
        return

    for l in lines[-5:]:
        print(f"  {l}")
    flag(f"最近的系统日志中发现 {len(lines)} 条 OOM(内存耗尽)记录,"
         f"说明系统曾经内存严重不足到需要强制杀进程,这是很强的'内存不够'信号。", "bad")


# --------------------------------------------------------------------------
# 结论
# --------------------------------------------------------------------------

def print_conclusion():
    header("诊断结论")
    if not ISSUES:
        print(C.green("没有发现明显异常。系统当前的负载/内存/磁盘/温度都在正常范围内。"))
        return

    order = {"bad": 0, "warn": 1, "info": 2}
    for level, msg in sorted(ISSUES, key=lambda x: order.get(x[0], 3)):
        icon = {"bad": C.red("✗ [严重]"), "warn": C.yellow("⚠ [注意]"), "info": C.cyan("ℹ [提示]")}[level]
        print(f"  {icon} {msg}")

    print("\n" + C.bold("建议:"))
    print("  1) 优先处理标记为 [严重] 的问题;")
    print("  2) 如果是内存/swap 问题 → 关闭占用内存最多的程序分组(见上面第5节),或加内存;")
    print("  3) 如果是磁盘空间问题 → 清理占用最大分区的大文件(可用 `du -sh * | sort -rh` 排查);")
    print("  4) 如果某个程序 CPU 一直很高 → 考虑重启该程序,或用 `strace -p <PID>` / 查看日志排查死循环;")
    print("  5) 如果是温度问题 → 清灰、检查风扇转速 (`sensors` 命令), 避免持续降频。")


# --------------------------------------------------------------------------
# CSV 日志(方便以后对比趋势)
# --------------------------------------------------------------------------

def write_log(path, overall_cpu, vm, sm, top_disk_pct, n_bad, n_warn):
    file_exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "cpu_pct", "mem_pct", "swap_pct",
                              "max_disk_pct", "n_bad_issues", "n_warn_issues"])
        writer.writerow([
            dt.datetime.now().isoformat(timespec="seconds"),
            f"{overall_cpu:.1f}", f"{vm.percent:.1f}", f"{sm.percent:.1f}",
            f"{top_disk_pct:.1f}", n_bad, n_warn,
        ])
    print(f"\n本次结果已追加写入日志: {path}")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="电脑变慢诊断脚本")
    parser.add_argument("--interval", type=float, default=2.0, help="采样窗口秒数 (默认 2 秒)")
    parser.add_argument("--top", type=int, default=10, help="每个排行榜显示多少条 (默认 10)")
    parser.add_argument("--full", action="store_true", help="额外显示单个进程明细")
    parser.add_argument("--no-color", action="store_true", help="关闭彩色输出")
    parser.add_argument("--log", type=str, default=None, help="把本次汇总结果追加写入指定 CSV 文件,便于以后对比趋势")
    args = parser.parse_args()

    if args.no_color or not sys.stdout.isatty():
        C.enabled = False

    print(C.bold(f"电脑变慢诊断脚本 — {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
    print(f"采样窗口: {args.interval}s   Top N: {args.top}")

    # 先给进程 CPU/IO 计数器预热一次(见 snapshot_processes),再进行其它检测,
    # 最后统一 sleep(args.interval) 拿到进程指标的差值。
    procs0 = snapshot_processes()

    overall_cpu = check_cpu(args.interval)
    vm, sm = check_memory()
    check_disk_space()
    check_disk_io(args.interval)
    check_processes(args.interval, args.top, args.full, procs0)
    check_temperature()
    check_oom()
    print_conclusion()

    if args.log:
        max_disk_pct = 0.0
        for part in psutil.disk_partitions(all=False):
            try:
                max_disk_pct = max(max_disk_pct, psutil.disk_usage(part.mountpoint).percent)
            except Exception:
                pass
        n_bad = sum(1 for lvl, _ in ISSUES if lvl == "bad")
        n_warn = sum(1 for lvl, _ in ISSUES if lvl == "warn")
        write_log(os.path.expanduser(args.log), overall_cpu, vm, sm, max_disk_pct, n_bad, n_warn)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消。")
        sys.exit(130)
