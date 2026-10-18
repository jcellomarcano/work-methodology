#!/usr/bin/env python3
"""C6 text audit: measures every kit text an agent can get in context.
Read-only on the kit. Usage: python3 audit.py <kit_root> > audit.json
Tokens = chars/4 (ceil), an [Inferred] estimate, not a tokenizer."""
import ast, glob, hashlib, json, os, re, subprocess, sys
from pathlib import Path

KIT = Path(sys.argv[1]).resolve()
OUT = Path(__file__).resolve().parent
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True


def tok(s):
    return (len(s) + 3) // 4


def meas(text):
    return {"bytes": len(text.encode()), "chars": len(text), "lines": text.count("\n") + (0 if text.endswith("\n") or not text else 1),
            "words": len(text.split()), "tokens": tok(text)}


def read(p):
    return (KIT / p).read_text(encoding="utf-8")


def split_fm(t):
    if not t.startswith("---\n"):
        return "", t
    e = t.find("\n---\n", 3)
    return t[4:e + 1], t[e + 5:]


def fm_field(fm, key):
    m = re.search(rf"^{key}:\s*(.*)$", fm, re.M)
    return m.group(1).strip() if m else ""


head = subprocess.run(["git", "-C", str(KIT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
dirty = subprocess.run(["git", "-C", str(KIT), "status", "--porcelain"], capture_output=True, text=True).stdout.splitlines()
items = []  # (mode, name, text)


def add(mode, name, text):
    items.append({"mode": mode, "name": name, "text": text})


# ---- always loaded (main session, Claude Code) ----
add("always", "AGENTS.md", read("AGENTS.md"))
add("always", "CLAUDE.md (wrapper, imports AGENTS.md)", read("CLAUDE.md"))
ss = (OUT / "session_start.out").read_text()
add("always", "hook:session_start_status output (measured on fixture)", ss)
sys.path.insert(0, str(KIT / "03-tools"))
from mcp import catalog  # noqa: E402
tools = [{"name": t.name, "description": t.description, "inputSchema": t.input_schema} for t in catalog.TOOLS]
tools_json = json.dumps({"tools": tools}, ensure_ascii=False, separators=(",", ":"))
add("always", f"MCP tools/list ({len(tools)} tools, compact JSON)", tools_json)
per_tool = {t["name"]: tok(json.dumps(t, ensure_ascii=False, separators=(",", ":"))) for t in tools}
desc_only = sum(tok(t["description"]) for t in tools)
skill_idx, skill_fm_full = [], []
for p in sorted(glob.glob(str(KIT / "02-skills/*/SKILL.md"))):
    fm, body = split_fm(Path(p).read_text())
    skill_idx.append(f"{fm_field(fm, 'name')}: {fm_field(fm, 'description')}")
    skill_fm_full.append(fm)
    add("on-demand", "skill:" + Path(p).parent.name, body)
add("always", f"skill index name+description ({len(skill_idx)} skills)", "\n".join(skill_idx))
agent_idx = []
agents = sorted(glob.glob(str(KIT / "01-roles/agents/generic-*.md")))
bodies = {}
for p in agents:
    fm, body = split_fm(Path(p).read_text())
    n = Path(p).stem
    agent_idx.append(f"{n}: {fm_field(fm, 'description')}")
    bodies[n] = body
add("always", f"subagent index name+description ({len(agents)} agents)", "\n".join(agent_idx))

# ---- per subagent ----
pi_renders = {}
for p in agents:
    n = Path(p).stem
    add("per-subagent", "claude-body:" + n, bodies[n])
    r = subprocess.run([sys.executable, str(KIT / "03-tools/lib/render_agents.py"), "--target", "pi", p], capture_output=True, text=True)
    pi_renders[n] = r.stdout if r.returncode == 0 else ""
    add("per-subagent-pi", "pi-render:" + n, pi_renders[n])
    add("per-subagent-ref", "contract:" + n, read(f"01-roles/agents/{n}.contract.json"))
for t in ["04-templates/brief.md", "04-templates/agent-brief.md", "04-templates/round-context-pack.md", "CONTEXT-PACK.md"]:
    add("per-subagent-ref", t, read(t))

# ---- on demand ----
for pat in ["00-principles/*.md", "06-languages/*.md", "docs/*.md", "README.md", "07-communication/rules.md",
            "07-communication/templates.md", "07-communication/identity.en.md", "07-communication/identidad.es.md",
            "07-communication/adapters/CLAUDE.md", "05-adopt/checklist.md", "03-tools/README.md"]:
    for p in sorted(glob.glob(str(KIT / pat))):
        add("on-demand", str(Path(p).relative_to(KIT)), Path(p).read_text())
for t in ["04-templates/change-card.md", "04-templates/round-minutes.md"]:
    add("on-demand", t, read(t))

# ---- hook messages to the model (per firing) ----
SAMPLE = {"rel": "app/src/main/kotlin/com/example/booking/BookingRepository.kt", "tree": "4b825dc642cb",
          "receipt_state": "none", "allow": "src/**, tests/**", "cap": "40", "schema_name": "verification", "reason": None}
hookmsgs = []
for hp in sorted(glob.glob(str(KIT / "03-tools/hooks/*.py"))):
    src = Path(hp).read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in ("emit_pretool", "emit_stop_block"):
            a = node.args[-1]
            seg = ast.get_source_segment(src, a)
            parts = []
            def flat(x):
                if isinstance(x, ast.Constant):
                    parts.append(str(x.value))
                elif isinstance(x, ast.JoinedStr):
                    for v in x.values:
                        flat(v.value if isinstance(v, ast.FormattedValue) else v)
                elif isinstance(x, ast.BinOp):
                    flat(x.left); flat(x.right)
                elif isinstance(x, ast.Name) and x.id == "reason":
                    parts.append("no approved receipt for tree 4b825dc642cb (receipt: none)" if "gates" in hp else
                                 SAMPLE["rel"] + " is outside the role's may_write / receipt scope (src/**, tests/**)")
                else:
                    parts.append("X" * 40 if "errors" in ast.dump(x) else "<v>")
            flat(a)
            msg = "".join(parts)
            for k, v in SAMPLE.items():
                if v:
                    msg = msg.replace("<v>", v, 1) if False else msg
            first = {"budget.py": "40", "validate_subagent_output.py": "verification"}.get(Path(hp).name, SAMPLE["rel"])
            msg = msg.replace("<v>", first, 1).replace("<v>", "x")
            wrapper = 110 if node.func.attr == "emit_pretool" else 30  # JSON envelope chars
            hookmsgs.append({"hook": Path(hp).name, "line": node.lineno, "chars": len(msg), "tokens_with_envelope": tok("x" * (len(msg) + wrapper)), "msg": msg[:160]})
for h in hookmsgs:
    add("hook-firing", f"hook:{h['hook']}:{h['line']}", "x" * (h["chars"] + (110 if "stop" not in h["hook"] else 30)))

# ---- measurements ----
rows = []
for it in items:
    m = meas(it["text"])
    rows.append({"mode": it["mode"], "name": it["name"], **m})
totals = {}
for r in rows:
    t = totals.setdefault(r["mode"], {"items": 0, "bytes": 0, "lines": 0, "words": 0, "tokens": 0})
    t["items"] += 1
    for k in ("bytes", "lines", "words", "tokens"):
        t[k] += r[k]
top = sorted(rows, key=lambda r: -r["tokens"])[:15]
top_always = sorted([r for r in rows if r["mode"] == "always"], key=lambda r: -r["tokens"])
# session cold start in Claude Code: CLAUDE.md + AGENTS.md (import) + hook + MCP + indexes
always_total = totals["always"]["tokens"]
# per-subagent cold start: body + its MCP tool schemas (Claude filters tools) + CONTEXT-PACK + round-context-pack + brief
cp = tok(read("CONTEXT-PACK.md")); rcp = tok(read("04-templates/round-context-pack.md")); br = tok(read("04-templates/brief.md"))
ap = tok(read("00-principles/agent-protocol.md"))
per_agent = {}
for p in agents:
    n = Path(p).stem
    fm, _ = split_fm(Path(p).read_text())
    mcp_tools = [x.strip().replace("mcp__metodo__", "") for x in fm_field(fm, "tools").split(",") if "mcp__metodo__" in x]
    mcp_cost = sum(per_tool.get(x, 0) for x in mcp_tools)
    per_agent[n] = {"body": tok(bodies[n]), "pi_render": tok(pi_renders[n]), "contract": tok(read(f"01-roles/agents/{n}.contract.json")),
                    "mcp_schemas": mcp_cost, "mcp_tools": len(mcp_tools),
                    "cold_start_claude": tok(bodies[n]) + mcp_cost + cp + rcp + br,
                    "cold_start_claude_plus_protocol": tok(bodies[n]) + mcp_cost + cp + rcp + br + ap}

# ---- duplication: normalized sentences, 5-word shingles, Jaccard ----
MF = [it for it in items if it["mode"] in ("always", "per-subagent", "per-subagent-ref", "on-demand") and not it["name"].startswith(("MCP", "hook:", "contract:"))]


def norm(s):
    s = re.sub(r"[`*_>#|]", " ", s.lower())
    s = re.sub(r"[^a-z0-9áéíóúñ/.\- ]", " ", s)
    return " ".join(s.split())


sents = []
for it in MF:
    for chunk in re.split(r"(?<=[.!?])\s+|\n\s*[-*]\s+|\n\n|\n\d+\.\s+", it["text"]):
        n = norm(chunk)
        w = n.split()
        if len(w) >= 8:
            sh = {" ".join(w[i:i + 5]) for i in range(len(w) - 4)}
            sents.append((it["name"], n, sh))
inv = {}
for i, (_, _, sh) in enumerate(sents):
    for g in sh:
        inv.setdefault(g, set()).add(i)
pairs = {}
for g, ids in inv.items():
    if len(ids) > 30:
        continue
    ids = sorted(ids)
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            pairs[(ids[a], ids[b])] = 1
parent = list(range(len(sents)))
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]; x = parent[x]
    return x
cross = []
for (a, b) in pairs:
    if sents[a][0] == sents[b][0]:
        continue
    A, B = sents[a][2], sents[b][2]
    j = len(A & B) / len(A | B)
    if j >= 0.5:
        parent[find(a)] = find(b)
    if 0.3 <= j and not (sents[a][0].startswith("claude-body") and sents[b][0].startswith("claude-body")):
        cross.append({"j": round(j, 2), "a": sents[a][0], "b": sents[b][0], "text": sents[a][1][:120]})
comp = {}
for i in range(len(sents)):
    r = find(i)
    if r != i or any(find(k) == i for k in range(len(sents)) if k != i):
        comp.setdefault(r, []).append(i)
dup = []
for r, ids in comp.items():
    if len(ids) < 2:
        continue
    files = sorted({sents[i][0] for i in ids})
    if len(files) < 2:
        continue
    toks = [tok(sents[i][1]) for i in ids]
    rep = min(ids, key=lambda i: len(sents[i][1]))
    dup.append({"text": sents[rep][1][:150], "files": files, "n": len(files), "sentences": len(ids), "jaccard_min": 0.5,
                "redundant_tokens": sum(toks) - max(toks)})
dup.sort(key=lambda d: (-d["redundant_tokens"], d["text"]))
cross.sort(key=lambda d: (-d["j"], d["a"], d["b"]))
# exact repeated lines across agent bodies
line_count = {}
for n, b in bodies.items():
    for ln in {norm(x) for x in b.splitlines() if len(x.split()) >= 5}:
        line_count.setdefault(ln, set()).add(n)
rep_lines = sorted(({"line": k[:140], "agents": len(v), "tokens_each": tok(k), "redundant_tokens": (len(v) - 1) * tok(k)}
                    for k, v in line_count.items() if len(v) >= 3), key=lambda d: (-d["redundant_tokens"], d["line"]))

# ---- Spanish leftovers in model-facing text ----
ES = re.compile(r"\b(que|los|las|del|para|una|pero|cuando|también|está|como|desde|Verificador|Desconocido|Medido|Inferido|Supuesto|Probado|Cartógrafo|Proponente|Retador|Juez|Mecánico|hecho|sí)\b|[áéíóúñ¿¡]")
spanish = []
for it in items:
    if it["mode"] in ("hook-firing",) or it["name"].startswith(("07-communication/identidad", "MCP")):
        continue
    for i, ln in enumerate(it["text"].splitlines(), 1):
        hits = ES.findall(ln)
        hits = [h for h in hits if h]
        if len(hits) >= 1 and not re.search(r"\"[^\"]*(que|para)[^\"]*\"", ln):
            spanish.append({"file": it["name"], "line": i, "hits": len(hits), "text": ln.strip()[:120]})
mcp_es = [t["name"] for t in tools if ES.search(t["description"])]

# ---- stale references: backticked paths that resolve nowhere ----
stale, runtime_refs = [], []
TRACKED = {Path(x).name for x in subprocess.run(["git", "-C", str(KIT), "ls-files"], capture_output=True, text=True).stdout.splitlines()}
RUNTIME = re.compile(r"(^|/)(round/|out/|NNN|000-|\.mcp\.json|\.claude/|\.pi/|deps\.|metrics\.json|delta\.|results\.json|summary\.json|\.lint\.json|CONVENTIONS\.md|invariants\.md|\.contract\.json$|SKILL\.md$|scope_path=|\.personal\.)")
ref_items = [it for it in items if it["mode"] in ("always", "per-subagent", "per-subagent-ref", "on-demand") and not it["name"].startswith(("MCP", "hook:"))]
for it in ref_items:
    nm = it["name"].split(" ")[0]
    base = KIT / ("01-roles/agents" if nm.startswith("claude-body:") else (f"02-skills/{nm[6:]}" if nm.startswith("skill:") else Path(nm).parent))
    for m in re.finditer(r"`([^`\s]+\.(?:md|json|py|sh|ts))`", it["text"]):
        ref = m.group(1)
        if any(c in ref for c in "<>*${}") or ref.startswith(("http", "~")):
            continue
        cands = [base / ref, KIT / ref, KIT / "03-tools" / ref, KIT / "03-tools/lib" / ref, KIT / "03-tools/schemas" / ref,
                 KIT / "00-principles" / ref, KIT / "04-templates" / ref, KIT / "07-communication" / ref, KIT / "01-roles/agents" / ref,
                 KIT / "03-tools/hooks" / ref, KIT / "03-tools/config" / ref, KIT / "02-skills" / ref, KIT / "docs" / ref]
        if any(c.exists() for c in cands):
            continue
        if RUNTIME.search(ref):
            runtime_refs.append(ref); continue
        stale.append({"file": it["name"], "ref": ref, "basename_tracked": Path(ref).name in TRACKED})
# installed-context break: ../../ refs in agent bodies resolve to <repo>/ after install into <repo>/.claude/agents/
installed_break = sorted({(n, m.group(1)) for n, b in bodies.items() for m in re.finditer(r"`(\.\./\.\./[^`]+)`", b)})
installed_break_skills = []
for p in sorted(glob.glob(str(KIT / "02-skills/*/SKILL.md"))):
    for m in re.finditer(r"`(\.\./[^`]+)`", Path(p).read_text()):
        installed_break_skills.append((Path(p).parent.name, m.group(1)))

# ---- rules in agent bodies that a hook already enforces ----
HOOKED = {"never talk to the user / spawn (guard_gates subagent deny, contract)": r"never talk to the user|never spawn",
          "never touch build files / .claude (guard_paths deny)": r"settings\.gradle|\.claude/\*\*",
          "budget: harness denies next call (budget.py)": r"harness denies the next call",
          "never push/PR/merge (guard_gates deny for subagents)": r"never (push|open a pr|merge)",
          "final JSON valid vs schema (validate_subagent_output)": r"moved out of this body"}
hooked = {}
for k, rx in HOOKED.items():
    hit = [n for n, b in bodies.items() if re.search(rx, b, re.I)]
    toks = sum(tok(" ".join(l for l in b.splitlines() if re.search(rx, l, re.I))) for n, b in bodies.items())
    hooked[k] = {"agents": len(hit), "tokens_total": toks}
gradle = [n for n, b in bodies.items() if re.search(r"gradle", b, re.I)]

# ---- docs-caps coverage ----
caps = json.loads(read("03-tools/config/docs-caps.json"))["caps"]
uncapped_model_facing = sorted(r["name"] for r in rows if r["mode"] in ("on-demand", "per-subagent-ref", "always")
                               and not r["name"].startswith(("skill:", "MCP", "hook", "skill index", "subagent index", "CLAUDE.md")) and r["name"] not in caps)

res = {"head": head, "dirty_paths": len(dirty), "token_method": "ceil(chars/4)", "totals": totals,
       "top15": [{k: r[k] for k in ("mode", "name", "tokens", "bytes", "lines", "words")} for r in top],
       "always": [{k: r[k] for k in ("name", "tokens", "bytes", "lines", "words")} for r in top_always],
       "rows": [{k: r[k] for k in ("mode", "name", "tokens", "bytes", "lines", "words")} for r in rows],
       "mcp": {"tools": len(tools), "tokens": tok(tools_json), "desc_tokens": desc_only, "top_tools": sorted(per_tool.items(), key=lambda x: -x[1])[:8]},
       "skill_frontmatter_full_tokens": sum(tok(x) for x in skill_fm_full),
       "per_agent": per_agent, "dup_top": dup[:20], "dup_clusters": len(dup), "dup_redundant_tokens": sum(d["redundant_tokens"] for d in dup),
       "cross_top": cross[:25], "cross_n": len(cross), "rep_lines": rep_lines[:15], "spanish": spanish, "spanish_mcp": mcp_es, "stale": stale, "runtime_refs": len(runtime_refs), "installed_break": installed_break,
       "installed_break_skills": installed_break_skills, "hooked": hooked, "gradle_agents": gradle,
       "hookmsgs": hookmsgs, "uncapped": uncapped_model_facing}
print(json.dumps(res, indent=1, ensure_ascii=False, sort_keys=True))
