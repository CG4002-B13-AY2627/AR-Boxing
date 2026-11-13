"""Live dashboard for +/-16 g and +/-2000 dps game gloves.

In FPGA mode, punch damage scales with measured acceleration by default.
Use --demo-intensity to override it with a fixed game intensity.
"""

from esp_ai_live_dashboard import run_cli


if __name__ == "__main__":
    run_cli(imu_sensitivity=(2048.0, 16.4), default_ai_dir=None,
            description=__doc__)
