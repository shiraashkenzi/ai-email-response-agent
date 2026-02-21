# Deep Architectural and Performance Code Review

**AI Email Agent** — Brutally honest, specific findings and recommendations.

---

## 1. CRITICAL PERFORMANCE BOTTLENECKS

### 1.1 Multiple OpenAI calls per turn (root cause of 18–26s latency)

**Why it happens:** The agent uses a **strict tool-then-LLM loop**. Every time the model returns one or more `tool_calls`, you execute them, append tool results to history, and call the LLM **again**. There is no batching of tool calls across rounds and no “plan then execute” step.

- **Typical flow for “draft a reply to the project proposal email”:**
  1. **OpenAI call 1:** Model calls `search_emails` + `list_emails_summary` (or only search).
  2. **OpenAI call 2:** Model sees search/list result, calls `get_email` (+ often `parse_email`).
  3. **OpenAI call 3:** Model sees full email, calls `generate_reply` (which triggers **another** full OpenAI call inside the tool).
  4. **OpenAI call 4:** Model sees reply text, calls `create_draft` (or sends a final message).
  5. **OpenAI call 5:** Model returns final user-facing message.

So you get **at least 4–5 round-trips** to the API for one user request. At ~3–6s per round-trip, that alone explains 12–30 seconds.

**Concrete change:** You cannot reduce to “one call per turn” without changing the architecture (see Section 7). You can:
- **Batch tool calls:** When the model returns multiple tool_calls in one response, you already execute them in one go; the next round is the bottleneck. Encourage the model (via system prompt) to do “search + list_emails_summary” in one round and “get_email + parse_email” in the next, rather than one tool per round.
- **Avoid nested LLM in tools:** `generate_reply` is a **separate** `chat.completions.create` call inside a tool. So one “agent turn” can include 1 agent call + 1 generate_reply call = 2 OpenAI round-trips in a single iteration. Consider moving reply generation into the main agent (e.g. the model outputs the reply text as content, and a lightweight tool only “registers” it for send/draft) or use a single, larger prompt that includes “generate the reply in this turn” so you don’t need a separate generate_reply tool call.

### 1.2 Redundant Gmail API calls in `list_emails_summary`

**Location:** `tools.py` → `_build_list_emails_summary` handler.

**What it does:** For each of the first N message refs (from `search_emails`), it calls:
- `gmail.get_email(msg_id)` → **full** `messages.get(..., format="full")`
- `gmail.parse_email(full)` → in-process parsing

So for 10 search results you do **10 full message fetches** (including body) only to show one line per message (subject, from, date). That’s 10× more data and 10× more latency than needed.

**Concrete change:** In `gmail_service.py`, add a method that fetches **metadata only**, e.g.:

```python
def get_email_metadata(self, message_id: str, headers: Optional[List[str]] = None) -> Dict[str, Any]:
    # format="metadata", metadataHeaders=["From", "Subject", "Date"]
```

Use it in `list_emails_summary` instead of `get_email` + `parse_email`. If you keep using `get_email`, at least use `format="metadata"` and `metadataHeaders=["From","Subject","Date"]` for this use case so the body is never transferred. That will cut list_emails_summary latency by a large factor (and reduce bandwidth).

### 1.3 No caching of fetched emails

**What happens:** The same email can be fetched multiple times in one turn:
- Once in `list_emails_summary` (get_email per row).
- Again when the user picks “1” and the model calls `get_email(message_id)`.
- Again if the model calls `parse_email(message_id)` (which internally calls `get_email`).

So the **same** message is fetched 2–3 times. No in-memory cache (e.g. by message_id for the current turn).

**Concrete change:** Add a small TTL cache (e.g. in `GmailService` or in the agent’s tool layer) keyed by `message_id` for the duration of one turn, or at least for the process. Invalidate or cap size to avoid unbounded growth.

### 1.4 Blocking, sequential tool execution

**What happens:** All tool calls in a given round are executed **sequentially** in a single thread. If the model returned `[search_emails, list_emails_summary]` in one response, you’d run search, then list (which does N get_email calls one by one). No parallelism.

**Concrete change:** Where tools are independent (e.g. multiple `get_email` calls for different ids), run them concurrently (e.g. `concurrent.futures.ThreadPoolExecutor`) so Gmail API latency doesn’t add up linearly. This is especially impactful for `list_emails_summary` (many get_email/metadata calls).

### 1.5 Token estimation and trim run every iteration

**Location:** `agent.py` → `run_turn` → `_trim_messages_to_fit(self._messages, MAX_MESSAGE_TOKENS)` at the **start of every** loop iteration. Inside, `_messages_token_estimate` walks all messages and touches every role, content, tool_calls, and tool result string.

**Impact:** With many messages, this is O(n) per iteration and the trim loop can pop many times (each pop again O(n) for list). For large histories this adds measurable CPU and latency.

**Concrete change:** (a) Cache the estimated token count and update it incrementally when appending messages; or (b) run trim only when the message list length or total content length exceeds a threshold, not every time; or (c) use a cheaper heuristic (e.g. total character count of last K messages) to decide when to trim.

---

## 2. AGENT ARCHITECTURE

### 2.1 Agent loop is “one decision per round”

The loop is: **LLM → [tool_calls] → execute all → append results → LLM → …**. This is standard “ReAct-style” tool use but inherently causes multiple round-trips. The loop itself is clear and correct; the **cost** is architectural (see Section 7).

### 2.2 Decision and generation are not merged

Today, “decide what to do” and “generate the reply text” are separate: the model either calls tools (including `generate_reply`) or returns content. So “generate reply” is a tool that triggers another LLM call. Merging would mean: in one prompt/response, the model both decides and, when the task is “draft reply”, outputs the reply body as content (or a structured block), and a separate lightweight action (e.g. `create_draft_from_content`) only sends that text to Gmail. That would remove one full LLM round-trip per “draft/send reply” flow.

### 2.3 Tool invocation pattern

- **Positive:** Tools are registered by name, schema is derived once, execution is a simple lookup and `handler(**arguments)`. Clean.
- **Issue:** `send_reply` / `create_draft` never receive `reply_to_email` from the agent. The tool schema and handler in `tools.py` do not include `reply_to_email`; only `gmail_service` supports it. So the **original email is never passed** when sending or drafting from the agent. The service then falls back to the `to` argument from the LLM, which can be wrong or malformed → **production bug** (Invalid To header, or wrong recipient).

**Concrete change:** Add `reply_to_email` (or `original_email`) to the `send_reply` and `create_draft` tool parameters (as optional object). The agent/LLM should pass the last parsed email when replying; the tool handler must forward it to `gmail_service.send_reply` and `create_draft`.

### 2.4 Conversation history growth and trimming

- **Growth:** Every user message, assistant message (with optional tool_calls), and tool result is appended to `_messages`. History grows unbounded across turns.
- **Trimming:** `_trim_messages_to_fit` keeps system + suffix of messages under `MAX_MESSAGE_TOKENS`. Old messages are dropped from the front; when an assistant message with tool_calls is dropped, its tool messages are dropped too. So **history is trimmed per turn** before each LLM call, but the **stored** `_messages` list is never pruned; only the “sent” slice is trimmed. So memory use grows and the trim pass walks the full list each time (see 1.5).

**Concrete change:** After a turn, optionally prune `self._messages` to the same window you’d send (e.g. keep last K messages or last N tokens). That keeps memory and trim cost bounded.

### 2.5 Tool results in history

Tool results are truncated to `MAX_TOOL_RESULT_CHARS` (3500) and appended as `{"role": "tool", "tool_call_id": fid, "content": result_str}`. That’s correct for the OpenAI API. No bug here; the issue is **size** (full email bodies in results) and **redundancy** (same body in get_email result, parse_email result, generate_reply input, and again in history).

---

## 3. LLM USAGE

### 3.1 Prompts and system prompt

- **System prompt:** One long string in `agent.py`, sent on every request as the first message. Not duplicated elsewhere; it’s only in the messages list once per call.
- **Size:** The system prompt is ~1.1k characters (tools list + rules). Reasonable. The main cost is **conversation history** (many turns + tool results) and the **tools schema** (~586 tokens) sent every time.

### 3.2 Conversation history and trimming

- **Trim:** You trim to `MAX_MESSAGE_TOKENS` (7000) before each call. That’s good.
- **Estimation:** Token estimate is `len/4`; real tokenizer can be 20–40% different. If you trim to 7000 estimated, real tokens can be ~8500 and you can hit context limits. Consider a safety margin (e.g. target 6000 estimated) or use tiktoken for the model you use.

### 3.3 Over-sending email bodies

- **get_email** returns the **full** message (including body). That full dict is serialized into the tool result and appended to history (truncated to 3500 chars, but still large).
- **parse_email** returns a flat dict that includes **body**. So the same body appears in: (1) get_email result, (2) parse_email result, (3) generate_reply’s `original_email` (and thus in the generate_reply tool result if the model passes it back). So the **same body is in the conversation 2–3 times**.
- **generate_reply** sends the full `original_email` (including body) in its **own** LLM request (separate from the agent). So the body is again in that request.

**Concrete change:** (a) For the agent, consider tool results that omit body or summarize it (“Body: [1200 chars]…”) when the tool is get_email/parse_email; (b) in the system prompt, instruct the model to use “body excerpt” in summaries and only include full body when necessary for reply generation; (c) for generate_reply, you could pass only a truncated body (e.g. first 500 chars) and still get a reasonable draft.

### 3.4 Reducing model calls to one per turn

With the current “tool then LLM” loop, **one call per user turn is not possible** if the agent must use tools: you need at least one call to decide, then after tools another call to decide or respond. To approach “one call per turn” you’d need a different design, e.g.:
- **Structured output / function calling with “plan”:** One call returns a full plan (e.g. search → get_email(1) → generate_reply → create_draft); you execute the plan and only then, if needed, one more call to format the final user message. That’s 2 calls per turn instead of 4–5.
- **Single “mega” turn:** One prompt that includes “here are the tools and their results so far; output either more tool calls or the final answer.” You’d need to run tools and re-call with the same “turn” until the model outputs no tool calls. That still implies multiple calls for multi-step flows but with a clearer “one logical turn” boundary.

---

## 4. GMAIL SERVICE

### 4.1 Redundant encoding/decoding

- **Outgoing:** `_build_reply_message` builds MIME and returns `base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")`. One encode; no redundant encoding.
- **Incoming:** `get_email` returns the raw API response (payload has base64-encoded body). `_extract_body` decodes once per part. No double-decode in the same code path. But when the same message is fetched multiple times (see 1.3), you decode the same body multiple times.

### 4.2 Repeated header parsing

- **parse_email** walks `payload["headers"]` with a linear scan per header name (From, To, Subject, Date, etc.). So each header is O(n) over the list. For a single message that’s fine. When you call parse_email repeatedly for the same message (e.g. after get_email, then again in list_emails_summary for the same id if it were cached as full), you’d parse again. The main issue is repeated **fetch**, not repeated parse.

### 4.3 Unnecessary API calls

- **list_emails_summary:** Uses full `get_email` for each id → N full fetches. Should use metadata-only fetch (see 1.2).
- **Duplicate fetches:** Same message_id fetched multiple times in one turn (see 1.3).

### 4.4 threadId

- **send_reply:** Correctly passes `threadId` in the send body. **create_draft:** Correctly passes `threadId` in the draft message when provided. No misuse detected.

---

## 5. ERROR HANDLING

### 5.1 Broad exceptions

- **agent.py:** `except Exception as e` when executing a tool: captures everything (including KeyboardInterrupt if it were raised from the handler), turns it into a string and continues. That’s intentional so one failing tool doesn’t kill the turn, but it **swallows** the exception type and stack for the caller. The CLI only sees “Error: …” in the agent response.
- **gmail_service:** `except Exception as e` in `search_emails` re-raises as GmailError. Broad but acceptable for “anything else”.

**Suggestion:** In the agent, at least log the exception type and re-raise certain critical errors (e.g. LLMError, KeyboardInterrupt) instead of converting to a string. For tool errors, you could attach a small “error_code” or “tool_failed” marker so the model can react differently than to normal output.

### 5.2 Swallowed errors

- **list_emails_summary:** `except Exception:` with no log: when one message fails to load, you append `[error loading] (id: …)` and continue. The exception is swallowed. Prefer `logger.debug` or `logger.warning` with the message id and exception message so failures are visible in logs.

### 5.3 Retries

- **OpenAI:** No retries on rate limit (429) or transient errors. One failure fails the turn.
- **Gmail:** No retries on 5xx or transient network errors.

**Suggestion:** Add a small retry layer (e.g. 2 retries with backoff) for 429 and 5xx in the LLM and Gmail clients. Use exponential backoff to avoid hammering the APIs.

---

## 6. CODE QUALITY

### 6.1 Duplication

- **Recipient resolution:** `_build_reply_message` and `_normalize_recipient` both deal with “from” / “to”. Resolution logic is in `_build_reply_message` (using _normalize_recipient); create_draft/send_reply no longer duplicate MIME build. Good.
- **Tool result truncation:** Only in agent (`_truncate_tool_result`). No duplication.
- **Error message strings:** GmailError for invalid recipient is similar in create_draft and send_reply; it’s now centralized in _build_reply_message. Good.

### 6.2 Refactors and helpers

- **Token estimation:** Could be a small module or use `tiktoken` so both agent and (if needed) tools share one implementation.
- **Tool execution:** The “parse arguments → execute_tool → serialize result → append to messages” block in the agent could be a helper, e.g. `_execute_tool_calls(tool_calls) -> list of (tool_call_id, content)` to shorten `run_turn` and make it easier to add parallelism or caching.

### 6.3 Separation of concerns

- **Agent** does: history, trim, LLM call, tool dispatch, timing. Reasonable. Trimming logic could live in a small “context manager” that takes messages and returns the slice to send.
- **Tools** are stateless and receive services; clean.
- **Gmail** does not know about the agent or LLM; good.

---

## 7. LOGGING

### 7.1 Verbosity

- You already set httpx and googleapiclient to WARNING. Per-turn and per–OpenAI-call logs are at INFO. That’s reasonable. If you run in production with INFO, you’ll get one log line per OpenAI call and one summary per turn; not excessive.

### 7.2 Blocking

- Logging is synchronous. For high throughput it could matter; for an interactive CLI it’s negligible. No change needed unless you move to async.

### 7.3 Structure

- Using `logger.info("OpenAI call took %.0f ms", ...)` and the “Turn / OpenAI / Gmail / Other” summary is clear. For production you might add a structured field (e.g. `turn_id`, `openai_ms`) so logs can be queried by metric.

---

## 8. MEMORY & STATE

### 8.1 Unbounded conversation history

- **Yes.** `self._messages` only grows; only the **slice** sent to the API is trimmed. So over a long session you can have hundreds of messages in memory and trim runs over all of them each turn (see 1.5).

**Concrete change:** Prune `self._messages` after each turn to the same window you use for the next call (e.g. keep system + last 20 messages or last 6000 estimated tokens). That bounds memory and keeps trim cheap.

### 8.2 Pruning or summarizing

- No summarization of old turns. You could add a step: when trimming, replace the oldest “user + assistant + tools” block with a short summary message (e.g. “User searched for X; agent listed 5 emails; user chose #1.”) so the model keeps context without full history. That’s a larger change.

### 8.3 Email body sent multiple times

- Yes (see 3.3). Same body in get_email result, parse_email result, and possibly in generate_reply and in tool results. Truncation limits size but doesn’t remove redundancy. Sending a body once (or a short digest) in the agent context and referencing it by id or “the email above” would reduce tokens.

---

## 9. PRODUCTION RISKS

- **Invalid or wrong recipient:** send_reply/create_draft are never given `reply_to_email` from the tools layer → fallback to LLM-provided `to` → can be wrong or invalid. **Fix:** Add reply_to_email to tool schema and pass parsed email from context.
- **Context length exceeded:** Trim target (7000) with char/4 estimate can still exceed 8192. **Fix:** Lower MAX_MESSAGE_TOKENS or use tiktoken.
- **No retries:** One 429 or transient Gmail/OpenAI failure fails the whole turn. **Fix:** Retry with backoff.
- **Tool failure only as string:** Model sees “Error: …” and may retry the same failing call. **Fix:** Consider structured error (e.g. `{"error": true, "message": "..."}`) and/or prompt the model to not retry the same tool with same args.

---

## 10. SIMPLIFIED HIGH-PERFORMANCE AGENT LOOP (PROPOSAL)

Goal: Reduce to **~2–3 LLM round-trips** per user turn and cut Gmail round-trips.

**A. Plan-then-execute (2 phases)**

1. **Phase 1 — Plan:** One LLM call with system prompt + user message + (optional) short “recent context” (e.g. last turn only). Ask the model to output a **structured plan**: list of tool calls with name and arguments (and optionally “final reply text” if the task is “draft a reply”). No tools in this call; use JSON or structured output.
2. **Phase 2 — Execute:** Run all planned tool calls (with parallelism where independent). If the plan included “reply text”, call create_draft/send_reply with that text; no generate_reply tool.
3. **Phase 3 — Confirm (optional):** One short LLM call with “Here’s what was done: …” and “Summarize for the user in one sentence” to produce the final message. Or skip and format a fixed template from the plan result.

So: **2 LLM calls** (plan + optional confirm) instead of 4–5. Latency drops roughly by half or more.

**B. Single “tool round” with batched tools**

- Keep the current loop but:
  - Use **metadata-only** fetch for list_emails_summary (and optional caching for get_email).
  - **Remove** the generate_reply **tool**; instead, in the system prompt, instruct the model to output the reply **in the assistant message content** when it has the email (e.g. in a markdown block or after “REPLY_BODY:”). A tiny tool `create_draft_from_content(content, thread_id, subject, to)` (or reuse create_draft with body from content) would then create the draft without another LLM call. That saves 1–2 LLM calls per “draft reply” flow.
  - Add **reply_to_email** to send_reply/create_draft and pass the last parsed email from the agent so recipient is always correct.

**C. Caching and Gmail**

- **Turn-scoped cache:** Keyed by message_id, store get_email (or get_email_metadata) results for the current turn; reuse in list_emails_summary, get_email, parse_email.
- **list_emails_summary:** Use `get_email_metadata(msg_id, ["From","Subject","Date"])` (or a new method) instead of full get_email + parse_email. Optionally run these metadata fetches in parallel (e.g. ThreadPoolExecutor).

Implementing **B + C** gives the largest gain with minimal architectural change; **A** is a cleaner but bigger refactor.

---

## 11. SUMMARY TABLES

### Critical performance bottlenecks

| # | Bottleneck | Impact | Fix |
|---|------------|--------|-----|
| 1 | 4–5+ OpenAI round-trips per turn | 12–30s | Plan-then-execute or merge reply generation into agent content |
| 2 | generate_reply = extra LLM call inside tool | +3–6s per draft | Have model output reply in content; tool only create_draft(sent body) |
| 3 | list_emails_summary: N full get_email | N × ~500ms + bandwidth | Use metadata-only fetch (format=metadata, metadataHeaders) |
| 4 | Same email fetched 2–3 times per turn | 2–3× Gmail latency | Turn-scoped cache by message_id |
| 5 | Sequential tool execution | Sum of Gmail latencies | Parallelize independent get_email/metadata calls |
| 6 | Trim + token estimate every iteration | CPU + latency with long history | Incremental token count or trim only when needed |

### Architectural improvements

| # | Improvement | Benefit |
|---|-------------|---------|
| 1 | Pass reply_to_email in send_reply/create_draft tools | Correct recipient; fewer Invalid To errors |
| 2 | Prune _messages after each turn (same as sent window) | Bounded memory; faster trim |
| 3 | Optional “plan” phase (structured output) then execute | Fewer LLM round-trips |
| 4 | Structured tool errors (e.g. error: true) | Model can avoid pointless retries |
| 5 | Retries with backoff for 429/5xx | More robust in production |

### Concrete refactor suggestions (short list)

1. **gmail_service:** Add `get_email_metadata(message_id, headers=["From","Subject","Date"])` and use it in list_emails_summary.
2. **tools.py:** Add `reply_to_email` (optional) to send_reply and create_draft; agent or tool layer passes last parsed email when available.
3. **agent.py:** After each turn, set `self._messages = [system] + _trim_messages_to_fit(rest, MAX_MESSAGE_TOKENS)` so stored history stays bounded.
4. **tools.py (list_emails_summary):** On exception, log at debug/warning with message_id and error.
5. **llm_service / gmail_service:** Wrap create/execute in a retry helper (e.g. 2 retries, exponential backoff) for 429 and 5xx.
6. **agent.py:** Consider replacing generate_reply tool with “model outputs reply in content”; add a tool “create_draft_with_body(body, …)” that only does MIME + drafts.create.
7. **agent.py:** When executing multiple tool calls, run independent ones (e.g. multiple get_email for different ids) in ThreadPoolExecutor.

---

*End of review.*
