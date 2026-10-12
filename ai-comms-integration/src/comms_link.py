import queue

from config import load_comms_server


def install_hook(in_q):
    comms_server = load_comms_server()

    def hooked(sess, fields):
        try:
            in_q.put_nowait(fields)
        except queue.Full:
            pass

    comms_server.match_pipeline_reply = hooked


def run_comms():
    load_comms_server().main()
