The migration is at 78 percent. It works in most cases, but two entities aren't migrated and there's a test that hasn't run.

**What works:** 14 of 18 entities are migrated; the tests pass on those commits.

**What's missing:** `Receipt` and `Shift` aren't migrated.

**What's blocking:** you can't test the database bank until tomorrow; nobody has verified whether startup works without network.

**Next step:** today you migrate `Receipt` and `Shift`. Tomorrow you run the full database bank. Then you test cold start without network before marking it ready.

Not tested: cold start without connectivity; `Receipt` and `Shift` under load on the test bench.
