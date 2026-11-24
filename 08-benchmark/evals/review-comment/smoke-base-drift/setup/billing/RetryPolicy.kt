package billing

import kotlin.math.pow

class RetryPolicy(private val maxAttempts: Int = 3, private val baseDelayMs: Long = 200) {
    fun shouldRetry(attempt: Int): Boolean = attempt < maxAttempts

    // Waits longer after each failed delivery so the provider is not hammered.
    fun delayMs(attempt: Int): Long {
        val factor = 2.0.pow(attempt)
        return (baseDelayMs * factor).toLong()
    }
}
