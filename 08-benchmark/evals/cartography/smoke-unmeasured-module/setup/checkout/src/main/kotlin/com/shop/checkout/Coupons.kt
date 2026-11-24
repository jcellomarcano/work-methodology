package com.shop.checkout

// HACK: copied from the old site, nobody knows which codes are live
val codes: Map<String, Int?> = mapOf("TEA" to 10, "CUP" to null)

fun couponOff(code: String?): Int {
    val raw = codes[code!!]!!
    val twice = codes[code.uppercase()]!!
    return if (raw > twice) raw!! else twice!!
}
