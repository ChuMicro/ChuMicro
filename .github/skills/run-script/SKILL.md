---
name: run-script
description: How to run multi-line Python scripts or create file content that would otherwise require heredocs. Use this skill when you need to execute Python code beyond a simple one-liner, or when you need to write structured content to a file via the terminal.
---

# Run Script

The agent terminal **cannot reliably handle** multi-line input. This includes:

- `python -c "..."` with quotes, newlines, or special characters
- `python -c '...'` with any internal single quotes
- Heredocs (`<< EOF ... EOF`) for creating files
- `echo` / `printf` / `cat` with embedded newlines

**Always write the content to a `.scratch/` file using your harness's file-write tool, then run or use it from the terminal.**

## Running Python code

### Step 1 — Write the script

Use your harness's file-write tool (Claude Code's `Write`, Copilot's `create_file`, Cursor's editor, etc.) to write the Python code to `.scratch/<descriptive-name>.py`. This overwrites any previous content.

### Step 2 — Run it

```
python .scratch/<descriptive-name>.py
```

For unbuffered output (when output appears missing or incomplete):

```
python -u .scratch/<descriptive-name>.py
```

### When `python -c` is acceptable

Only for **true one-liners** with no quotes inside, no newlines, and no special characters:

```
python -c "print(1 + 2)"
```

If you have to think about escaping, it is not a one-liner. Write a file.

## Creating file content (heredoc replacement)

When you need to create or overwrite a non-Python file (YAML, TOML, JSON, plain text) and a file tool can do it directly, **use the file tool**. The terminal is not needed.

When you must create file content *and* the file tool is unsuitable (e.g., the content is dynamic or computed), write a Python script to `.scratch/` that generates the file:

```python
# .scratch/gen_config.py
from pathlib import Path
Path("output.yml").write_text("key: value\n")
```

Then run it: `python .scratch/gen_config.py`

## Rules

- The `.scratch/` directory is gitignored — never commit it.
- Use descriptive filenames: `.scratch/write_config.py`, not `.scratch/tmp.py`.
- Clean up is optional — `.scratch/` files do no harm.
