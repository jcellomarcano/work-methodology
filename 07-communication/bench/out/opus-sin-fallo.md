With what's here, the main hypothesis is clear: **it's an ANR from a blocked main thread, not a network or memory problem**.

**Why it fits**

- `ANR in MainActivity` means the UI thread went unresponsive for more than ~5 s. The "frozen" screen cashiers report is exactly that: the UI is still drawn, but it isn't processing events.
- `PaymentViewModel.kt:118` @ `7c1d0e9` calls `provider.confirm()` synchronously on the main thread. A payment confirmation call involves network I/O (TLS handshake + processing at the issuer/acquirer). It's enough for the provider to be slow to respond for the UI thread to freeze.
- The 40 ms `ping` **doesn't rule this out**, and it shouldn't be read as "the network was fine" in the sense that matters here: it measures the ICMP round trip, not the confirmation operation's response time. A backend that takes 8 s to authorize is perfectly compatible with a 40 ms ping.
- The absence of OOM rules out the other usual cause of freezing (GC thrashing / memory pressure). That strengthens the blocking hypothesis, it doesn't weaken it.
- That it doesn't reproduce on the test bench is expected: there, the provider is usually a stub or sandbox that responds in milliseconds, so the blocking never reaches the ANR threshold. It's a symptom that depends on the real provider's latency, not on the test code.

**What's still not confirmed**

I don't have the ANR trace, and that's the piece that turns the hypothesis into a diagnosis. I need `/data/anr/traces.txt` (or the Play Console / Firebase Crashlytics ANR) for the 12:03:41 event. If the `main` thread's stack shows stuck inside `provider.confirm()` (typically in a `SocketRead` or similar), it's closed. If it shows stuck somewhere else, a contended `lock`, a `Binder` transaction, a disk write, then line 118 is a real problem but not *this* problem, and we'd need to keep digging there.

Two smaller things are also still open: whether there are automatic retries inside `confirm()` (they'd multiply the blocking time), and whether the HTTP client's timeout is configured or defaults to the system one.

**How to reproduce it**

On the test bench, inject latency at the provider: a stub that sleeps 10 s before responding, or a Toxiproxy-style proxy with a delay. It should reproduce on the first try. If it doesn't show the ANR with 10 s of forced latency, the hypothesis falls apart and we need to go back to the trace.

**The fix**

Take `confirm()` off the main thread: `viewModelScope.launch` with the call on `Dispatchers.IO`, an explicit `withTimeout` (agree the value with the payments team; it's usually between 15 and 30 s for authorizations), and an intermediate UI state, a spinner and a disabled charge button, so the cashier can see the operation is in progress.

An important warning about this: **in payments, a timeout can't mean "it failed"**. If the request gets cut off on our end, the authorization may still have gone through at the issuer. This needs idempotency (same operation key on retry) and a status query before treating the operation as failed or letting the cashier repeat it. Otherwise, the risk is duplicate charges, which is quite a bit worse than a frozen screen.

If you send me the ANR trace I'll confirm or rule this out as soon as I see it.
