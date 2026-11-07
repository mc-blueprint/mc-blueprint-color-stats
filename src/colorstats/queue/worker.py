"""計算を子プロセスに分離し、停止フラグで中断する単一スロットワーカー。"""

import errno
import importlib
import multiprocessing
import socket
import threading
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from time import monotonic, sleep

from sqlalchemy.exc import SQLAlchemyError

from colorstats.queue.core import Claim, LeaseLost, NonRetryableError, Queue, RunInfo
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


@dataclass(frozen=True)
class Deferred:
    """次回取得まで延期する。実際のAPI失敗だけconsume_attemptを指定する。"""

    reason: str
    delay: timedelta
    consume_attempt: bool = False


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
                if claim.stage == "review" and claim.payload.get("kind") == "image_gate":
                    result = (True, module.prepare_job(claim))
                else:
                    result = (True, module.prepare(claim))
            except Exception as error:
                result = (
                    False,
                    (
                        f"{type(error).__name__}: {error}",
                        error.errno if isinstance(error, OSError) else None,
                        not isinstance(error, NonRetryableError),
                    ),
                )
            connection.send(result)
    finally:
        connection.close()


class Worker:
    """handlersはstage→モジュール名。prepare(claim)とregister(session, run, data)を実装。

    prepareは試行固有の一時ファイルだけを書き、DBや確定先を変更しない。
    registerは親プロセスの完了取引内でDB登録のみを行う。
    reviewのkind=image_gateは子プロセスでAPI台帳を先行確定し、共通ループでleaseを更新する。
    """

    def __init__(
        self,
        queue: Queue,
        handlers: dict[str, str],
        stop_file: Path,
        poll_interval: float = 0.2,
        *,
        storage_paths: dict[str, tuple[Path, ...]] | None = None,
        provider: str | None = None,
    ):
        if poll_interval <= 0:
            raise ValueError("ポーリング間隔は正の値が必要です")
        self.queue = queue
        self.handlers = handlers
        self.stop_file = stop_file
        self.poll_interval = poll_interval
        self.storage_paths = storage_paths or {}
        self.provider = provider
        self._provider_lease = None
        self._process = None
        self._connection = None
        self._prepared_count = 0

    def _available(self, stage):
        return storage_available(stage, self.storage_paths.get(stage, ()))

    def run(self, *, once: bool = False) -> None:
        """停止ファイル存在時に取得・計算を止める。onceは最大1件を処理して戻る。"""
        try:
            if self.provider is not None:
                from colorstats.collect.limits import ProviderLease

                if socket.gethostname() != "ubuntu-1":
                    raise ValueError("provider別collectは保存契約確認済みのubuntu-1専用です")
                self._provider_lease = ProviderLease(self.queue, self.provider)
                self._provider_lease.acquire()
            while not self.stop_file.exists():
                if self._provider_lease is not None:
                    self._provider_lease.renew()
                stages = tuple(stage for stage in self.handlers if self._available(stage))
                options = {"provider": self.provider} if self.provider is not None else {}
                claim = self.queue.claim(stages, **options) if stages else None
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
            if self._provider_lease is not None:
                self._provider_lease.release()
                self._provider_lease = None

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
            if self.provider is not None and claim.payload["host"] != socket.gethostname():
                raise NonRetryableError("collectの保存先hostが実行hostと一致しません")
            if not self._available(claim.stage):
                self.queue.defer(claim, "保存先の復旧待ち")
                return
            self.queue.check_input(claim)
            module_name = (
                "colorstats." + claim.payload["kind"]
                if claim.stage == "review" and claim.payload.get("kind") in {
                    "image_gate", "privacy_review"}
                else self.handlers[claim.stage]
            )
            self._start_prepare()
            process = self._process
            preparing = True
            connection = self._connection
            received = threading.Event()
            response = []
            errors = []

            def communicate():
                try:
                    connection.send((module_name, claim))
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
                        message, number, retryable = result
                        if number in (errno.EROFS, errno.ENODEV, errno.ESTALE, errno.EIO):
                            self.queue.defer(claim, message)
                            return
                        if not retryable:
                            self.queue.fail(claim, message, retryable=False)
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
                    if isinstance(result, Deferred):
                        if result.consume_attempt:
                            self.queue.fail(claim, result.reason, delay=result.delay)
                        else:
                            self.queue.defer(claim, result.reason, delay=result.delay)
                        return
                    module = importlib.import_module(module_name)
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
                    if self._provider_lease is not None:
                        self._provider_lease.renew()
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
                    self.queue.fail(claim, f"{type(error).__name__}: {error}",
                                    retryable=not isinstance(error, NonRetryableError))
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
