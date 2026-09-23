The screen freezes because the charge calls `provider.confirm()`, and that call blocks the main thread (the part of the program that draws the screen and handles taps).

- Cause: in `PaymentViewModel.kt:118` (commit `7c1d0e9`), the call to `provider.confirm()` is synchronous on the main thread. While it waits for the provider's response, the screen can't draw or respond to the cashier's tap.
- Evidence: the log shows `ANR in MainActivity` at 12:03:41 (ANR: "the app is not responding"), right when that line runs.
- Ruled out: not the network (40 ms ping, normal) nor low memory (no OOM in the log).
- Pending: the failure hasn't reproduced yet on the test bench.

Next step: move `provider.confirm()` to a background thread, so the main one stays free while it waits for the response.

## Technical detail

- [Measured] Log: `12:03:41 ANR in MainActivity`.
- [Measured] `PaymentViewModel.kt:118` @ `7c1d0e9`: `provider.confirm()` invoked synchronously on the main thread.
- [Measured] Network: 40 ms ping at the time of the report.
- [Measured] Log with no OOM entries.
- [Inferred] The synchronous call blocks the main thread long enough to trigger the ANR; it matches the log in time and file.
- [Unknown] It hasn't been reproduced on the test bench: the exact blocking time still needs confirming, and whether `provider.confirm()` has its own timeout.
