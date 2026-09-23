The screen freezes because the charge waits for the provider's response on the same thread that draws the screen.

- What the cashier sees: they tap charge, the app stops responding for a few seconds, and Android flags it as hung (ANR: the app is not responding in time).
- The cause: `PaymentViewModel.kt:118`, at version `7c1d0e9`, calls `provider.confirm()` synchronously on the main thread. That thread is the only one that draws; while it waits for the provider, it draws nothing.
- Think of it like the supermarket checkout: the cashier is the main thread and the call to the provider is a phone call they take without hanging up. Unlike the supermarket, here the cashier can't say "one moment": the whole line stays frozen until someone answers.
- What it is NOT: not the network, the ping was at 40 ms; not low memory, no OOM in the log.
- Money risk: if the cashier taps again while the screen is frozen, the charge can go through twice. It hasn't been confirmed that this happened, and it needs checking before closing the case.

Next step: take `provider.confirm()` off the main thread and leave the screen with a waiting indicator and the button disabled until the response arrives.

I need from you: the transaction IDs of the cashiers who reported the freeze, to cross-check them against the provider and see if any got charged twice.

Not tested: it hasn't been reproduced on the test bench; the 12:03:41 ANR isn't tied to a specific transaction; I don't know how long the provider actually took at that moment.

## Technical detail

- [Measured] Incident log: `12:03:41 ANR in MainActivity`.
- [Measured] Network during the incident: 40 ms ping.
- [Measured] No OOM appears in the log.
- [Tested] `PaymentViewModel.kt:118` @ `7c1d0e9` invokes `provider.confirm()` synchronously on the main thread.
- [Inferred] The ANR comes from that call. Android declares an ANR when the main thread stays blocked for about 5 s; a synchronous network call on that thread blocks it for however long the provider takes to answer.
- [Unknown] The actual duration of `provider.confirm()` at 12:03:41. There's no time trace around the call. A 40 ms ping measures the network round trip, not how long the provider takes to process the charge.
- [Unknown] Whether the charge got recorded at the provider in the frozen transactions.
- [Assumed] Cashiers retry when they see the frozen screen. This comes from the phrase "se queda congelada al cobrar" (the screen freezes when charging), not from a trace.
- [Unknown] Reproduction on the test bench. To force it: delay the provider's response past 5 s with a test double, and measure the call's duration with a trace before and after line 118.

Literal quote from the report: "la pantalla se queda congelada al cobrar".
