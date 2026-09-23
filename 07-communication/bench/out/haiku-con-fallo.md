The screen freezes because `provider.confirm()` runs blocking on the main UI thread.

Symptom: ANR in MainActivity at 12:03:41 while the cashier tries to charge.

Cause: `PaymentViewModel.kt:118` @ 7c1d0e9 runs a synchronous call on the UI thread. This blocks the interface for the whole operation.

What it is NOT:
- Not network congestion: ping at 40 ms.
- Not low memory: no OOM in the log.

Next step:
Move `provider.confirm()` to a background thread (Kotlin coroutines or ThreadPool). Update the UI from the result.

Not tested:
The failure does not reproduce on the test bench; verify with the real cashier's data and network.
