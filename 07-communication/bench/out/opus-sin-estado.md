**Room migration status**

We're at 14 of 18 entities migrated. Tests are green on the commit range `a1b2c3d..e4f5a6b`.

**What's missing**
- `Receipt` and `Shift`: the two pending entities.
- Validation on the test bench: another session has it until tomorrow, so we can't get in before then.
- Cold start without network: not tested yet.

**Reading**

Most of the work is done and backed by tests, but I still wouldn't call it finished. The two open risks are cold start without network, which is exactly where a Room migration tends to fail (pending migration when opening the database, no remote fallback), and the fact that we still haven't validated anything on the real bench.

**Next step**

While we wait for the bench, I'll move ahead with `Receipt` and `Shift`. Tomorrow, as soon as it frees up, the priority is cold start without network; until that's tested, I wouldn't call the migration closed.

Does either of the two remaining entities have priority, or should I do them in whatever order comes up?
