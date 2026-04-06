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

**Always write the content to a `.scratch/` file using a file tool, then run or use it from the terminal.**

## Running Python code

### Step 1 — Write the script

Use a **file tool** to write the Python code to `.scratch/<descriptive-name>.py`.

- **First time:** use `create_file`.
- **Replacing an existing scratch file:** use `insert_edit_into_file`.

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

## Critical: replacing scratch files

`insert_edit_into_file` **will append** if it thinks the new content is an addition. This produces a script containing the previous script concatenated with the new one.

When using `insert_edit_into_file` to replace a scratch file:

1. **Provide only the new file content.**
2. **Do not use `...existing code...` comments.** The entire file is being replaced.
3. **Do not reference or include any part of the previous content.**

## Rules

- The `.scratch/` directory is gitignored — never commit it.
- Use descriptive filenames: `.scratch/write_config.py`, not `.scratch/tmp.py`.
- Clean up is optional — `.scratch/` files do no harm.
