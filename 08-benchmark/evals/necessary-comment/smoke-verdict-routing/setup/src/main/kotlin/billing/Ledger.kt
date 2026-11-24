package billing

class Ledger(private val entries: MutableList<Entry>) {
    fun settle(now: Long): Long {
        // d is the number of days past due and f is the late fee in cents per day
        val d = (now - entries.first().dueAt) / 86_400_000L
        val f = 25L
        return entries.sumOf { it.cents } + d * f
    }
}
