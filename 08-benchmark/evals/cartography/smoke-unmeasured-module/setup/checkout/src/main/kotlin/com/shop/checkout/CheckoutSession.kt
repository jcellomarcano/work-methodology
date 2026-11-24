package com.shop.checkout

class CheckoutSession(val cart: Cart) {
    var startedAt: Long = 0L
    var step: Int = 0
    var coupon: String? = null
    lateinit var payer: String
    fun label(): String = cartLabel(cart)
    fun next() {
        step += 1
    }
}
