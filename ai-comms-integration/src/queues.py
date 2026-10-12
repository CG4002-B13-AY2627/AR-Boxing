import multiprocessing as mp

from config import IN_QUEUE_MAXSIZE, MP_START_METHOD, OUT_QUEUE_MAXSIZE


def make_queues():
    ctx = mp.get_context(MP_START_METHOD)
    return ctx.Queue(maxsize=IN_QUEUE_MAXSIZE), ctx.Queue(maxsize=OUT_QUEUE_MAXSIZE)
