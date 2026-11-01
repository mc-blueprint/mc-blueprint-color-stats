"""計算を子プロセスに分離し、停止フラグで中断する単一スロットワーカー。"""

import importlib
import multiprocessing
import threading
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic, sleep

from sqlalchemy.exc import SQLAlchemyError

from colorstats.queue.core import Claim, LeaseLost, Queue, RunInfo


@dataclass
class Prepared:
    """prepareの戻り値。dataは小さいpickle可能値、filesは一時パスと出力名。

    実際の不変パスはregister時のrun.output_pathsから取得する。
    """

    info: RunInfo
    data: object = None
    files: list[tuple[Path, Path]] = field(default_factory=list)


def _prepare(module_name, claim, pipe):
    try:
        module = importlib.import_module(module_name)
        pipe.send((True, module.prepare(claim)))
    except Exception as error:
        pipe.send((False, f"{type(error).__name__}: {error}"))
    finally:
        pipe.close()


class Worker:
    """handlersはstage→モジュール名。prepare(claim)とregister(session, run, data)を実装。

    prepareは試行固有の一時ファイルだけを書き、DBや確定先を変更しない。
    registerは親プロセスの完了取引内でDB登録のみを行う。
    """

    def __init__(
        self, queue: Queue, handlers: dict[str, str], stop_file: Path, poll_interval: float = 0.2
    ):
        if poll_interval <= 0:
            raise ValueError("ポーリング間隔は正の値が必要です")
        self.queue = queue
        self.handlers = handlers
        self.stop_file = stop_file
        self.poll_interval = poll_interval

    def run(self, *, once: bool = False) -> None:
        """停止ファイル存在時に取得・計算を止める。onceは最大1件を処理して戻る。"""
        while not self.stop_file.exists():
            claim = self.queue.claim(tuple(self.handlers))
            if claim is None:
                if once:
                    return
                sleep(self.poll_interval)
                continue
            self._run_claim(claim)
            if once:
                return

    def _run_claim(self, claim: Claim):
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_prepare, args=(self.handlers[claim.stage], claim, sender))
        try:
            process.start()
            sender.close()
            renew_at = monotonic() + self.queue.lease.total_seconds() / 3
            while True:
                if self.stop_file.exists():
                    self._stop(process)
                    self._return(claim)
                    return
                wait = min(self.poll_interval, max(0, renew_at - monotonic()))
                if receiver.poll(wait):
                    try:
                        success, result = receiver.recv()
                    except EOFError:
                        raise RuntimeError("計算プロセスが結果を返さず終了しました") from None
                    if not success:
                        raise RuntimeError(result)
                    if self.stop_file.exists():
                        self._stop(process)
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
                if not process.is_alive():
                    if receiver.poll():
                        continue
                    raise RuntimeError(f"計算プロセスの異常終了: {process.exitcode}")
                if monotonic() >= renew_at:
                    self.queue.renew(claim)
                    renew_at = monotonic() + self.queue.lease.total_seconds() / 3
        except LeaseLost:
            pass
        except Exception as error:
            try:
                self.queue.fail(claim, f"{type(error).__name__}: {error}")
            except LeaseLost:
                pass
        finally:
            if process.pid is not None:
                self._stop(process)
                process.close()
            receiver.close()
            sender.close()

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
