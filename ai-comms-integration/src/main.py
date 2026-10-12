from ai_process import start_ai
from queues import make_queues
from comms_link import install_hook, run_comms


def main():
    in_q, out_q = make_queues()
    start_ai(in_q, out_q)
    install_hook(in_q)
    run_comms()


if __name__ == "__main__":
    main()
