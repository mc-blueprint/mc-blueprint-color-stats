"""計算を子プロセスに分離し、停止フラグで中断する単一スロットワーカー。"""

import errno
import importlib
import multiprocessing
import threading
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic, sleep

from sqlalchemy.exc import SQLAlchemyError

from colorstats.queue.core import Claim, LeaseLost, Queue, RunInfo
from colorstats.queue.storage import storage_available

MAX_PREPARES = 256


@dataclass
class Prepared:
    """prepareの戻り値。dataは小さいpickle可能値、filesは一時パスと出力名。

    実際の不変パスはregister時のrun.output_pathsから取得する。
    """

    info: RunInfo
    data: object = None
    files: list[tuple[Path, Path]] = field(default_factory=list)


def _prepare(connection):
    try:
        while True:
            try:
                request = connection.recv()
            except EOFError:
                return
            if request is None:
                return
            module_name, claim = request
            try:
                module = importlib.import_module(module_name)
                result = (True, module.prepare(claim))
            except Exception as error:
                result = (
                    False,
                    (
                        f"{type(error).__name__}: {error}",
                        error.errno if isinstance(error, OSError) else None,
                    ),
                )
            connection.send(result)
    finally:
        connection.close()


class Worker:
    """handlersはstage→モジュール名。prepare(claim)とregister(session, run, data)を実装。

    prepareは試行固有の一時ファイルだけを書き、DBや確定先を変更しない。
    registerは親プロセスの完了取引内でDB登録のみを行う。
    """

    def __init__(
        self,
        queue: Queue,
        handlers: dict[str, str],
        stop_file: Path,
        poll_interval: float = 0.2,
        *,
        storage_paths: dict[str, tuple[Path, ...]] | None = None,
    ):
        if poll_interval <= 0:
            raise ValueError("ポーリング間隔は正の値が必要です")
        self.queue = queue
        self.handlers = handlers
        self.stop_file = stop_file
        self.poll_interval = poll_interval
        self.storage_paths = storage_paths or {}
        self._process = None
        self._connection = None
        self._prepared_count = 0

    def _available(self, stage):
        return storage_available(stage, self.storage_paths.get(stage, ()))

    def run(self, *, once: bool = False) -> None:
        """停止ファイル存在時に取得・計算を止める。onceは最大1件を処理して戻る。"""
        try:
            while not self.stop_file.exists():
                stages = tuple(stage for stage in self.handlers if self._available(stage))
                claim = self.queue.claim(stages) if stages else None
                if claim is None:
                    if once:
                        return
                    sleep(self.poll_interval)
                    continue
                self._run_claim(claim)
                if once:
                    return
        finally:
            self._stop_prepare()

    def _start_prepare(self):
        if self._process is not None and self._process.is_alive():
            if self._prepared_count < MAX_PREPARES:
                return
            self._stop_prepare()
        self._close_prepare()
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(target=_prepare, args=(child,))
        try:
            process.start()
        except Exception:
            parent.close()
            child.close()
            raise
        child.close()
        self._process = process
        self._connection = parent
        self._prepared_count = 0

    def _close_prepare(self):
        if self._process is not None and self._process.pid is not None:
            if self._process.is_alive():
                self._stop(self._process)
            else:
                self._process.join()
            self._process.close()
        if self._connection is not None:
            self._connection.close()
        self._process = self._connection = None

    def _stop_prepare(self):
        if self._process is not None and self._process.is_alive():
            try:
                self._connection.send(None)
            except (BrokenPipeError, OSError):
                pass
            self._process.join(timeout=1)
            if self._process.is_alive():
                self._stop(self._process)
        self._close_prepare()

    def _run_claim(self, claim: Claim):
        process = None
        exchange = None
        discard_process = False
        preparing = False
        try:
            if not self._available(claim.stage):
                self.queue.defer(claim, "保存先の復旧待ち")
                return
            self._start_prepare()
            process = self._process
            preparing = True
            connection = self._connection
            received = threading.Event()
            response = []
            errors = []

            def communicate():
                try:
                    connection.send((self.handlers[claim.stage], claim))
                    response.append(connection.recv())
                except Exception as error:
                    errors.append(error)
                finally:
                    received.set()

            exchange = threading.Thread(target=communicate, daemon=True)
            exchange.start()
            renew_at = monotonic() + self.queue.lease.total_seconds() / 3
            while True:
                if not self._available(claim.stage):
                    self._close_prepare()
                    self.queue.defer(claim, "保存先の復旧待ち")
                    return
                if self.stop_file.exists():
                    self._close_prepare()
                    self._return(claim)
                    return
                wait = min(self.poll_interval, max(0, renew_at - monotonic()))
                if received.wait(wait):
                    if errors:
                        discard_process = True
                        raise RuntimeError("計算プロセスとの通信に失敗しました") from errors[0]
                    success, result = response[0]
                    preparing = False
                    self._prepared_count += 1
                    if not success:
                        message, number = result
                        if number in (errno.EROFS, errno.ENODEV, errno.ESTALE, errno.EIO):
                            self.queue.defer(claim, message)
                            return
                        raise RuntimeError(message)
                    if not self._available(claim.stage):
                        self._stop_prepare()
                        self.queue.defer(claim, "保存先の復旧待ち")
                        return
                    if self.stop_file.exists():
                        self._stop_prepare()
                        self._return(claim)
                        return
                    module = importlib.import_module(self.handlers[claim.stage])
                    self.queue.complete(
                        claim,
                        result.info,
                        lambda session, run, module=module, result=result: module.register(
                            session, run, result.data
                        ),
                        result.files,
                    )
                    return
                if monotonic() >= renew_at:
                    self.queue.renew(claim)
                    renew_at = monotonic() + self.queue.lease.total_seconds() / 3
        except LeaseLost:
            discard_process = preparing
        except Exception as error:
            discard_process = discard_process or preparing
            try:
                if not self._available(claim.stage) or (
                    isinstance(error, OSError)
                    and error.errno in (errno.EROFS, errno.ENODEV, errno.ESTALE, errno.EIO)
                ):
                    self.queue.defer(claim, "保存先の復旧待ち")
                else:
                    self.queue.fail(claim, f"{type(error).__name__}: {error}")
            except LeaseLost:
                pass
        except BaseException:
            discard_process = True
            raise
        finally:
            if discard_process:
                self._close_prepare()
            elif self._process is process and process is not None and not process.is_alive():
                self._close_prepare()
            if exchange is not None:
                exchange.join(timeout=1)

    @staticmethod
    def _stop(process):
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)

    def _return(self, claim):
        def fail():
            try:
                self.queue.fail(claim, "停止フラグによる中断")
            except (LeaseLost, SQLAlchemyError):
                pass

        thread = threading.Thread(target=fail, daemon=True)
        thread.start()
        thread.join(timeout=2)
