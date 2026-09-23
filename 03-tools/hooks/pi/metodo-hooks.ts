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
 */

import { spawnSync } from "node:child_process";
import { basename, join } from "node:path";
import { existsSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const TOOLS_ROOT = process.env.METODO_TOOLS || "__TOOLS_DEFAULT__";
const REPO_ROOT = process.env.METODO_REPO || "__REPO_DEFAULT__";
const HOOKS = join(TOOLS_ROOT, "hooks");

// pi built-ins under the names the Python hooks match on.
const TOOL_NAMES: Record<string, string> = {
	edit: "Edit",
	write: "Write",
	bash: "Bash",
	read: "Read",
	grep: "Grep",
	find: "Glob",
	ls: "LS",
};

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

/** The Claude Code stdin shape. agent_type is what hooks/_common.is_subagent
 * reads: empty for the owner's session, a marker for a subagent process, so the
 * Python guards apply the subagent rule (deny) instead of the owner's (ask). */
function payload(ctx: any, event: string, toolName: string, input: Record<string, unknown>) {
	return {
		session_id: sessionId(ctx),
		cwd: REPO_ROOT,
		hook_event_name: event,
		tool_name: toolName,
		tool_input: input,
		agent_type: isSubagentProcess() ? "pi-subagent" : "",
		agent_id: "",
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

	pi.on("before_agent_start", async (_event, _ctx) => {
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
		const toolName = TOOL_NAMES[event.toolName];
		if (!toolName) return undefined;
		const input = toolInput(toolName, (event.input as Record<string, any>) || {});
		const body = payload(ctx, "PreToolUse", toolName, input);

		for (const script of ["guard_paths.py", "guard_gates.py", "budget.py"]) {
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
		const toolName = TOOL_NAMES[event.toolName];
		if (toolName !== "Edit" && toolName !== "Write") return undefined;
		const input = toolInput(toolName, (event.input as Record<string, any>) || {});
		runHook("touched_paths.py", payload(ctx, "PostToolUse", toolName, input));
		return undefined;
	});

	pi.on("agent_end", async (event, ctx) => {
		const text = lastAssistantText((event as any).messages || []);
		if (!text) return;
		const path = join(HOOKS, "reply_lint.py");
		if (!existsSync(path)) return;
		try {
			spawnSync("python3", [path], {
				input: JSON.stringify({ ...payload(ctx, "Stop", "", {}), last_assistant_message: text, stop_hook_active: false }),
				encoding: "utf8",
				timeout: 10000,
				env: { ...process.env, METODO_TOOLS: TOOLS_ROOT, METODO_REPO: REPO_ROOT },
			});
		} catch {
			// reply_lint measures, it never gates: a failure here changes nothing.
		}
	});
}
