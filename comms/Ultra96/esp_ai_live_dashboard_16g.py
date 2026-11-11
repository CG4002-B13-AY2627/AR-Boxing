"""Live dashboard for game gloves configured for +/-16 g and +/-2000 dps."""

from esp_ai_live_dashboard import run_cli


if __name__ == "__main__":
    run_cli(imu_sensitivity=(2048.0, 16.4), default_ai_dir=None)
