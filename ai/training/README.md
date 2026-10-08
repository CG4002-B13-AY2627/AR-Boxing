# `src/` — what to run, and when

Everything runnable ships as a `.sh` **and** a `.bat` with the same name, arguments and behaviour.
On Windows use the `.bat`; the examples below drop the extension.

## The short answer

```
src\pipeline --name <run>            everything, archived as out\pipeline\<run>\   ~45 min
```

That is the command you want almost always. It runs the five stages in order, cleans first so a
run cannot inherit the last one's outputs, logs each stage, and copies everything worth keeping
into `out\pipeline\<run>\`. Everything below is either a piece of that, or an analysis of what
it produced.

After export, the pipeline asks whether HLS should run the full simulation flow or only
synthesize and export IP. Use `--hls-mode synth-export` to skip both C simulation and RTL
co-simulation; `--hls-mode full` selects the usual flow without prompting.

Runs are archived one level below `out\` under the script that wrote them — `out\pipeline\`,
`out\all\`, `out\sweep\` — so a run says which question it was answering before you open it.
`transfer` takes either `<run>` or `<kind>\<run>`, and only needs the second when two kinds
hold the same name.

## The pipeline, stage by stage

Each stage consumes the one above it. `src\scripts\<name>` runs one on its own, which is what you
want while iterating; `pipeline` is what you run when you want an archive.

Times are measured off `out\pipeline\mark-4\`, a full run on synthetic data totalling
45 minutes.

| # | Stage | What it does | Took |
|---|---|---|---|
| 1 | `train` | FP32 baseline, then the Brevitas QAT sweep at 8/7/6/5/4 bits. Selects a width and leaves exactly one checkpoint in `train\qmodel\`. **2 min only because the data is synthetic** — real collection moves this into the tens of minutes. | 2 min |
| 2 | `check` | One Brevitas pass, two checks: the board's `preprocess.py` against the `quant_input` hook, then the integer description against every quantizer. Exits non-zero if either fails. | 6 s |
| 3 | `export` | Extracts the description, writes `params_w<N>.hpp`, `weights_w<N>.hpp`, and the golden vectors as both a C header and a `.npz` the board can read. | 4 s |
| 4 | `hls` | Full: C simulation → synthesis → C/RTL co-simulation → packaged IP. `synth-export`: synthesis → packaged IP. **The long pole in the full flow is cosim** — ~19 min of it for 200 vectors. | 36 min (full) |
| 5 | `vivado` | Block design → implementation → `.bit` and `.hwh`, with timing, utilisation and power reports. | 7 min |

**`check` runs before `export` on purpose.** It re-extracts the description itself rather than
reading one off disk, so headers are never emitted from arithmetic that failed.

### Resuming

```
src\pipeline --name <run> --from hls        skip train, check and export
src\pipeline --name <run> --build E         a directive variant
```

`--from <stage>` cleans and runs from that stage onward, so it never deletes what the stage is
about to consume. Use it when the model has not changed and you are only rebuilding the hardware.

**The width is never an argument.** It is whatever training selected, read from
`fpga\hls\selected_width.hpp`. Retraining at another width carries it all the way to the bitstream
with no edit anywhere.

## The two comparisons

`pipeline` builds one point. These build a row of them and render the table, into their own
archive. `all` still archives one overlay, because one of its variants is the build that ships;
`sweep` archives none, because none of its widths is.

| Command | Varies | Holds fixed | Answers |
|---|---|---|---|
| `src\all --name <run>` | the directive set, A–D | the width | demo heading 6 — which optimisations were implemented, and what each cost |
| `src\sweep --name <run>` | the width, 8–4 | `--build`, default A | §5.6 — what a bit of precision costs in silicon, and where the network breaks |

`sweep` trains once, because training already sweeps the widths and leaves one checkpoint per
entry in `train\checkpoints\`; the rest is `check`, `export`, `hls` and `vivado` per width,
driven through `NN_CHECKPOINT_OVERRIDE`. **The selected width is built first and without an
override**, because its export is the one that writes `selected_width.hpp`, which `params.hpp`
includes unconditionally. Read the result in `out\sweep\<run>\summary\summary.md`.

## Housekeeping

| Command | What it does | Takes |
|---|---|---|
| `src\scripts\clean [stages]` | Deletes generated artefacts. With no arguments, all of them. `pipeline` runs this first, which is why a run never inherits the last one's outputs. | seconds |

**On power, and why there is no annotated estimate.** `vivado` writes a *vectorless* power report:
nobody tells it how often each wire toggles, so it assumes, and it comes out roughly 3× the rail
the board actually measures. Annotating it with recorded switching activity was attempted on
2026-09-21 and **does not work** — synthesis does not preserve HLS's net names, so activity
recorded from the RTL matches 0 of 23,417 nets in the implemented design. Quote the vectorless
figure beside the board's own measurement (`power.sh`), which is the stronger evidence anyway.

## Getting it onto the board

```
ultra-96\transfer --name <run>
```

Ships one archived `pipeline` or `all` run to `~/ai/<run>/` on the Ultra96 — the bitstream, the
hardware handoff, the normalisation stats, the interface contract, the golden set, plus the host
code and the scripts that drive it. A `sweep` run has no bitstream and is refused. What to run once it is there is in
[`ultra-96/scripts/README.md`](../ultra-96/scripts/README.md).

## A typical session

```
src\pipeline --name mark-7               build it                  ~60 min
ultra-96\transfer --name mark-7          send it to the board
                                         then, on the board:
  bash verify.sh                         440/440 bit-exact?
  bash latency.sh                        the timing table
  bash power.sh                          rails and die temperature
  bash pmanagement.sh                    power configurations, swept and picked
```

## Things that will bite you

- **A run starts from nothing.** `clean` removes every pre-existing artefact first, by design: a
  run that dies in HLS must never archive the previous run's bitstream and present it as its own.
  The corollary is that `out\<kind>\<run>\` is the **only** copy of anything git does not
  hold.
- **A sweep archives no bitstream, on purpose.** It answers what a width costs, not what ships;
  `transfer` refuses one and says why. The build that goes to the board comes from `pipeline`.
- **The archive holds outputs, not projects.** `out\<kind>\<run>\` has the bitstream, the
  headers, the reports and the logs. It does not have `hls_w*_*` or `vivado_w*_*`, which are gitignored and
  regenerable — so anything needing an *open* Vivado design needs the build present, not just
  archived.
- **Co-simulation is slow.** About 19 minutes for 200 vectors. `src\scripts\hls 6 A 2` runs two
  vectors instead, for a smoke test while iterating.
- **Generated headers are committed, checkpoints are not.** The header is the interface between
  the Python half and the Vitis half, and Vitis runs where the virtualenv does not exist.
- **Never hand-edit a `*_w<N>.*` file.** That suffix means generated. Everything else in
  `fpga\hls\` is hand-written.

## Where the rules live

`train\config.py` owns every dimension of the model, and `scripts\build_config.py` owns every path,
generated name and environment variable this layer uses — with `scripts\sweep_config.py` doing the
same for the width sweep's own stage names, archive directories and report paths. Nothing else
restates one. The test to
apply before writing any new file: **changing the selected width, the window size or the class
count should touch one line, not one line per consumer.**
