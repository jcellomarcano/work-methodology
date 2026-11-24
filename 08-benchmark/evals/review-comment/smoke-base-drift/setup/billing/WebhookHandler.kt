package billing

class WebhookHandler(private val policy: RetryPolicy, private val seen: MutableSet<String>) {
    fun handle(id: String, deliver: () -> Boolean) {
        if (!seen.add(id)) return
        var attempt = 0
        while (!deliver() && policy.shouldRetry(attempt)) {
            Thread.sleep(policy.delayMs(attempt))
            attempt++
        }
    }
}
