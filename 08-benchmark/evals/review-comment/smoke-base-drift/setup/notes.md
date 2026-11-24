# My pass over the retry PR (feature/retry-webhook into develop)

Read it in the web diff; three files show up there.

1. billing/RetryPolicy.kt:11 - the delay doubles on every attempt and nothing caps it. If someone raises maxAttempts to 10, a webhook thread sleeps for minutes. Cap it.
2. billing/LegacyExport.kt:7 - the diff shows the try/catch around writeText gone, so an IOException now takes the whole export down. Put the guard back.
