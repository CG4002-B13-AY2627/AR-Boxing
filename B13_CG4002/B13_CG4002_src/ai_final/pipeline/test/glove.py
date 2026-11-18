import serial

from serial.tools import list_ports

from live_config import BAUD_RATE, LINE_FIELDS, LINE_PREFIX, SERIAL_TIMEOUT_S


def find_port():
    usb = [port.device for port in list_ports.comports() if port.vid is not None]

    if len(usb) != 1:
        raise SystemExit(
            f"{len(usb)} USB serial devices attached ({', '.join(usb) or 'none'}). "
            "Plug in the right glove alone, or name it with --port."
        )

    return usb[0]


def parse(line):
    prefix, _, rest = line.partition(",")
    values = rest.split(",")

    if prefix != LINE_PREFIX or len(values) != len(LINE_FIELDS):
        return None

    try:
        return dict(zip(LINE_FIELDS, map(int, values)))
    except ValueError:
        return None


class Glove:
    def __init__(self, port=None):
        self.port = port or find_port()

        try:
            self.serial = serial.Serial(self.port, BAUD_RATE, timeout=SERIAL_TIMEOUT_S)
        except serial.SerialException as exc:
            raise SystemExit(f"{self.port}: {exc}") from exc

        self.serial.reset_input_buffer()

    def readings(self):
        while True:
            try:
                line = self.serial.readline()
            except serial.SerialException as exc:
                raise SystemExit(f"{self.port}: {exc}") from exc

            reading = parse(line.decode("ascii", errors="ignore").strip())
            if reading is not None:
                yield reading

    def close(self):
        self.serial.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
