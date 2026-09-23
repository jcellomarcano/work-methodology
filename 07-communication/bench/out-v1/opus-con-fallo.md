The screen freezes because the charge runs on the same thread that draws the screen: while the provider answers, the app can't paint anything and Android flags it as "not responding" (ANR).

- Symptom, as the cashier sees it: they tap charge and the register goes still; the log records it at 12:03:41 as `ANR in MainActivity`.
- Cause: in `PaymentViewModel.kt:118` (commit 7c1d0e9) `provider.confirm()` is called synchronously on the main thread. That thread is the only one that draws, so while it waits for the response, it draws nothing.
- Analogy: the main thread is a single cashier; the call to the provider is a phone inquiry. While the cashier is on the phone, the line doesn't move. Where it breaks: here the customer doesn't see the cashier on the phone, they just see the frozen screen and think the register broke.
- What it is NOT: not the network (40 ms ping) nor low memory (no OOM in the log). That it doesn't reproduce on the test bench rules nothing out: there the provider answers faster and the blocking doesn't reach the ANR threshold.

Next step: take `provider.confirm()` off the main thread and leave the screen in a "charging" state while it responds. I need from you: confirmation on whether I touch that file on top of 7c1d0e9 or open a separate branch, and the maximum acceptable wait time for the cashier.

## Technical detail

- [Measured] `12:03:41 ANR in MainActivity` in the terminal's log.
- [Measured] 40 ms network latency at the time of the failure; no OOM entries in the same log.
- [Measured] `PaymentViewModel.kt:118` @ 7c1d0e9 invokes `provider.confirm()` with no thread switch.
- [Inferred] The synchronous block on the main thread exceeds Android's ANR threshold (5 s for user input) and produces the reported freeze: "la pantalla se queda congelada al cobrar" (the screen freezes when charging).
- [Assumed] `provider.confirm()` performs blocking network I/O; its actual duration at the register isn't instrumented.
- [Unknown] p95 duration of `provider.confirm()` in production; Android version and model of the affected terminals.

Not tested: it hasn't been reproduced on the test bench; the full ANR trace (`/data/anr/traces.txt`), which would show the main thread stuck inside `confirm()`, hasn't been read; the provider's latency hasn't been measured, only the ping. To close the diagnosis: pull that trace from an affected terminal and add a timer around the call.
