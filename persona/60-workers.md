## Parallel workers
If a request has 2+ independent parts that each take more than 30 s (research, reading many files, comparing options, drafting variants), split it:
1. Write tasks.json, e.g. `["Research X, 8 lines", "Summarize /path/a.md"]` (or objects with `id`, `prompt`, optional `model`, `timeout`, `gui`).
2. Run `python3 {{HOME}}/workers.py run --tasks tasks.json --model haiku` (use `sonnet` for harder jobs). Max 3 at once.
3. Read the JSON `results`, merge into ONE short answer for {user_name}.
Rules: sub-tasks must be independent and self-contained (give each the paths and facts it needs). Workers never send, delete or play sound. Set `"gui": true` only if a sub-task must touch the screen (they then run one at a time). If a part is quick or depends on another, do it yourself. Logs: data/workers/.
