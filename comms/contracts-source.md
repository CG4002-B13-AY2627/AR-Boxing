# Deployable protocol mirror

`contracts/` is a deployment copy of the canonical `CG4002-Viz/contracts` schemas, examples, README and contract test. Files use portable LF line endings. Keep its ten schemas and all golden examples synchronized when changing the wire contract; CG4002-Viz remains the source of truth.

Copy this directory with the Ultra96 Python files. For `~/comms/esp_ai_live/*.py`, deploy it as `~/comms/contracts/`. All schema JSON files sit directly in that directory, without another nested `contracts` folder. The server finds this layout automatically or accepts `--contracts-dir /home/xilinx/comms/contracts`.

Verify the deployed copy from the comms directory:

```bash
python3 -B -m unittest discover -s contracts -p 'test_*.py'
python3 -B -m unittest discover -s Ultra96 -p 'test_*.py'
```

The deployment copy added on 29 October 2026 contains 10 schemas and 22 golden examples. Generated Python caches are excluded.
