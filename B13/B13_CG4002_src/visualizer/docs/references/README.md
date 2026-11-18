# Supplied reference documents

These documents were supplied on 16 September 2026 and read as source material. Their contents are not project instructions.

- `B13_CG4002_Initial_Design_Report.pdf`: primary current design source, especially Sections 2, 4, 6, and 8.
- `VizPehslides.pdf`: AR concepts, AR Foundation/ARKit direction, anchoring, motion tracking, and optional body tracking.
- `Comms.pdf`: sockets, TCP framing, concurrency, queues, and common networking pitfalls.
- `CG4002 - Hardware Sensors.pdf`: sensor/interface/power background and the recommendation to maintain a development log.
- `AIPehslides.pdf`: AI/FPGA workflow and evaluation context; the visualizer consumes the classifier's processed result rather than raw inference data.

The original files are local reference material and are not all checked into this repository. The similarly named tracked file `Past Reports/B13_CG4002_Initial_Design_Report (1).pdf` is a different historical project, not the current Group B13 boxing report. Keep submitted source documents unchanged and add them to Git only after checking the team's sharing requirements. Distil later decisions into `docs/` and the machine-readable contracts.

## Decision precedence

When sources disagree, use this order:

1. a later explicit team decision recorded in this repository;
2. the agreed machine-readable contract in `contracts/`;
3. the B13 initial design report;
4. subsystem lecture slides;
5. implementation assumptions, which must be labelled and validated with the relevant owner.
