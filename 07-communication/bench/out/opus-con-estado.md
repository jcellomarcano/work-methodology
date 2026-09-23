The Room migration is at 14 of 18 entities, with green tests, and it's stalled until tomorrow because of the test bench.

- Done: 14 entities migrated out of 18.
- Tested: tests pass on commits a1b2c3d..e4f5a6b.
- Missing: `Receipt` and `Shift`, the last two entities.
- Blocking: another session is occupying the test bench until tomorrow.

Next step: migrate `Receipt` and `Shift` while the bench frees up, then run the full verification once it's available.

Not tested: cold start without network. Until it's tested, I don't know whether the app opens correctly the first time without a connection.

## Technical detail

- 14/18 entities migrated to Room; `Receipt` and `Shift` remain. [Measured]
- Green suite on the commit range `a1b2c3d..e4f5a6b`. [Tested]
- Test bench held by another session until tomorrow; no exact release date or time. [Measured]
- Cold start without network: not run. [Unknown]
- The 4 remaining entities behave like the 14 already migrated. [Assumed]
