# Bench session, POS terminal T-07, 2026-11-20

Change under test: PAY-231, the coupon is applied before tax (card.md).
Metric: tap to approved, in milliseconds, six taps per arm with the same test card.

## Arm A, v2.3.0 (what is in production)

- Release build, installed from the store track.
- Taps went to the acquirer's certification host, the real one.
- Terminal held by Marta Ruiz.
- Tap 3 hit a network retry.

## Arm B, release-2.4 (the candidate)

- Candidate build from the release-2.4 branch.
- The certification host went down at 16:10, so this arm ran with MOCK_ACQUIRER=1: the app answers "approved" by itself after a fixed delay, with no network.
- Terminal held by Dario Vega (Marta had left).
- Tap 2 froze on the coupon screen before the tap registered.
