The Room migration is at 14 of 18 entities with green tests, and it's blocked until tomorrow because of the test bench.

- Done: 14 entities migrated and their tests pass.
- Missing: `Receipt` and `Shift`, the 2 remaining entities.
- Blocking: another session has the test bench until tomorrow, so there's no new measurement today.
- Unverified: cold start without network.

Next step: take the test bench tomorrow, close out `Receipt` and `Shift`, and measure cold start without network.

## Technical detail

- [Measured] 14 of 18 entities migrated to Room; `Receipt` and `Shift` are missing.
- [Tested] Green tests on commits a1b2c3d..e4f5a6b.
- [Measured] Test bench occupied by another session until tomorrow.
- [Unknown] `Receipt` and `Shift` behavior under Room: not yet migrated, no data.
- Not tested: cold start without network.
