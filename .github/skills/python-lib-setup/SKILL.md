---
name: python-lib-setup
description: Set up Python project for PyPI publishing or private GitHub distribution with pyproject.toml, src layout, and optional build scripts. Use when creating a new Python package, setting up for PyPI distribution, initializing a Python library project, or setting up a private library distributed via GitHub.
---

# Python PyPI Project Setup Pattern

This skill helps you set up a Python project for PyPI publishing following modern best practices with pyproject.toml, src layout, and standardized build/publish scripts.

## When to Use This Skill

Use this skill when:
- Starting a new Python package for PyPI distribution
- Setting up a private Python library distributed via GitHub
- You want to use modern pyproject.toml-based configuration
- You need a standardized src/ layout with explicit package discovery
- You want automated build and publish scripts (PyPI path)

## What This Skill Creates

1. **`pyproject.toml`** - Modern Python project configuration
2. **`src/{package_name}/`** - Source layout with package structure
3. **`.gitignore`** - Comprehensive Python gitignore
4. **`dev-requirements.txt`** - Development dependencies (includes build/twine for PyPI only)
5. **`build-publish.sh`** - Automated build and publish script (PyPI only)
6. **`LICENSE`** - License file (Proprietary, MIT, or O'Saasy)
7. **`README.md`** - Basic project documentation

## Step 1: Gather Project Information

**IMPORTANT**: Before creating files, ask the user these questions:

1. **"What is your project name?"** (e.g., "pg-podcast-toolkit", "mypackage")
   - Use this to derive:
     - PyPI package name: `{project-name}` (with hyphens, e.g., `pg-podcast-toolkit`)
     - Python package name: `{package_name}` (with underscores, e.g., `pg_podcast_toolkit`)
     - Module directory: `src/{package_name}/`

2. **"What is the project description?"** (brief one-line description for PyPI)

3. **"What is your name?"** (for author field)

4. **"What is your email?"** (for author field — **only ask this if the answer to question 6 is `GitHub private`**. PyPI metadata and public GitHub repos are publicly browsable, so embedding the author email there exposes it to scrapers. For those, omit the email entirely; capture name only.)

5. **"What is your GitHub username?"** (for project URLs)

6. **"How will this package be distributed?"** (one of three; this drives both the tooling AND whether the author email is embedded)
   - **PyPI** — Public package registry. Includes build/twine tooling and a publish script. **Email omitted from `authors` and README** (PyPI metadata is public).
   - **GitHub public** — Public repo, installed via `git+https://` URL. No PyPI artifacts. **Email omitted from `authors` and README** (repo is publicly browsable).
   - **GitHub private** — Private repo, installed via `git+https://${CR_PAT}@...` URL. No PyPI artifacts. **Email included** (only readers with repo access see it).

7. **"What license do you want to use?"** (options: Proprietary, MIT, O'Saasy)
   - **Proprietary**: All rights reserved, no open source distribution
   - **MIT**: Permissive open source, allows commercial use
   - **O'Saasy**: Modified MIT that reserves commercial SaaS rights for the copyright holder (see https://osaasy.dev/)

8. **"What Python version should be the minimum requirement?"** (default: 3.8)

9. **"What are your initial dependencies?"** (optional - comma-separated list, can be empty)

10. **"What keywords describe your project?"** (optional - for PyPI searchability)

## Step 2: Create Directory Structure

Create these directories if they don't exist:
```
{project_root}/
├── src/
│   └── {package_name}/
└── (other files at root)
```

## Step 3: Create pyproject.toml

Create `pyproject.toml` with the following structure, **substituting project-specific values**:

```toml
[project]
name = "{project-name}"
version = "0.0.1"
authors = [
  { name="{author_name}", email="{author_email}" },   # GitHub PRIVATE only — see note below
]
description = "{project_description}"
keywords = [{keywords_list}]
readme = "README.md"
requires-python = ">={python_version}"
license = {text = "{license_name} License"}
classifiers = [
    "Programming Language :: Python :: 3",
    "{license_classifier}",
    "Operating System :: OS Independent",
]
dependencies = [
  {dependencies_list}
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{package_name}"]

[project.urls]
Homepage = "https://github.com/{github_username}/{project-name}"
Issues = "https://github.com/{github_username}/{project-name}/issues"
```

**CRITICAL Substitutions**:
- `{project-name}` → project name with hyphens (e.g., `pg-podcast-toolkit`)
- `{package_name}` → package name with underscores (e.g., `pg_podcast_toolkit`)
- `{author_name}` → author's name
- `{author_email}` → author's email — **only when distribution is `GitHub private`**. For `PyPI` and `GitHub public`, drop the `, email="..."` half and write the entry as `{ name="{author_name}" }` (PEP 621 allows the `email` field to be omitted; it must not be left blank or set to a placeholder, just omit the key).
- `{project_description}` → one-line description
- `{keywords_list}` → comma-separated quoted keywords (e.g., `"podcasting", "rss", "parser"`) or empty
- `{python_version}` → minimum Python version (e.g., `3.8`)
- `{license_name}` → license name (e.g., `MIT`, `O'Saasy`, `Proprietary - All Rights Reserved`)
- `{license_classifier}` → Full classifier string:
  - MIT: `License :: OSI Approved :: MIT License`
  - O'Saasy: `License :: Other/Proprietary License`
  - Proprietary: `License :: Other/Proprietary License`
- `{dependencies_list}` → comma-separated quoted dependencies (e.g., `'requests', 'beautifulsoup4'`) or empty
- `{github_username}` → GitHub username

**License Classifiers Mapping**:
- Proprietary → `Other/Proprietary License`
- MIT → `MIT License`
- O'Saasy → `Other/Proprietary License` (modified MIT with SaaS restrictions)

**License Text Handling**:
- **Proprietary**: Use `license = {text = "Proprietary - All Rights Reserved"}`
- **MIT**: Use `license = {text = "MIT License"}`
- **O'Saasy**: Use `license = {text = "O'Saasy License"}` and create LICENSE file from https://osaasy.dev/

## Step 4: Create Comprehensive .gitignore

Create `.gitignore` with comprehensive Python patterns:

```gitignore
# Byte-compiled / optimized / DLL files
__pycache__/
*.py[cod]
*$py.class

# C extensions
*.so

# Distribution / packaging
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
pip-wheel-metadata/
share/python-wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# PyInstaller
*.manifest
*.spec

# Unit test / coverage reports
htmlcov/
.tox/
.nox/
.coverage
.coverage.*
.cache
nosetests.xml
coverage.xml
*.cover
*.py,cover
.hypothesis/
.pytest_cache/

# Translations
*.mo
*.pot

# Django stuff:
*.log
local_settings.py
db.sqlite3
db.sqlite3-journal

# Flask stuff:
instance/
.webassets-cache

# Scrapy stuff:
.scrapy

# Sphinx documentation
docs/_build/

# PyBuilder
target/

# Jupyter Notebook
.ipynb_checkpoints

# IPython
profile_default/
ipython_config.py

# pyenv
.python-version

# pipenv
Pipfile.lock

# PEP 582
__pypackages__/

# Celery stuff
celerybeat-schedule
celerybeat.pid

# SageMath parsed files
*.sage.py

# Environments
.env
.venv
env/
venv/
ENV/
env.bak/
venv.bak/
bin/
include/
pyvenv.cfg

# Spyder project settings
.spyderproject
.spyproject

# Rope project settings
.ropeproject

# mkdocs documentation
/site

# mypy
.mypy_cache/
.dmypy.json
dmypy.json

# Pyre type checker
.pyre/

# IDEs
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store
```

## Step 5: Create dev-requirements.txt

Create `dev-requirements.txt` with development dependencies.

**If distribution is PyPI:**
```
build
twine
pytest
black
mypy
```

**If distribution is GitHub:**
```
pytest
black
mypy
```

These are the tools needed to develop (and for PyPI, build/publish) the package. Add other dev tools as needed (isort, pytest-cov, etc.).

## Step 6: Create build-publish.sh (PyPI only)

**If distribution is GitHub, skip this step entirely.**

**If distribution is PyPI**, create `build-publish.sh` with venv activation and build/publish commands:

```bash
#!/bin/bash
# Build and publish package to PyPI
# Activates virtual environment before running

# Activate virtual environment
source bin/activate

# Clean previous builds
rm -rf dist/*

# Build package
python -m build

# Upload to PyPI
python -m twine upload dist/*
```

**Note**: This script follows the convention that the virtual environment is in `bin/` at the project root.

## Step 7: Create Package Structure

Create the basic package structure:

1. **`src/{package_name}/__init__.py`** - Package initialization file:
   ```python
   """
   {project_description}
   """

   __version__ = "0.0.1"
   ```

2. **If this is a library package**, you can add:
   ```python
   # Export main classes/functions here for easier imports
   # from .module import ClassName, function_name
   # __all__ = ['ClassName', 'function_name']
   ```

## Step 8: Create LICENSE File

Create the appropriate LICENSE file based on the user's license choice:

### For MIT License:
```
MIT License

Copyright (c) {year} {author_name}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### For O'Saasy License:
Download the license text from https://osaasy.dev/ and replace `<Year>` and `<Copyright Holder>` with appropriate values:
```
O'Saasy License

Copyright (c) {year} {author_name}

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to use, copy,
modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
and to permit persons to whom the Software is furnished to do so, subject to
the following conditions:

1. The above copyright notice and this permission notice shall be included in
   all copies or substantial portions of the Software.

2. The licensee may not use the Software to directly compete with the original
   Licensor by offering it to third parties as a hosted, managed, or
   Software-as-a-Service (SaaS) product or cloud service.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### For Proprietary License:
```
Proprietary License

Copyright (c) {year} {author_name}. All rights reserved.

This software and associated documentation files (the "Software") are proprietary
and confidential. Unauthorized copying, modification, distribution, or use of
this Software, via any medium, is strictly prohibited.

The Software is provided for use only by authorized licensees under the terms
of a separate written agreement with the copyright holder.
```

## Step 9: Create README.md

Create `README.md` with basic project documentation. The Installation and Development sections vary by distribution type.

**If distribution is PyPI:**

```markdown
# {project-name}

{project_description}

## Installation

```bash
pip install {project-name}
```

## Usage

```python
import {package_name}

# Add usage examples here
```

## Development

### Setup

```bash
# Create virtual environment
python -m venv .

# Activate virtual environment
source bin/activate  # On Windows: bin\Scripts\activate

# Install dependencies
pip install -r dev-requirements.txt
pip install -e .
```

### Building and Publishing

```bash
# Make sure you have PyPI credentials configured
# Build and publish to PyPI
./build-publish.sh
```

## License

{license_name}

## Author

{author_name}
```

> The Author line above is `{author_name}` only — PyPI READMEs render publicly on
> pypi.org, so the email is intentionally omitted. (Same rule as the `pyproject.toml`
> `authors` block in Step 3.)

**If distribution is GitHub:**

```markdown
# {project-name}

{project_description}

## Installation

### Public repo
```bash
pip install git+https://github.com/{github_username}/{project-name}.git
```

### Private repo (requires `CR_PAT` environment variable)
```bash
pip install git+https://${CR_PAT}@github.com/{github_username}/{project-name}.git
```

### As a dependency in pyproject.toml
```toml
dependencies = [
    "{project-name} @ git+https://{env:CR_PAT}@github.com/{github_username}/{project-name}.git",
]
```

### As a dependency in requirements.txt
```
{project-name} @ git+https://${CR_PAT}@github.com/{github_username}/{project-name}.git
```

## Usage

```python
import {package_name}

# Add usage examples here
```

## Development

### Setup

```bash
# Create virtual environment
python -m venv .

# Activate virtual environment
source bin/activate  # On Windows: bin\Scripts\activate

# Install dependencies
pip install -r dev-requirements.txt
pip install -e .
```

## License

{license_name}

## Author

{author_name} ({author_email})
```

> **Author line rule for the GitHub template above:**
> - **GitHub private** → keep as shown: `{author_name} ({author_email})`.
> - **GitHub public** → drop the email parens; write `{author_name}` only. Public
>   GitHub READMEs are scraped, and the email was never collected in this branch
>   anyway (see Step 1, question 4).

## Step 10: Make Script Executable (PyPI only)

**If distribution is GitHub, skip this step.**

**If distribution is PyPI**, run:
```bash
chmod +x build-publish.sh
```

## Step 11: Create Initial Git Repository (if needed)

If not already a git repository:
```bash
git init
git add .
git commit -m "Initial project structure for PyPI package"
```

## Step 12: Document Next Steps

Inform the user of the next steps.

**If distribution is PyPI:**

1. **Install development dependencies**:
   ```bash
   source bin/activate
   pip install -r dev-requirements.txt
   ```

2. **Install package in development mode**:
   ```bash
   pip install -e .
   ```

3. **Write your code** in `src/{package_name}/`

4. **Update version** in `pyproject.toml` before publishing

5. **Configure PyPI credentials** (one-time setup):
   ```bash
   # Create ~/.pypirc with your PyPI token
   ```

6. **Build and publish**:
   ```bash
   ./build-publish.sh
   ```

**If distribution is GitHub:**

1. **Install development dependencies**:
   ```bash
   source bin/activate
   pip install -r dev-requirements.txt
   ```

2. **Install package in development mode**:
   ```bash
   pip install -e .
   ```

3. **Write your code** in `src/{package_name}/`

4. **Update version** in `pyproject.toml` before each release

5. **Referencing this library from other projects**:
   - In `pyproject.toml`:
     ```toml
     dependencies = [
         "{project-name} @ git+https://{env:CR_PAT}@github.com/{github_username}/{project-name}.git",
     ]
     ```
   - In `requirements.txt`:
     ```
     {project-name} @ git+https://${CR_PAT}@github.com/{github_username}/{project-name}.git
     ```

## Design Principles

This pattern follows these principles:

1. **Modern pyproject.toml** - No setup.py needed, all config in pyproject.toml
2. **Src Layout** - Source code in `src/` directory for better separation
3. **Explicit Package Discovery** - Using hatchling with explicit package paths
4. **Comprehensive .gitignore** - Covers all common Python artifacts
5. **Virtual Environment Convention** - Uses `bin/` at project root
6. **Automated Publishing** - Simple script for build and publish
7. **Best Practices** - Follows PEP 517/518 and modern Python packaging standards

## Example Usage in Claude Code

### PyPI Distribution Example

User: "Set up a Python package for PyPI"
Claude: "What is your project name?"
User: "awesome-lib"
Claude: [Asks remaining questions, user selects **PyPI** for distribution]
Claude:
1. Creates src/awesome_lib/ directory structure
2. Creates pyproject.toml with project metadata
3. Creates comprehensive .gitignore
4. Creates dev-requirements.txt with build tools and dev dependencies
5. Creates build-publish.sh script
6. Creates LICENSE file (based on user's choice)
7. Creates src/awesome_lib/__init__.py
8. Creates README.md with PyPI install instructions
9. Makes script executable
10. Documents next steps for the user

### GitHub Distribution Example

User: "Set up a private Python library"
Claude: "What is your project name?"
User: "arcana-models"
Claude: [Asks remaining questions, user selects **GitHub** for distribution]
Claude:
1. Creates src/arcana_models/ directory structure
2. Creates pyproject.toml with project metadata
3. Creates comprehensive .gitignore
4. Creates dev-requirements.txt (no build/twine)
5. Creates LICENSE file (based on user's choice)
6. Creates src/arcana_models/__init__.py
7. Creates README.md with git+https:// install instructions and dependency reference patterns
8. Documents next steps for the user (no PyPI credentials or publish script)
