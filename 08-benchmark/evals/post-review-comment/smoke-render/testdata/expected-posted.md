`billing/InvoiceService.kt:142` @ 9f3c2ab

- **What happens:** the retry loop charges the card again when the first charge timed out but went through.
- **Why it happens:** the retry does not check the charge id it already holds.
- **Impact:** a customer can be billed twice for one invoice.
- **How to fix:** look the charge up by its idempotency key before retrying.

```kotlin
val existing = charges.findByKey(invoice.idempotencyKey)
if (existing == null) charge(invoice)
```
