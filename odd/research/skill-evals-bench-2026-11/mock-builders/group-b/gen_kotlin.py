"""Write a Kotlin tree whose shape totals are exactly the ones given (files, fun, loc, non-blank, var, !!).

The lines are dealt out over the files in turn, so no file is long enough to raise a style rule.
"""
import pathlib
import sys

root, files, funs, loc, non_blank, var, bang = sys.argv[1], *map(int, sys.argv[2:8])
base = pathlib.Path(root) / "cart" / "src" / "main" / "kotlin" / "cart"
base.mkdir(parents=True, exist_ok=True)
for old in base.glob("*.kt"):
    old.unlink()
lines = [f"fun f{i}(x: Int?) = x!!" if i < bang else f"fun f{i}() = {i}" for i in range(funs)]
lines += [f"var v{i} = {i}" for i in range(var)]
lines += [f"// note {i}" for i in range(non_blank - funs - var)]
lines += [""] * (loc - non_blank)
for n in range(files):
    (base / f"Cart{n}.kt").write_text("".join(line + "\n" for line in lines[n::files]), encoding="utf-8")
