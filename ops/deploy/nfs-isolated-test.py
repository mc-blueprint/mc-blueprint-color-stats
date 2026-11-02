"""試験exportだけを専用net/mount名前空間のTCP中継で停止・復帰させる。

ubuntu-1でsudo実行。ubuntu-2の一時exportは別途用意する。
既存NFS、ホストの経路・firewall・fstabは変更しない。
"""

import argparse
import ctypes
import hashlib
import json
import os
import select
import socket
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path("/mnt/issue42-test")
EXPORT = "/mnt/data/work/issue-42/nfs-test"
STATE = Path("/var/tmp/issue-42")


def event(name, **values):
    print(json.dumps({"event": name, "time": time.time(), **values}), flush=True)


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--durations", type=int, nargs="+", default=[15, 630])
    args = parser.parse_args()
    if socket.gethostname() != "ubuntu-1" or os.geteuid() != 0:
        raise SystemExit("ubuntu-1上でsudo実行してください")
    STATE.mkdir(exist_ok=True)
    log_root = STATE / f"run-{int(time.time())}"
    log_root.mkdir()
    ROOT.mkdir(exist_ok=True)
    original_net = os.open("/proc/self/ns/net", os.O_RDONLY)

    def connect():
        connection = socket.socket()
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        connection.bind(("192.168.1.85", 742))
        connection.settimeout(10)
        connection.connect(("192.168.1.86", 2049))
        connection.settimeout(None)
        return connection

    upstream = connect()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.unshare(0x40000000 | 0x00020000) != 0:  # NEWNET | NEWNS
        raise OSError(ctypes.get_errno(), "unshare")
    run("mount", "--make-rprivate", "/")
    run("ip", "link", "set", "lo", "up")
    isolated_net = os.open("/proc/self/ns/net", os.O_RDONLY)
    event("isolated", netns=os.readlink("/proc/self/ns/net"))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 20490))
    listener.listen(1)
    forwarding = threading.Event()
    forwarding.set()
    paused = threading.Event()

    def relay():
        nonlocal upstream
        client, _ = listener.accept()
        while True:
            if not forwarding.is_set():
                paused.set()
                forwarding.wait()
                paused.clear()
            readable, _, _ = select.select([upstream, client], [], [], 0.1)
            if upstream in readable and not upstream.recv(1, socket.MSG_PEEK):
                upstream.close()
                os.setns(original_net, 0)
                try:
                    upstream = connect()
                finally:
                    os.setns(isolated_net, 0)
                event("upstream_reconnected")
                continue
            sockets = {client: upstream, upstream: client}
            for source in readable:
                data = source.recv(1048576)
                if not data:
                    return
                sockets[source].sendall(data)

    threading.Thread(target=relay, daemon=True).start()
    mounted = False
    children = []
    try:
        run(
            "mount", "-t", "nfs", "-o",
            "vers=4.2,proto=tcp,port=20490,nconnect=1,hard,timeo=600,retrans=2,nosharecache",
            f"127.0.0.1:{EXPORT}", str(ROOT),
        )
        mounted = True
        event("mounted", options=run("findmnt", "-rn", "--mountpoint", str(ROOT)))
        event("baseline", sha256=hashlib.sha256((ROOT / "baseline").read_bytes()).hexdigest())
        for duration in args.durations:
            forwarding.clear()
            if not paused.wait(5):
                raise RuntimeError("中継を停止できません")
            event("outage_begin", duration=duration)
            handles = []
            for operation in ("read", "write"):
                log = (log_root / f"{operation}-{duration}.jsonl").open("w")
                code = (
                    "import os,time,json,hashlib; from pathlib import Path; "
                    f"p=Path({str(ROOT)!r})/{f'{operation}-{duration}'!r}; "
                    "print(json.dumps({'event':'io_begin','time':time.time()}),flush=True); "
                )
                if operation == "read":
                    code += "data=p.read_bytes(); "
                else:
                    code += (
                        "data=b'issue42-write'*8192; "
                        "f=p.open('wb'); f.write(data); f.flush(); os.fsync(f.fileno()); "
                        "f.close(); p.rename(p.with_suffix('.done')); "
                        "data=p.with_suffix('.done').read_bytes(); "
                    )
                code += (
                    "print(json.dumps({'event':'io_end','time':time.time(),"
                    "'sha256':hashlib.sha256(data).hexdigest()}),flush=True)"
                )
                process = subprocess.Popen(
                    ["python3", "-u", "-c", code], stdout=log, stderr=log,
                    user=1000, group=1000,
                )
                children.append(process)
                handles.append(log)
            started = time.monotonic()
            next_report = 0
            while time.monotonic() - started < duration:
                elapsed = time.monotonic() - started
                if elapsed >= next_report:
                    event("waiting", elapsed=elapsed, processes=[
                        {"pid": p.pid, "exit": p.poll(),
                         "wchan": (
                             Path(f"/proc/{p.pid}/wchan").read_text() if p.poll() is None else ""
                         )}
                        for p in children[-2:]
                    ])
                    next_report += 30
                time.sleep(1)
            forwarding.set()
            event("outage_end", duration=duration)
            for process, log in zip(children[-2:], handles, strict=True):
                process.wait(timeout=180)
                log.close()
                if process.returncode:
                    raise RuntimeError(f"I/O失敗: {process.returncode}")
            event("resumed", duration=duration)
            for operation in ("read", "write"):
                print((log_root / f"{operation}-{duration}.jsonl").read_text(), flush=True)
    finally:
        forwarding.set()
        for process in children:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        if mounted:
            run("umount", str(ROOT))
            event("unmounted")
        listener.close()
        upstream.close()
        os.close(original_net)
        os.close(isolated_net)
    event("finished")


if __name__ == "__main__":
    main()
