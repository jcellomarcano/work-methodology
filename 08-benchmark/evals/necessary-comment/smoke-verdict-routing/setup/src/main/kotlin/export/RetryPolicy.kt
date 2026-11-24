package export

/**
 * This interface is the retry policy of an export.
 */
interface RetryPolicy {
    fun waitMillis(attempt: Int): Long
}

class PartnerRetryPolicy(private val clock: Clock) : RetryPolicy {
    private var attempts = 0

    override fun waitMillis(attempt: Int): Long {
        // increment the attempt counter
        attempts += 1
        // The partner bans a key for an hour after four calls inside one second, and we saw that
        // happen twice in March, so the wait never drops under 300 ms.
        val floor = 300L
        // 1 shl attempt doubles the wait each time, capped at 30 seconds
        val wait = minOf(floor * (1L shl attempt), 30_000L)
        // NEEDS-COMMENT: why the jitter comes from the clock and not from Random
        return wait + clock.millis() % 50
    }

    // Removed the old linear backoff here.
    fun reset() {
        attempts = 0
    }
}
