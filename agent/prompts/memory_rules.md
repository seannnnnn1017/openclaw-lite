## Memory Architecture

Long-term memory lives under `agent/data/memories/` in three tiers:
- **Hot** — `MEMORY.md` index, injected every turn (index lines only, no content)
- **Warm** — `topics/*.md` files, loaded on demand by a selector model
- **Cold** — `transcripts/*.jsonl`, keyword-searchable with `memory.search`

Never use `file-control` to access files inside `agent/data/memories/`. The runtime handles all memory paths internally.

---

## Writing Memory

To create or update a topic file, emit exactly this JSON (nothing else in the reply):

```
{"memory":"write","file":"<filename>.md","skill":"<skill-name or null>","title":"<one-line title>","tags":["tag1"],"content":"<markdown content>"}
```

The runtime writes `topics/<filename>.md` and updates `MEMORY.md` automatically.

### When to write

| Trigger | Example |
|---------|---------|
| User says "remember this" / "以後都這樣" | Explicit instruction |
| A gotcha or known issue is discovered | Skill returned unexpected error, fix is worth keeping |
| A stable preference is confirmed | Default database, language style, workflow rule |

### When NOT to write

- Code snippets (code changes, memory does not)
- One-time task instructions
- Temporary debug state or in-progress work

---

## Choosing a filename

1. **Before writing**, check `MEMORY.md` index to see if a relevant topic file already exists.
2. **Same topic** → reuse the existing filename (overwrite). Do not create a duplicate.
3. **New independent topic** → use a new descriptive kebab-case filename.

Examples of correct scoping:
- `notion-schedule-preference.md` — Notion schedule DB defaults
- `notification-workflow.md` — how notifications are routed
- `user-language-preference.md` — language and tone preferences

---

## Searching Memory

To search past conversations (Cold tier):

```
{"memory":"search","query":"<keyword>","limit":20}
```

Returns matching lines with ±2 lines of context from transcript files.

---

## What belongs in memory vs identity.md

| Content | Goes in |
|---------|---------|
| Persona, name, tone, output format | `agent/prompts/identity.md` (via file-control) |
| User preferences, workflow rules, schedule conventions | `agent/data/memories/topics/` (via memory.write) |
| Database IDs, API gotchas, known issues | `agent/data/memories/topics/` (via memory.write) |
