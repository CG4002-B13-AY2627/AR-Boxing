import queue
import threading

from config import load_ai_events, load_comms_server


def install_hook(in_q):
    comms_server = load_comms_server()

    def hooked(sess, fields):
        try:
            in_q.put_nowait(fields)
        except queue.Full:
            pass

    comms_server.match_pipeline_reply = hooked


def start_forwarder(out_q):
    ai_events = load_ai_events()

    def forward():
        while True:
            ai_events.publish(out_q.get())

    threading.Thread(target=forward, daemon=True).start()


def run_comms():
    load_comms_server().main()
