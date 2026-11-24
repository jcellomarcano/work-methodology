"""Rename the ids of the scratch scenario to the ids the cases already use; nothing else of an answer changes.

The real answers name the scratch tools folder, the scratch repo, their commits and the job's run id.
The cases were built on another scratch scenario of the same toy repo, whose ids their staged files and
answer keys carry, so each id is replaced by its counterpart and the tools' out folder by `out`,
where the cases stage it.
"""
import pathlib, sys
w = pathlib.Path(sys.argv[1]).resolve()
RENAMES = [
    (str(w / "kit" / "03-tools" / "out") + "/", "out/"),                                   # the tools' out folder, as staged
    (str(w / "shop"), "/work/shop"),                                                        # the scratch repo
    ("42400ef347e69e7ef40096ae9fbff40366a66d0b", "20c83b02fecccbd5d5ec48767ef6422abceaa21b"),  # the measured commit
    ("f1b7f080d02393c27eef82b4c5acf9d553f5bd5a", "a41d315937a3bb6ebecb4ab06015b6fbefc71831"),  # the baseline's commit
    ("3056836a93aa12da0a4b9b6014892b76dc052354", "0392317d88a575d29ef1a878ce6e27a53dd3921d"),  # the tools before
    ("c4cba01afc4d4e6ad8aa41228f5747d37054ba15", "9ecc641b61d7b06bf76846e41990b6685258dd64"),  # the tools after
    ("20261124194207-175a14", "20261124141729-40698d"),                                    # the job's run id
]
(w / "mocks").mkdir(exist_ok=True)
for name in ("cartography", "clean_pass", "metrics_delta", "job_status"):
    text = (w / "real" / f"{name}.txt").read_text(encoding="utf-8")
    for old, new in RENAMES:
        text = text.replace(old, new)
    assert str(w) not in text and "/var/" not in text and "/Users/" not in text, name
    (w / "mocks" / f"{name}.md").write_text(text + "\n", encoding="utf-8")
    print(f"{name}: {len(text.splitlines())} lines")
