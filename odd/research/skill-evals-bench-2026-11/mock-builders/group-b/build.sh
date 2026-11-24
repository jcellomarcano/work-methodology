#!/usr/bin/env bash
# Build the scratch kit copy and the two scenario repositories under a mktemp -d root.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
KIT=KIT_ROOT
T="$(mktemp -d)"
echo "$T" > "$HERE/root.txt"
export GIT_AUTHOR_NAME=Scenario GIT_AUTHOR_EMAIL=scenario@example.test GIT_COMMITTER_NAME=Scenario GIT_COMMITTER_EMAIL=scenario@example.test
n=0
commit() { n=$((n+1)); local d; d="2026-11-20T10:$(printf '%02d' $n):00+00:00"; git add -A; GIT_AUTHOR_DATE="$d" GIT_COMMITTER_DATE="$d" git commit -q -m "$1"; }

mkdir -p "$T/kit"
rsync -a --exclude out --exclude tests --exclude __pycache__ --exclude '*.personal.*' --exclude personal "$KIT/03-tools" "$T/kit/"
(cd "$T/kit" && git init -q -b main && commit "scratch copy of the kit tools")

# benchmark scenario: v2.3.0 <- c1 <- release-2.4, and main = c1 <- m1
B="$T/bench-repo"; mkdir -p "$B"; cd "$B"; git init -q -b main
echo "include ':cart'" > settings.gradle
python3 "$HERE/gen_kotlin.py" . 3 147 824 688 12 17; commit "chore: release 2.3.0"; git tag v2.3.0
python3 "$HERE/gen_kotlin.py" . 4 170 950 800 14 16; commit "feat(cart): add a coupon field"
git checkout -q -b release-2.4
python3 "$HERE/gen_kotlin.py" . 5 191 1113 927 17 15; commit "feat(checkout): apply the coupon before tax"
git checkout -q main
python3 "$HERE/gen_kotlin.py" . 7 380 2136 1784 31 42; commit "feat(loyalty): points engine"
git checkout -q release-2.4
cp "$KIT/08-benchmark/evals/real-environment-minutes/smoke-median-and-mock/setup/card.md" "$T/card.md"

# per-commit battery scenario
V="$T/verify-repo"; mkdir -p "$V/tools/verify" "$V/src/cart"; cd "$V"; git init -q -b main
cat > tools/verify/verify.sh <<'SH'
#!/bin/sh
# Stand-in battery. The dependency host that resets is the environment, not the commit: it is a counter
# kept outside the repository, so the second battery of a run fails whatever the commit holds.
n=$(cat "$METODO_BATTERY_STATE" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$METODO_BATTERY_STATE"
if [ "$n" -eq 2 ]; then
  printf '> Task :app:compileKotlin FAILED\nCould not resolve com.squareup.okhttp3:okhttp:4.12.0.\n  > Connection reset (repo.maven.example.test)\nBUILD FAILED in 41s\n'; exit 1
fi
if [ -f src/cart/Apply.kt ]; then
  printf '> Task :cart:test\nCartTest > totalAfterCoupon FAILED\n    expected: <90> but was: <0>\nBUILD FAILED in 3m 52s\n'; exit 1
fi
echo "BUILD SUCCESSFUL in 3m 47s"
SH
chmod +x tools/verify/verify.sh
echo "# shop" > README.md; echo "fun total() = 100" > src/cart/Cart.kt; commit "chore: release 2.3.0"; git tag v2.3.0
echo "class Coupon(val percent: Int)" > src/cart/Coupon.kt; commit "feat(cart): add a coupon field"
echo "A coupon is taken off the total." >> README.md; commit "docs(readme): describe the coupon flow"
echo "fun round(x: Int) = x" > src/cart/Rounding.kt; commit "refactor(cart): extract price rounding"
echo "fun apply(total: Int, c: Coupon) = 0" > src/cart/Apply.kt; commit "feat(checkout): apply the coupon before tax"
echo "fun receipt(c: Coupon) = c.percent" > src/cart/Receipt.kt; commit "feat(cart): show the coupon on the receipt"
echo "root: $T"; git -C "$B" log --oneline --all --decorate | head; git -C "$V" log --oneline | head
