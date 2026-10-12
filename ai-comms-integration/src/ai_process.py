import multiprocessing as mp
import os
import queue
import signal

from config import MP_START_METHOD, QUEUE_GET_TIMEOUT_S
from emitter import Emitter
from inference import Inference
from packet_monitor import PacketMonitor
from pipeline import Pipeline


def run_ai(in_q, out_q, parent_pid):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    monitor = PacketMonitor()
    emitter = Emitter(out_q)

    with Inference() as inference:
        pipeline = Pipeline(inference, monitor)

        while os.getppid() == parent_pid:
            try:
                emitter.emit(*pipeline.push(in_q.get(timeout=QUEUE_GET_TIMEOUT_S)))
            except queue.Empty:
                pass
            monitor.report()


def start_ai(in_q, out_q):
    ctx = mp.get_context(MP_START_METHOD)
    proc = ctx.Process(target=run_ai, args=(in_q, out_q, os.getpid()), daemon=True)
    proc.start()
    return proc
