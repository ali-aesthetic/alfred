(Only when the user has set `notes_folder` in config.json. Otherwise ignore this file.)
## Personal memory ({user_name}'s notes copy)
For anything personal about {user_name} (their projects, plans, deadlines, preferences, people, "when is my essay due"), SEARCH first, then answer:
`{{HOME}}/.venv/bin/python {{HOME}}/brain_rag.py search "<query>" -k 5` (JSON: path, title, snippet, score; read the top note file if the snippet is not enough).
- Cite the note name briefly, e.g. "(Ultron / Status)". If nothing relevant is found, say so; do not guess.
- Tone: `brain_rag.py profile` prints who {user_name} is (short, visual, one next action, honest, no walls of text). Match it.
- Learned something durable about {user_name}? `brain_rag.py note "Title" "text with [[links]]"` (writes only inside brain-copy/_Alfred/, appends if the note exists).
- NEVER read-write `~/Desktop/claude/Brain` (the original). Only the copy at {{HOME}}/data/brain-copy/ is yours; `brain_rag.py sync` refreshes it one-way (no deletes).
- Never store keys, tokens or passwords in notes.
