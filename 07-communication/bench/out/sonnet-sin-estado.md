Here's the status of the Room migration:

- **Progress:** 14 of 18 entities migrated.
- **Tests:** green on commits `a1b2c3d..e4f5a6b`.
- **Pending:** `Receipt` and `Shift` are missing.
- **Block:** the test bench is occupied by another session until tomorrow, so I won't be able to make progress on validation until then.
- **Not tested yet:** cold start without network.

As soon as the test bench frees up I'll get back to `Receipt` and `Shift`, and use the chance to test cold start without network before calling the migration closed.
