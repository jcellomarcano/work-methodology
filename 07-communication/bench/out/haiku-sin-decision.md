Given your priority hierarchy (Money > Payment state > Recoverability > UX), the answer is clear: **Room + an internal write-ahead log**.

Here's the reasoning:

**Why not SharedPreferences:**
- Not designed for critical or transactional data
- Doesn't guarantee durability against concurrent crashes

**Why Room alone isn't enough:**
- Room is excellent for persistence, but between the call to the provider and the confirmation, if the process dies, you've lost the intermediate state
- You need to know: "we're waiting for the provider's response" vs "it was confirmed" vs "it failed"

**Solution: pragmatic hybrid**

1. **Room for the final state** (confirmed payments, processed failures)
2. **A *very simple* write-ahead file** in the app's own private directory (getFilesDir) for:
   - Transaction start timestamp
   - Provider transaction ID (if you have it)
   - State: "sending" → "confirmed" / "failed"

3. **On startup:**
   - Read the write-ahead
   - If incomplete, retry confirmation/rollback
   - Once resolved, write to Room and delete the write-ahead

Advantages:
- Room stays your source of truth for historical data
- The write-ahead is minimal and fast (recoverability guaranteed)
- Zero extra dependencies (no need for WAL libraries)
- The team keeps using Room for what Room does well

**Note:** The write-ahead doesn't need to be sophisticated. Use plain JSON in `app/files/payment_wal.txt`. If it dies mid-write, even better (it's safe to assume the operation failed).
