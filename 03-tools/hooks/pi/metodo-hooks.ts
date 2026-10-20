/**
 * metodo-hooks: the kit's guards on pi.
 *
 * pi has no hook system, but it has extensions, so this file is the adapter
 * and not a second implementation. It reuses hooks/*.py unchanged: it builds
 * the same stdin JSON Claude Code sends, runs the script, and reads the same
 * decision protocol back (JSON on stdout with hookSpecificOutput).
 *
 * TOOLS_ROOT and REPO_ROOT are rendered by bin/install-pi.sh; METODO_TOOLS
 * and METODO_REPO in the environment win over both.
 *
 * Which script runs on which tool is HOOK_MATRIX, a copy of the matchers in
 * hooks/hooks.settings.json (tests/test_pi_extension.py fails if they drift).
 *
 * Subagent identity under gentle-pi, which runs each subagent as its own pi
 * process marked GENTLE_PI_AGENTS_CHILD=1:
 *   agent_id    "pi-<pid>-<load time>", computed once per process, so it is
 *               stable for the subagent's whole life and distinct from any
 *               other subagent, even when two share a session id.
 *   agent_type  METODO_AGENT_TYPE if the spawner sets it; else the role
 *               marker render_agents.py appends to every pi agent
 *               (<!-- metodo-role: <name> -->), read from the system prompt
 *               at before_agent_start; else "pi-subagent", which has no
 *               contract (subagent rules still apply, budget and output
 *               checks do not).
 */

import { spawnSync } from "node:child_process";
import { basename, join } from "node:path";
import { existsSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const TOOLS_ROOT = process.env.METODO_TOOLS || "__TOOLS_DEFAULT__";
const REPO_ROOT = process.env.METODO_REPO || "__REPO_DEFAULT__";
const HOOKS = join(TOOLS_ROOT, "hooks");

// pi built-ins under the names the Python hooks match on. MCP tools already
// carry the Claude name (mcp__metodo__<tool>, toolPrefix "mcp").
const TOOL_NAMES: Record<string, string> = {
	edit: "Edit",
	write: "Write",
	bash: "Bash",
	read: "Read",
	grep: "Grep",
	find: "Glob",
	ls: "LS",
};

/** hooks/hooks.settings.json, PreToolUse and PostToolUse, in its order.
 * A matcher is an anchored regex over the Claude tool name; "" matches all. */
export const HOOK_MATRIX: Record<string, { matcher: string; script: string }[]> = {
	PreToolUse: [
		{ matcher: "Edit|Write|MultiEdit", script: "guard_paths.py" },
		{ matcher: "Bash|mcp__metodo__receipt_start|mcp__metodo__receipt_finalize|mcp__metodo__receipt_acknowledge", script: "guard_gates.py" },
		{ matcher: "", script: "budget.py" },
	],
	PostToolUse: [
		{ matcher: "Bash", script: "guard_gates.py" },
		{ matcher: "Edit|Write|MultiEdit", script: "touched_paths.py" },
	],
};

function scriptsFor(event: string, toolName: string): string[] {
	return (HOOK_MATRIX[event] || [])
		.filter((entry) => entry.matcher === "" || new RegExp(`^(?:${entry.matcher})$`).test(toolName))
		.map((entry) => entry.script);
}

// A receipt tool reached through a generic MCP proxy tool (gentle-pi exposes
// one named `mcp`). Its input shape is not documented here, so any string at
// any depth of the input that ends in receipt_<op> counts, whatever the case,
// padding or separator: a false match only adds a gate.
const RECEIPT_OP = /(?:^|[^a-z0-9])receipt[_-](start|finalize|acknowledge)$/i;

function findReceiptOp(value: unknown, depth = 0): string {
	if (typeof value === "string") return RECEIPT_OP.exec(value.trim())?.[1]?.toLowerCase() || "";
	if (depth > 8 || value === null || typeof value !== "object") return "";
	for (const nested of Object.values(value as Record<string, unknown>)) {
		const op = findReceiptOp(nested, depth + 1);
		if (op) return op;
	}
	return "";
}

/** The name the Python hooks match on for a pi tool call. */
function claudeToolName(piName: string, input: Record<string, unknown>): string {
	if (TOOL_NAMES[piName]) return TOOL_NAMES[piName];
	if (piName === "mcp") {
		const op = findReceiptOp(input || {});
		if (op) return `mcp__metodo__receipt_${op}`;
	}
	return piName;
}

const ROLE_NAME = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
const ROLE_MARKER = /<!--\s*metodo-role:\s*([A-Za-z0-9][A-Za-z0-9_-]{0,63})\s*-->/g;
const PROCESS_AGENT_ID = `pi-${process.pid}-${Date.now().toString(36)}`;
let markerRole = "";

type Decision = { decision?: string; reason: string };

function sessionId(ctx: any): string {
	try {
		const file = ctx?.sessionManager?.getSessionFile?.();
		return file ? basename(String(file)).replace(/\.jsonl?$/, "") : "pi-ephemeral";
	} catch {
		return "pi-ephemeral";
	}
}

/** gentle-pi marks the pi process it spawns for a subagent; the extension is
 * loaded there too, so without this every child call looked like the owner's. */
function isSubagentProcess(): boolean {
	return process.env.GENTLE_PI_AGENTS_CHILD === "1";
}

function agentType(): string {
	if (!isSubagentProcess()) return "";
	const explicit = process.env.METODO_AGENT_TYPE || "";
	return (ROLE_NAME.test(explicit) ? explicit : "") || markerRole || "pi-subagent";
}

/** The Claude Code stdin shape. agent_type and agent_id are what
 * hooks/_common.is_subagent reads: both empty for the owner's session, both
 * set for a subagent process, so the Python guards apply the subagent rule
 * (deny) instead of the owner's (ask), and budget.py counts per agent_id. */
function payload(ctx: any, event: string, toolName: string, input: Record<string, unknown>) {
	return {
		session_id: sessionId(ctx),
		cwd: REPO_ROOT,
		hook_event_name: event,
		tool_name: toolName,
		tool_input: input,
		agent_type: agentType(),
		agent_id: isSubagentProcess() ? PROCESS_AGENT_ID : "",
	};
}

/** Runs one hook and reads its decision. Any failure here is silent and
 * allows: the kit's rule is that a guard never takes the session down. */
function runHook(script: string, body: unknown): Decision | undefined {
	const path = join(HOOKS, script);
	if (!existsSync(path)) return undefined;
	try {
		const proc = spawnSync("python3", [path], {
			input: JSON.stringify(body),
			encoding: "utf8",
			timeout: 10000,
			env: { ...process.env, METODO_TOOLS: TOOLS_ROOT, METODO_REPO: REPO_ROOT },
		});
		const out = (proc.stdout || "").trim();
		if (!out.startsWith("{")) return undefined;
		const parsed = JSON.parse(out);
		const specific = parsed.hookSpecificOutput;
		if (!specific?.permissionDecision) return undefined;
		return { decision: specific.permissionDecision, reason: specific.permissionDecisionReason || "" };
	} catch {
		return undefined;
	}
}

function toolInput(toolName: string, input: Record<string, any>): Record<string, unknown> {
	// pi calls the path `path`; the Python hooks read `file_path`.
	const mapped: Record<string, unknown> = { ...input };
	if (input.path && !input.file_path) mapped.file_path = input.path;
	if (toolName === "Bash" && input.command) mapped.command = input.command;
	return mapped;
}

/** Runs a Stop-family hook that only measures or records: its stdout is not
 * read, because pi has no way to send the agent back after agent_end. */
function runRecorder(script: string, body: unknown): void {
	const path = join(HOOKS, script);
	if (!existsSync(path)) return;
	try {
		spawnSync("python3", [path], {
			input: JSON.stringify(body),
			encoding: "utf8",
			timeout: 10000,
			env: { ...process.env, METODO_TOOLS: TOOLS_ROOT, METODO_REPO: REPO_ROOT },
		});
	} catch {
		// a recorder never gates: a failure here changes nothing.
	}
}

function lastAssistantText(messages: any[]): string {
	for (let i = (messages?.length || 0) - 1; i >= 0; i--) {
		const message = messages[i];
		if (message?.role !== "assistant") continue;
		const content = message.content;
		if (typeof content === "string") return content;
		if (Array.isArray(content)) {
			const text = content.filter((b: any) => b?.type === "text").map((b: any) => b.text).join("\n");
			if (text) return text;
		}
	}
	return "";
}

export default function (pi: ExtensionAPI) {
	let startupStatus = "";
	let statusInjected = false;

	pi.on("session_start", async (_event, ctx) => {
		const path = join(HOOKS, "session_start_status.py");
		if (!existsSync(path)) return;
		try {
			const proc = spawnSync("python3", [path], {
				input: JSON.stringify({ ...payload(ctx, "SessionStart", "", {}), source: "startup" }),
				encoding: "utf8",
				timeout: 10000,
				env: { ...process.env, METODO_TOOLS: TOOLS_ROOT, METODO_REPO: REPO_ROOT },
			});
			startupStatus = (proc.stdout || "").trim();
		} catch {
			startupStatus = "";
		}
		if (startupStatus && ctx.hasUI) ctx.ui.notify(startupStatus.split("\n")[0], "info");
	});

	pi.on("before_agent_start", async (event, _ctx) => {
		// The role comes from the system prompt only, never from the task text.
		// Context files come before the agent body, whose marker is its last
		// line, so the last marker wins; the first role found stays for the
		// life of the process.
		const systemPrompt = (event as any)?.systemPrompt;
		if (isSubagentProcess() && !markerRole && typeof systemPrompt === "string") {
			const markers = [...systemPrompt.matchAll(ROLE_MARKER)];
			markerRole = markers.length ? markers[markers.length - 1][1] : "";
		}
		if (statusInjected || !startupStatus) return undefined;
		statusInjected = true;
		return {
			message: {
				customType: "metodo-status",
				content: startupStatus,
				display: true,
			},
		};
	});

	pi.on("tool_call", async (event, ctx) => {
		const raw = (event.input as Record<string, any>) || {};
		const toolName = claudeToolName(event.toolName, raw);
		const input = toolInput(toolName, raw);
		const body = payload(ctx, "PreToolUse", toolName, input);

		for (const script of scriptsFor("PreToolUse", toolName)) {
			const verdict = runHook(script, body);
			if (!verdict) continue;
			if (verdict.decision === "deny") {
				if (ctx.hasUI) ctx.ui.notify(`metodo: ${verdict.reason}`, "warning");
				return { block: true, reason: verdict.reason };
			}
			if (verdict.decision === "ask") {
				// Claude Code asks the owner here. With no UI there is nobody to
				// ask, so the gate holds instead of waving the call through. A
				// subagent's confirm would hang until its timeout: only the owner's
				// session can answer, so the child is told to report instead.
				if (isSubagentProcess()) return { block: true, reason: `${verdict.reason} (owner gate: report it in your output, the parent session decides)` };
				if (!ctx.hasUI) return { block: true, reason: `${verdict.reason} (owner gate, no UI to confirm)` };
				const ok = await ctx.ui.confirm("metodo gate", verdict.reason);
				if (!ok) return { block: true, reason: verdict.reason };
			}
		}
		return undefined;
	});

	pi.on("tool_result", async (event, ctx) => {
		const raw = (event.input as Record<string, any>) || {};
		const toolName = claudeToolName(event.toolName, raw);
		const body = payload(ctx, "PostToolUse", toolName, toolInput(toolName, raw));
		// PostToolUse scripts only record; their decision, if any, is ignored.
		for (const script of scriptsFor("PostToolUse", toolName)) runRecorder(script, body);
		return undefined;
	});

	pi.on("agent_end", async (event, ctx) => {
		const text = lastAssistantText((event as any).messages || []);
		if (!text) return;
		if (isSubagentProcess()) {
			// SubagentStop on Claude Code. Claude can send the subagent back with
			// the errors; pi cannot here, so the script records the FAIL as
			// invalid-unenforced instead of claiming a block.
			runRecorder("validate_subagent_output.py", {
				...payload(ctx, "SubagentStop", "", {}),
				last_assistant_message: text,
				stop_hook_active: false,
				runtime_can_block: false,
			});
			return;
		}
		// The owner's reply is not linted at Stop time (owner decision D3): the
		// human-reply skill runs the lint on demand.
	});
}
