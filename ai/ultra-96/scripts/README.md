# `ultra-96/scripts/` — what each script does

Every file here is shipped by `transfer.sh` to the **root of a run** on the board,
`~/ai/<run>/`, beside the `bitstream/` it drives and above the `src/` it runs. Edit them here,
never on the board.

Listed in the order you would reach for them: does it work, does it join up, is it fast
enough, what does it cost, and what can we do about that.

| Script | What it does |
|---|---|
| `verify.sh` | Replays the golden set through the accelerator and compares **logits bit-exactly** against what Brevitas produced. This is the correctness claim — tier 4 of the five-tier verification. `./verify.sh 20` checks the first 20 instead of all 440. |
| `test.sh` | Pushes a stream through the whole PS path — windowing, pre-processing, inference, post-processing. Proves the four stages join up and that each window is the right slice of the stream. **With no `sample/` in the run** the stream is dummy data, it ends in action events, and it cannot check the labels. **With `sample/segment.txt`** — real IMU rows sent by [`individual-subcomponent-test`](../../individual-subcomponent-test/README.md) — it prints every window's raw logits and predicted class as a table and saves it as `sample/hardware_logits.txt`, to compare against the laptop's software run of the same segment. |
| `latency.sh` | Times both halves of the critical path in one sitting and prints them as one table against the ≤ 50 ms commitment: the PS work, the accelerator round trip, and the stride the window spends closing. Exits non-zero if any row misses its bound. |
| `power.sh` | Reads the board's own INA226 rails while the accelerator is idle, saturated, and paced at the real stride. The totals are what the wearable draws; the deltas against idle are the marginal cost of an inference. It also logs **die temperature per regime** from the AMS block — not a result in itself, but the evidence that those deltas are a load difference rather than a thermal ramp, which a passively cooled board cannot otherwise rule out. |
| `pmanagement.sh` | Demo heading 7. Measures **every combination** of CPU cores × CPU frequency × PL clock that the board exposes — 36 points on this board — replaying the whole golden set and holding each to `latency.sh`'s PS, PL and total bounds, then ranks the eligible ones by power and asks which to leave applied. Then the radios: it finds which radio controls the image exposes and which link carries the SSH session, measures each radio off against on, and asks again, offering only savings it verified. Writes `pmanagement/<timestamp>/report.md`. `apply` picks from the last sweep without re-measuring; `restore` puts everything back. Nothing is left applied unless it is picked. |

`power.sh` answers *what does the board draw*; `pmanagement.sh` answers *what can we do about it*.

A radio is only switched off if neither the SSH session nor the default route runs over it, and
every time it is, a detached dead-man timer is armed that turns it back on if the run loses
contact. If the session does drop, wait for that timer — about 90 s — rather than rebooting.

If a run arrived from Windows the executable bit will not have survived the copy — NTFS has
none to send. Then `bash <script>` rather than `./<script>`.
