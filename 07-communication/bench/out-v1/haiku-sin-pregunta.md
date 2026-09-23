No, there is currently a real risk. The problem is that you regenerate the idempotency key on every retry, which makes each attempt count as a distinct transaction. An idempotent request must use the **same key across all retries** of that operation.

**The fix is simple:**
1. Generate the idempotency key **only once**, before the retry loop
2. Reuse that same key on every attempt inside the loop

```kotlin
// Correct:
val idempotencyKey = newIdempotencyKey() // Only once
for (attempt in 1..maxRetries) {
    try {
        processPayment(idempotencyKey) // Reuse
        break
    } catch (e: Exception) {
        // retry
    }
}
```

**Immediate action:**
- Move `newIdempotencyKey()` outside the loop (line 52)
- Add a test that validates multiple retries use the same idempotency key
- Check whether there are other places where the key gets regenerated unnecessarily

Without these changes, there is indeed a risk of duplicate charges.
