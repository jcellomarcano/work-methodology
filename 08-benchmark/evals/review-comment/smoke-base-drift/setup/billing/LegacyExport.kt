package billing

import java.io.File

class LegacyExport(private val target: File) {
    fun write(rows: List<String>) {
        target.writeText(rows.joinToString("\n"))
    }
}
