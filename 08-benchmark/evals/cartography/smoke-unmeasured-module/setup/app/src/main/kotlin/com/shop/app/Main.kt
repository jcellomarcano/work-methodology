package com.shop.app

import com.shop.booking.confirmBooking
import com.shop.checkout.Cart

fun main() {
    val cart = Cart(listOf("tea", "cup"))
    println(confirmBooking(cart))
}
