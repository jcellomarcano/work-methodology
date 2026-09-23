The screen freezes because the charge blocks the main thread, not because of the network or low memory.

- Symptom: the log confirms an ANR (the app stops responding to the system) at 12:03:41 in `MainActivity`.
- Cause: `PaymentViewModel.kt:118` (commit `7c1d0e9`) calls `provider.confirm()` synchronously on the main thread, the same one that draws the screen.
- Ruled out: the network, the ping was 40 ms.
- Ruled out: low memory, the log shows no OOM.
- Pending: the failure hasn't reproduced on the test bench yet.

Next step: move `provider.confirm()` to a secondary thread (or make it asynchronous) and reproduce the ANR on the test bench before shipping the fix.

Not tested: the cause isn't confirmed by reproduction, it rests on the log and the code reading.

## Technical detail

- [Measured] ANR in `MainActivity` at 12:03:41.
- [Measured] Network ping of 40 ms at the time of the failure.
- [Measured] No OOM entries in the log.
- [Inferred] `provider.confirm()` in `PaymentViewModel.kt:118` (commit `7c1d0e9`) runs synchronously on the main thread and blocks rendering; this matches the typical ANR pattern.
- [Unknown] Whether `provider.confirm()` is slow because of the payment provider or some other internal wait.
- [Unknown] Root cause unconfirmed: it hasn't been reproduced yet on the test bench.
