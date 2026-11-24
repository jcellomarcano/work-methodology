Yes: the export retries a timed-out upload three times before it stops.

Each retry waits longer than the one before — one second, then two, then four — so a short outage passes without a second copy of the file.

## Technical detail
- `src/export/retry.py:9` sets the limit of three attempts [Measured]
- `src/export/retry.py:88` doubles the wait after each failed attempt [Measured]
- A retry cannot write the file twice, because the upload is skipped when the name already exists at the destination [Inferred]
- Not tested: an outage that lasts longer than the three attempts
