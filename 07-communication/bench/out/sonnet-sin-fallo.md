Thanks for the detail, this narrows the problem down quite a bit.

The log is fairly clear: the ANR (`12:03:41 ANR in MainActivity`) coincides with `PaymentViewModel.kt:118` (commit `7c1d0e9`) calling `provider.confirm()` synchronously on the main thread. If that call involves I/O (network, disk, or simply waiting for a response from the payment provider), it's going to block the UI thread for as long as that wait lasts, and that's exactly what cashiers perceive as "la pantalla se queda congelada al cobrar" (the screen freezes when charging). The 40 ms ping rules out a general connectivity problem, and the absence of OOM in the log rules out a memory issue; both point the same way: it isn't the network or memory, it's the main thread blocked waiting on that call.

That it hasn't reproduced yet on the test bench is expected if the provider responds quickly there: the bug doesn't depend on the network being bad, but on how long `confirm()` takes to return something. In production there's probably variability (a slower provider at certain times, retries, or an occasional slower-than-normal response) that isn't happening in the test environment.

To confirm and fix it, the most direct route is:

1. Check whether `confirm()` is a blocking call (network/disk) and, if so, move it off the main thread (a coroutine with `Dispatchers.IO`, for example), updating the UI asynchronously when it responds.
2. To reproduce it on the test bench, try simulating latency in the provider's response (a mock or proxy that delays the response by a few seconds) instead of relying on it happening "naturally."
3. If `confirm()` can't stop being synchronous because of the provider's SDK constraints, at the very least it needs a timeout and visual feedback, so the screen never stays frozen indefinitely.

If it works for you, the logical move would be for the app team to move that call off the main thread as a first step, and in parallel I can help you set up the simulated-latency scenario on the test bench to verify it fixes the ANR before shipping to production. Let me know if that makes sense and we move ahead that way.
