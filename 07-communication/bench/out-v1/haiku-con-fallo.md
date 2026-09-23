`provider.confirm()` on the main thread blocks the UI while it waits for the network, even with a 40 ms ping.

The ANR (Application Not Responding) happens because the synchronous call occupies the main thread. Even though the network is fast, the block is enough: 40 ms × repeated confirmations + local processing add up past Android's ANR threshold (5 seconds of blocked UI).

It doesn't reproduce on the test bench because the network there is even faster, or there's less concurrent load on the device.

## Technical detail

- `[Measured]` ANR log at 12:03:41 in `PaymentViewModel.kt:118`.
- `[Inferred]` Network latency (40 ms) plus local processing time adds up enough to trigger an ANR if it repeats or the device is under load.
- `[Assumed]` `provider.confirm()` makes a network call: there's no OOM, so the block is the culprit, not memory.
- `Not tested:` whether there are multiple consecutive confirmations, or whether the device's CPU is busy.

Next step: move `provider.confirm()` to a background thread with a coroutine or `AsyncTask`, and update the UI from the main thread once it finishes.
