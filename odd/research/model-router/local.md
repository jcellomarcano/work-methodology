# Research R4: local open-weight models for coding and agentic work

Read date for every source: 2026-10-16. Lane R4 of `odd/tasks/model-router.md` (S2, S3). Tags follow the kit:
**[Measured]** = observed on this machine or read verbatim from a fetched source [S#];
**[Inferred]** = reasoning from cited facts; **[Unknown]** = not established. Benchmark numbers are
**vendor-claimed** (the vendor's own harness), never measured here. No model was downloaded.

## 1. Model map (open weights, runnable locally)

Sizes are Ollama tag sizes (weights only, no KV cache) from the tags pages [S2]; params, license and
repo-creation date come from the Hugging Face API [S40]; context and controls from each model card.

| Model (HF repo) | Params total / active | License | Date | Native context | Ollama tag: size | Thinking / effort control | Tools | Coding claims (vendor-claimed) |
|---|---|---|---|---|---|---|---|---|
| Qwen3.8-27B (`Qwen/Qwen3.8-27B`) [S22] | 27.8B dense | Apache-2.0 | HF repo 2026-08-05 | 262,144 (to 1M with YaRN) | `qwen3.8:27b-q4_K_M` 18GB; `-q8_0` 30GB; `-bf16` 56GB; `-nvfp4` (MLX) 18GB | on by default; `enable_thinking` false per request; `reasoning_effort` xhigh (default) / medium / low; `preserve_thinking` | yes (Ollama `tools`) | Terminal Bench 2.1 73.0; SWE-bench Pro 61.7; LiveCodeBench v6 90.3 |
| Qwen3.6-35B-A3B (`Qwen/Qwen3.6-35B-A3B`) [S23] | 36.0B / 3B | Apache-2.0 | HF repo 2026-04-15 | 262,144 | `qwen3.6:35b-a3b-q4_K_M` 24GB; `-q8_0` 39GB; `qwen3.6:27b-q4_K_M` 17GB | `enable_thinking`, `preserve_thinking` via `chat_template_kwargs` | yes | SWE-bench Verified 73.4; SWE-bench Pro 49.5; Terminal-Bench 2.0 51.5 |
| Qwen3.5-9B (`Qwen/Qwen3.5-9B`) [S24] | 9.65B | Apache-2.0 | HF repo 2026-02-27 | 262,144 | `qwen3.5:9b-q4_K_M` 6.6GB; `-q8_0` 10GB; also 0.8b / 2b / 4b (1.0-5.2GB) | thinking on by default; `enable_thinking` false | yes | not recorded |
| Gemma 4 31B / 26B-A4B / 12B / E4B / E2B (`google/gemma-4-31B-it`, `-26B-A4B-it`) [S25][S26][S27] | 31.3B dense; 25.8B total, 3.8B active | Apache 2.0 | blog 2026-04-02 | 128K (E2B, E4B); 256K (12B, 26B, 31B) | `gemma4:31b-it-q4_K_M` 20GB, `-q8_0` 34GB; `26b-a4b-it-q4_K_M` 18GB, `-q8_0` 28GB; `12b-it-q4_K_M` 8.0GB; `e4b-it-q4_K_M` 6.6GB | `<\|think\|>` token in system prompt on/off (no levels in card) | native function calling | LiveCodeBench v6: 80.0 / 77.1 / 72.0 / 52.0 / 44.0 (31B / 26B / 12B / E4B / E2B) |
| gpt-oss-20b / gpt-oss-120b (`openai/gpt-oss-*`) [S28][S29] | 21B / 3.6B; 117B / 5.1B | Apache 2.0 | HF repo 2025-08-04 | 128K (Ollama) | native MXFP4: `gpt-oss:20b` 14GB; `gpt-oss:120b` 65GB | reasoning low / medium / high via system prompt; Ollama `think` levels, default medium [S4] | function calling, browsing, Python | none in card; Laguna's table lists gpt-oss-120B SWE-Bench Pro 16.2% [S30] |
| Laguna XS 2.1 (`poolside/Laguna-XS-2.1`) [S30] | 33.4B / 3B | OpenMDW-1.1 | HF repo 2026-06-20 | 262,144 | `laguna-xs-2.1:q4_K_M` 20GB; `:q8_0` 36GB; `:nvfp4` (MLX) 20GB | `enable_thinking` per request; interleaved, preserved thinking | yes (`poolside_v1` parser) | SWE-bench Verified 70.9%; SWE-Bench Pro 47.6%; Terminal-Bench 2.0 37.5% |
| North Mini Code 1.0 (`CohereLabs/North-Mini-Code-1.0`) [S31][S32] | 30.5B / 3B | Apache 2.0 | HF repo 2026-06-05 | 256K, 64K max output | `north-mini-code-1.0:q4_K_M` 19GB; `:q8_0` 32GB; `:mlx-nvfp4` 20GB | interleaved thinking; card says it works best on | yes | AA Coding Index 33.4 (blog); per-benchmark scores only in an image [Unknown] |
| Nemotron 3.5 Lightning (`nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16`) [S33] | 31.6B / 3B | OpenMDW-1.1 | card: August 11, 2026 | up to 1M | `nemotron-3.5-lightning:30b-a3b-q4_K_M` 25GB; `-q8_0` 35GB; `-nvfp4` (MLX) 23GB (256K) | `enable_thinking=True/False`; vLLM `thinking_token_budget` [S18] | yes (`qwen3_coder` parser) | SWE-bench Verified 51.56; Terminal-Bench 2.1 24.58 (NVIDIA harness) |
| Muse Glimmer 30B (`meta-models/Muse-Glimmer-30B`, org "Meta Inc.", verified [S41]) [S34] | 29.8B dense + perception encoder | Apache 2.0 | card: August 2026 | 131,072+ (Ollama 128K) | `muse-glimmer:30b-q4_K_M` 18GB; `-q8_0` 31GB; `-mlx` 19GB | system prompt `Reasoning strength: <value>`, low / medium / high / xhigh | yes | SWE-Bench Pro 51.2; SWE-Bench Verified 76.0; TerminalBench 2.1 51.7 (high reasoning) |
| Devstral Small 2 (`mistralai/Devstral-Small-2-24B-Instruct-2512`) [S35] | 24.0B dense | Apache-2.0 | HF repo 2025-11-28 | 256k (Ollama lists 384K) | `devstral-small-2:24b-instruct-2512-q4_K_M` 15GB; `-q8_0` 26GB | none stated; no `thinking` capability on Ollama [S1] | yes | SWE Bench Verified 68.0%; Terminal Bench 2 22.5% |
| GLM-4.7-Flash (`zai-org/GLM-4.7-Flash`) [S36] | 31.2B, "30B-A3B" | MIT | HF repo 2026-01-19 | 198K (Ollama) | `glm-4.7-flash:q4_K_M` 19GB; `:q8_0` 32GB | Preserved Thinking mode for agentic tasks | yes | SWE-bench Verified 59.2 |

Open weights that do **not** fit this machine (section 2): `gpt-oss:120b` 65GB; `qwen3.5:122b` 81GB;
Qwen3.8-Flash-Next 125B-A6B (`nvfp4` 105GB) [S2]; GLM-5.3-Flash, "320B total parameters and just 18B
active parameters" [S37], MIT; DeepSeek-V4.1-Flash, 552B backbone, MIT [S38]; Kimi K3, 2.8T total /
104B activated, Kimi K3 License [S39]. On Ollama the last three are `:cloud` tags only [S2], that is,
remote inference, not local. Meta's larger Muse Spark Open (816B / 42B active) is also listed [S1].

Thinking-control notes [Measured]: Qwen3.8 says "Thinking mode is on by default and can be disabled per
request" [S22]. Gemma 4: "Thinking is enabled by including the `<|think|>` token at the start of the
system prompt." [S25], and vLLM notes "Gemma 4 reasoning is disabled by default" [S18]. gpt-oss: "The
reasoning level can be set in the system prompts" [S28]. NVIDIA warns its table is not vendor-neutral
either: "Accuracy numbers measured by NVIDIA under a consistent harness" [S33]. Scores across rows use
different harnesses (Claude Code, SWE-agent, Harbor, NeMo Gym), so they are not comparable row to row
[Inferred].

## 2. This machine

| Fact | Value | How |
|---|---|---|
| Arch / CPU | `arm64`, `Apple M1 Max`, 10 cores | `uname -m`; `sysctl -n machdep.cpu.brand_string`; `sysctl -n hw.ncpu` [Measured] |
| Memory | 68719476736 bytes = 64 GiB unified | `sysctl -n hw.memsize` [Measured] |
| OS | macOS 27.0.1 (26A434) | `sw_vers` [Measured] |
| GPU wired limit | `iogpu.wired_limit_mb: 0` (meaning of 0 not sourced) | `sysctl iogpu.wired_limit_mb` [Measured]; semantics [Unknown] |
| Ollama | client 0.34.4 at `/usr/local/bin/ollama`; "could not connect to a running Ollama instance"; `ollama list` empty | `ollama --version`, `ollama list` [Measured] |
| llama.cpp | `llama-server` not on PATH | `which llama-server` [Measured] |
| LM Studio | `lms` at `~/.lmstudio/bin/lms` (CLI commit 6041ae0) | `which lms`; `lms version` [Measured] |
| pi | 1.3.0; `pi --list-models ollama` lists no Ollama model (only a fuzzy Gemini match) | [Measured]; no `models.json` provider for Ollama is active [Inferred] |

Fit at 64 GiB [Inferred]: the weights share unified memory with macOS, the harness and the KV cache,
and Ollama says "Setting a larger context length will increase the amount of memory required to run a
model." [S7]. A working rule is weights at most ~40 GB, leaving ~24 GB for KV cache and the OS.

| Class | Q4 (`q4_K_M` / `nvfp4`) | Q8 (`q8_0` / `mxfp8`) | BF16 |
|---|---|---|---|
| 0.8B-12B (Qwen3.5 small, Gemma 4 E2B/E4B/12B) | fits, several at once | fits | fits up to 12B (24GB) |
| 24B-36B (Qwen3.8-27B, Qwen3.6-35B-A3B, Gemma 4 26B/31B, Laguna XS 2.1, North Mini Code, Nemotron Lightning, Muse Glimmer, Devstral Small 2, GLM-4.7-Flash; gpt-oss-20b native) | fits (15-25GB) with 64K-128K context | fits (26-39GB) with reduced context | does not fit with useful context (52-72GB) |
| 117B+ (gpt-oss-120b, Qwen3.5-122B, Qwen3.8-Flash-Next, GLM-5.3-Flash, DeepSeek-V4.1-Flash, Kimi K3) | does not fit (65GB+) | no | no |

Throughput (tokens/s) on the M1 Max is [Unknown]: nothing was run. Ollama ships MLX-engine tags (`-mlx`,
`nvfp4`, `mxfp8`) and states "Ollama’s MLX engine provides state-of-the-art performance on Apple
Silicon" [S3] (vendor claim). Laguna XS 2.1 warns "`ollama run` may currently return empty output on
Apple Silicon" [S30]; the llama.cpp fix it cites (PR 25389) is `closed`, not merged [S42], so Laguna
on this Mac through Ollama is [Unknown] until tested.

## 3. Runtime controls (exact syntax)

| Runtime | Endpoint | Model | Context | Thinking / effort per request |
|---|---|---|---|---|
| Ollama native [S4][S6][S7] | `http://localhost:11434/api/chat` | `"model": "qwen3.8:27b-q4_K_M"` | `"options": {"num_ctx": 65536}`; server default `OLLAMA_CONTEXT_LENGTH=64000 ollama serve`; CLI `/set parameter num_ctx 4096` | `"think": true` / `false` / `"low"` `"medium"` `"high"` (model-defined); discover via `/api/show` field `thinking.values`; CLI `ollama run M --think=low --hidethinking` [Measured `ollama run --help`] |
| Ollama OpenAI-compatible [S5] | `http://localhost:11434/v1/` (`/chat/completions`, `/responses`), `api_key` "required but ignored" | `model` = tag | no per-request field: Modelfile `PARAMETER num_ctx <n>` then `ollama create` | `reasoning_effort` or `reasoning.effort`; `/v1/responses` also takes `think` |
| Ollama Anthropic-compatible [S8] | `ANTHROPIC_BASE_URL=http://localhost:11434` | `claude --model <tag>` | as native | "Use thinking controls with compatible models" |
| llama.cpp `llama-server` [S11] | OpenAI `/v1/chat/completions`; Anthropic `/v1/messages` | one GGUF (`-m`) or router `--models-dir` [L3] | `-c, --ctx-size N` (0 = from model) | server: `--reasoning-effort LEVEL`, `--reasoning-budget N`, `--reasoning-format`, `--jinja` (tools); request: `"chat_template_kwargs": {"enable_thinking": false}`, `"reasoning_effort": "none"` disables |
| LM Studio [S12]-[S17] | `http://localhost:1234/v1` (`/chat/completions`, `/responses`); Anthropic `/v1/messages` | `model` = model key | `lms load <model_key> --context-length 4096`; REST `"context_length": 16384`; `lms load --estimate-only <key>` previews memory | `/v1/responses`: `"reasoning": { "effort": "low" }`; the chat-completions parameter list shows no reasoning field [Measured absence] |
| vLLM [S18] | OpenAI-compatible server | served model | `--max-model-len` [S33] | server `--reasoning-parser <p>`, `--default-chat-template-kwargs '{"enable_thinking": false}'`; request `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`, `thinking_token_budget`; Apple-silicon support not checked [Unknown] |
| MLX-LM [S19][S44] | `mlx_lm.server --model <repo>` on `localhost:8080`, `/v1/chat/completions` | `--model` | `--max-kv-size n` (rotating cache) | not documented in the fetched pages [Unknown]; "The MLX LM server is not recommended for production" [S19] |

Harness hookup:

- **pi** [L2][L4][S10]: add a provider to `~/.pi/agent/models.json`
  (`"baseUrl": "http://localhost:11434/v1"`, `"api": "openai-completions"`, `"apiKey": "ollama"`,
  `"models": [{ "id": "<tag>" }]`), then `pi --model ollama/<tag> --thinking low`. pi levels are
  `off minimal low medium high xhigh max`, "clamped to the model's capabilities" [L4]; per-model
  `thinkingLevelMap` maps them to provider values [L5]. Shortcut: `ollama launch pi --model <tag>`
  [S10]. llama.cpp router: `/login llama.cpp` or `LLAMA_BASE_URL=http://127.0.0.1:8080` [L3].
- **Codex CLI** [S9][S21]: `codex --oss -m gpt-oss:20b`; choose `--local-provider` or set
  `oss_provider = "ollama" # or "lmstudio"`; `ollama launch codex`. Effort in config:
  `model_reasoning_effort = "medium"` [S21].
- **Claude Code** [S8][S15][S20]: Ollama documents `ANTHROPIC_AUTH_TOKEN=ollama ANTHROPIC_API_KEY=""
  ANTHROPIC_BASE_URL=http://localhost:11434 claude --model <tag>` and `ollama launch claude --model <tag>`;
  LM Studio documents `ANTHROPIC_BASE_URL=http://localhost:1234`. Anthropic's own gateway page says it
  "doesn’t support routing Claude Code to non-Claude models through any gateway" [S20]: works per
  Ollama and LM Studio, unsupported by Anthropic.

Context guidance: "Tasks which require large context like web search, agents, and coding tools should be
set to at least 64000 tokens." [S7]; "Use a context window of at least 64k tokens for Codex." [S9].
Ollama's defaults conflict across pages: "By default, Ollama uses a context window size of 4096 tokens."
[S6] versus ">= 48 GiB VRAM: 256k context" [S7]. Which one applies to 64 GiB unified memory is
[Unknown]; set `num_ctx` explicitly.

## 4. Fit with the kit's roles [Inferred]

| Kit use | Local fit | Why (cited) |
|---|---|---|
| Small tier: `generic-style-reviewer`, `generic-mechanic`, `generic-comment-gate` (15k cap) | **Good**: Qwen3.5-9B, Gemma 4 12B/E4B, gpt-oss-20b at low effort or thinking off | the role "interprets a measured result against a fixed rulebook" with a 15k cap [L1], well inside local context; pi lists llama.cpp chat models as classifiers [L2]. Risk: "Small models may follow instructions written inside the state." [L3] |
| Privacy-sensitive repos, offline work | **Good**, with cloud disabled | "Ollama runs locally. We don’t see your prompts or data when you run locally." [S6]; set `OLLAMA_NO_CLOUD=1` [S6] because `:cloud` tags run remotely [S2]; Gemma: "Gemma 4 supports high-quality offline code, turning your workstation into a local-first AI code assistant." [S27] |
| Medium tier: proposer 60k, verifier 40k, scoped cartographer | **Candidate only**: 24B-36B at Q4 with 64K context, after the admission test in `multi-provider-routing.md` | vendor-claimed SWE-bench numbers in section 1 approach hosted small models (Laguna lists Claude Haiku 4.5 at 73.3% vs its 70.9% [S30]), but harnesses differ and nothing was measured here |
| Full-repo cartography | **Poor** | the origin project measured "Full-repo cartographers: 135k-182k tokens each." [L1], beyond the 64K-128K that fits next to 18-25GB of weights |
| Large tier: `generic-challenger`, `generic-blind-spot-adversary`, irreversible changes | **Not a fit** | only ~30B models fit; Muse Glimmer's card reports "showing strictly lower capabilities than larger open-weight models" [S34]; the kit verifies a small model's critical finding "above" [L1] |
| Parallel local fan-out | **Limited** | "Required RAM will scale by OLLAMA_NUM_PARALLEL * OLLAMA_CONTEXT_LENGTH." [S6]; on 64 GiB, "Cheap fan-out, expensive funnel." [L1] means serialized local calls, not many parallel ones |
| Local model inside Claude Code | **Avoid for kit roles** | unsupported by Anthropic [S20]; use pi or Codex CLI, which document local providers [L2][S21] |

## 5. Uncertain

- Release dates marked "HF repo" are repo-creation dates from the HF API, not announcements.
- North Mini Code's per-benchmark scores are only in an image; Nemotron's harness table is an image too.
- Context for Devstral Small 2: 256k in the card, 384K on Ollama. Muse Glimmer: 131,072+ vs 128K.
- Real memory with KV cache, tokens/s and tool-call reliability on this M1 Max: [Unknown] until a model is
  pulled and run (not done; the parent forbade downloads).

## Sources (read 2026-10-16; HTTP status from `curl -sL -w '%{http_code}'`)

| ID | URL | Status |
|---|---|---|
| S1 | https://ollama.com/library?sort=newest | 200 |
| S2 | https://ollama.com/library/{qwen3.8,qwen3.6,qwen3.5,gemma4,gpt-oss,laguna-xs-2.1,north-mini-code-1.0,nemotron-3.5-lightning,muse-glimmer,devstral-small-2,glm-4.7-flash,qwen3.8-flash-next,glm-5.3-flash,deepseek-v4.1-flash,kimi-k3}/tags | 200 each |
| S3 | https://ollama.com/library/muse-glimmer | 200 |
| S4 | https://docs.ollama.com/capabilities/thinking | 200 |
| S5 | https://docs.ollama.com/api/openai-compatibility | 200 |
| S6 | https://docs.ollama.com/faq | 200 |
| S7 | https://docs.ollama.com/context-length | 200 |
| S8 | https://docs.ollama.com/integrations/claude-code | 200 |
| S9 | https://docs.ollama.com/integrations/codex | 200 |
| S10 | https://docs.ollama.com/integrations/pi | 200 |
| S11 | https://raw.githubusercontent.com/ggml-org/llama.cpp/master/tools/server/README.md | 200 |
| S12 | https://lmstudio.ai/docs/developer/openai-compat | 200 |
| S13 | https://lmstudio.ai/docs/developer/openai-compat/chat-completions | 200 |
| S14 | https://lmstudio.ai/docs/developer/openai-compat/responses | 200 |
| S15 | https://lmstudio.ai/docs/developer/anthropic-compat | 200 |
| S16 | https://lmstudio.ai/docs/cli/local-models/load | 200 |
| S17 | https://lmstudio.ai/docs/developer/rest/load | 200 |
| S18 | https://docs.vllm.ai/en/latest/features/reasoning_outputs.html | 200 |
| S19 | https://raw.githubusercontent.com/ml-explore/mlx-lm/main/mlx_lm/SERVER.md | 200 |
| S20 | https://code.claude.com/docs/en/llm-gateway | 200 |
| S21 | https://developers.openai.com/codex/config-advanced | 200 |
| S22-S26 | https://huggingface.co/{Qwen/Qwen3.8-27B, Qwen/Qwen3.6-35B-A3B, Qwen/Qwen3.5-9B, google/gemma-4-31B-it, google/gemma-4-26B-A4B-it}/raw/main/README.md | 200 each |
| S27 | https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/ | 200 |
| S28-S31 | https://huggingface.co/{openai/gpt-oss-20b, openai/gpt-oss-120b, poolside/Laguna-XS-2.1, CohereLabs/North-Mini-Code-1.0}/raw/main/README.md | 200 each |
| S32 | https://huggingface.co/blog/CohereLabs/introducing-north-mini-code | 200 |
| S33-S39 | https://huggingface.co/{nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16, meta-models/Muse-Glimmer-30B, mistralai/Devstral-Small-2-24B-Instruct-2512, zai-org/GLM-4.7-Flash, zai-org/GLM-5.3-Flash, deepseek-ai/DeepSeek-V4.1-Flash, moonshotai/Kimi-K3}/raw/main/README.md | 200 each |
| S40 | https://huggingface.co/api/models/{repo} for every repo in S22-S39 (license tag, `safetensors.total`, `createdAt`) | 200 each |
| S41 | https://huggingface.co/api/organizations/meta-models/overview | 200 |
| S42 | https://api.github.com/repos/ggml-org/llama.cpp/pulls/25389 | 200 |
| S43 | https://huggingface.co/api/models?author={Qwen,google,openai,poolside,nvidia,CohereLabs,mistralai,zai-org,deepseek-ai,facebook,meta-llama,moonshotai,microsoft}&sort=createdAt&direction=-1&limit=25 (discovery) | 200 each |
| S44 | https://raw.githubusercontent.com/ml-explore/mlx-lm/main/README.md | 200 |
| L1 | `00-principles/model-routing.md` (this repo) | local |
| L2-L4 | pi 1.3.0 installed docs: `docs/models.md`, `docs/llama-cpp.md`, `docs/cli.md` under `/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/` | local |
| L5 | same package, `schemas/models.schema.json` (`ThinkingLevelMap` keys) | local |
