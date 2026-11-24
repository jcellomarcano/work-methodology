#!/usr/bin/env bash
# Scratch scenario: a copy of the kit's tools as its own git repo, and the toy repo of the cases with a history.
set -euo pipefail
KIT=KIT_ROOT; W="$1"
g() { git -c user.name=scratch -c user.email=scratch@example.invalid -c commit.gpgsign=false "$@"; }
mkdir -p "$W/kit"
rsync -a --exclude out --exclude baselines --exclude __pycache__ --exclude '*.personal.*' --exclude tests "$KIT/03-tools/" "$W/kit/03-tools/"
cd "$W/kit" && git init -q -b main && git add -A && g commit -qm "tools A" && echo "toolsA=$(git rev-parse HEAD)"
SETUP=$KIT/08-benchmark/evals/cartography/smoke-unmeasured-module/setup
mkdir "$W/shop" && cd "$W/shop" && git init -q -b main
cp -R "$SETUP/app" "$SETUP/billing-legacy" "$SETUP/booking" "$SETUP/checkout" "$SETUP/gradle" "$SETUP/settings.gradle" .
CK=checkout/src/main/kotlin/com/shop/checkout
sd 'kotlin = "2.1.0"' 'kotlin = "2.0.0"' gradle/libs.versions.toml
sd '= "cart with " \+ cart.items.size \+ " items"' '= "cart"' $CK/Cart.kt
for f in booking/src/main/kotlin/com/shop/booking/BookingFlow.kt $CK/CartPricing.kt $CK/CheckoutSession.kt; do echo "// first cut" >> "$f"; done
git add -A && g commit -qm "first cut" && echo "c1=$(git rev-parse HEAD)"
set +e; bash "$W/kit/03-tools/bin/metrics.sh" "$W/shop" --save > "$W/save.out" 2> "$W/save.err"; echo "save rc=$?"; set -e
git checkout -q -b develop
sd 'kotlin = "2.0.0"' 'kotlin = "2.0.21"' gradle/libs.versions.toml
sd '= "cart"' '= "cart: " + cart.items.size' $CK/Cart.kt
git add -A && g commit -qm "develop: label and kotlin"
git init -q --bare "$W/origin.git" && git remote add origin "$W/origin.git" && git push -q origin develop && git fetch -q origin
git checkout -q main
cp -R "$SETUP/booking" "$SETUP/checkout" "$SETUP/gradle" .
git add -A && g commit -qm "second cut" && echo "c2=$(git rev-parse HEAD)"
git status --short | head; git branch -a | tr '\n' ' '; echo
diff -r "$SETUP/checkout" checkout && diff -r "$SETUP/booking" booking && diff -r "$SETUP/gradle" gradle && diff -r "$SETUP/app" app && diff -r "$SETUP/billing-legacy" billing-legacy && diff "$SETUP/settings.gradle" settings.gradle && echo "HEAD tree = the case's toy repo"
