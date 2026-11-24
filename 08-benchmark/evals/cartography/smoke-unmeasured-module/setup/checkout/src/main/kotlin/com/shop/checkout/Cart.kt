package com.shop.checkout

data class Cart(val items: List<String>)

fun cartLabel(cart: Cart): String = "cart with " + cart.items.size + " items"
