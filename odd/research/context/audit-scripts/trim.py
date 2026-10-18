#!/usr/bin/env python3
"""Derived trim figures from the kit, same token method (ceil(chars/4)). Read-only."""
import glob, json, re, subprocess, sys
from pathlib import Path

KIT = Path(sys.argv[1]).resolve()
sys.dont_write_bytecode = True
tok = lambda s: (len(s) + 3) // 4


def split_fm(t):
    e = t.find("\n---\n", 3)
    return t[4:e + 1], t[e + 5:]


PAT = {"budget_para": r"^Budget: `max_tool_calls`|^Budget:",
       "gradle_line": r"settings\.gradle",
       "never_talk_line": r"Never talk to the user directly",
       "output_pointer": r"moved out of this body",
       "contract_protocol_ptr": r"^Contract: `",
       "gradle_constraint": r"Gradle build"}
per = {}
for p in sorted(glob.glob(str(KIT / "01-roles/agents/generic-*.md"))):
    n = Path(p).stem
    _, body = split_fm(Path(p).read_text())
    lines = body.splitlines()
    d = {}
    for k, rx in PAT.items():
        hit = [l for l in lines if re.search(rx, l)]
        d[k] = tok("\n".join(hit)) if hit else 0
    pi = subprocess.run([sys.executable, str(KIT / "03-tools/lib/render_agents.py"), "--target", "pi", p], capture_output=True, text=True).stdout
    sec = pi[pi.find("## Contract (partly"):] if "## Contract (partly" in pi else ""
    d["pi_overhead"] = tok(pi) - tok(body)
    d["pi_contract_section"] = tok(sec)
    d["body"] = tok(body)
    d["cuttable"] = d["budget_para"] + d["gradle_line"] + d["never_talk_line"] + d["output_pointer"] + d["gradle_constraint"]
    per[n] = d
tot = {k: sum(v[k] for v in per.values()) for k in next(iter(per.values()))}

# skills: description tokens and savings at caps
sk = []
for p in sorted(glob.glob(str(KIT / "02-skills/*/SKILL.md"))):
    fm, body = split_fm(Path(p).read_text())
    m = re.search(r"^description:\s*(.*)$", fm, re.M)
    trig = re.findall(r"^\s+-\s", fm.split("triggers:")[1], re.M) if "triggers:" in fm else []
    sk.append({"skill": Path(p).parent.name, "desc": tok(m.group(1)), "body": tok(body), "fm": tok(fm), "triggers": len(trig)})
sk_save = {c: sum(max(0, s["desc"] - c) for s in sk) for c in (40, 50, 60)}

# MCP: split description vs schema; property-level descriptions
sys.path.insert(0, str(KIT / "03-tools"))
from mcp import catalog  # noqa: E402
mcp = []
for t in catalog.TOOLS:
    sch = json.dumps(t.input_schema, separators=(",", ":"))
    pdesc = sum(tok(v.get("description", "")) for v in (t.input_schema.get("properties") or {}).values() if isinstance(v, dict))
    mcp.append({"name": t.name, "desc": tok(t.description), "schema": tok(sch), "prop_desc": pdesc, "roles": list(getattr(t, "roles", ()) or ())})
mcp_tot = {"desc": sum(x["desc"] for x in mcp), "schema": sum(x["schema"] for x in mcp), "prop_desc": sum(x["prop_desc"] for x in mcp)}
orchestrator_only = [x["name"] for x in mcp if not x["roles"]]
mcp_desc_save_30 = sum(max(0, x["desc"] - 30) for x in mcp)

# section sizes of always-loaded / cold-start docs
def sections(path):
    t = (KIT / path).read_text()
    parts = re.split(r"(?m)^(## .*)$", t)
    out = {"_head": tok(parts[0])}
    for i in range(1, len(parts), 2):
        out[parts[i][:50]] = tok(parts[i] + parts[i + 1])
    return out

res = {"per_agent": per, "agent_totals": tot, "skills": sk, "skill_desc_total": sum(s["desc"] for s in sk),
       "skill_desc_savings_at_cap": sk_save, "mcp_totals": mcp_tot, "mcp_desc_save_cap30": mcp_desc_save_30,
       "mcp_no_roles": orchestrator_only, "mcp_top": sorted(mcp, key=lambda x: -(x["desc"] + x["schema"]))[:6],
       "sections": {p: sections(p) for p in ["AGENTS.md", "CONTEXT-PACK.md", "00-principles/agent-protocol.md"]},
       "identity_if_installed": {"adapters/CLAUDE.md": tok((KIT / "07-communication/adapters/CLAUDE.md").read_text()),
                                 "identidad.es.md": tok((KIT / "07-communication/identidad.es.md").read_text()),
                                 "identity.en.md": tok((KIT / "07-communication/identity.en.md").read_text()),
                                 "adapters/AGENTS.md": tok((KIT / "07-communication/adapters/AGENTS.md").read_text())}}
print(json.dumps(res, indent=1, sort_keys=True))
