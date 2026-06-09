# Agent Operational & Onboarding Guide (AGENTS.md)

Welcome, AI Agent! This document defines the operational boundaries, design patterns, testing strategies, and collaborative conventions for the `aw-vision` repository.

As an agentic AI coder or human contributor, you must adhere strictly to these principles to maintain codebase sanity and ensure future AI and human developers can read, modify, and build upon your work efficiently.

---

## 1. Product Context & Core Business Value

The **`aw-vision`** system is an advanced, local-first visual and semantic indexing extension for **ActivityWatch**. It acts as an autonomous semantic memory engine, capturing desktop views, extracting layout texts, and enabling natural language query retrieval over the user's historical computer sessions.

### Key Workflows & Data Pipelines:
* **AFK-Aware Ingestion Loop**: The system monitors the user's active/idle status via `aw-server`'s AFK bucket. Screens are only captured when the user is active, protecting resource utilization and preventing redundant disk writes during AFK cycles.
* **Bulk Processor Pipeline**: Screenshots are batched and processed in moments of low system activity (CPU-aware bulk execution). The pipeline executes:
  1. **OCR Extraction**: Running local `glm-ocr:q8_0` via Ollama to pull exact text lines from the screen.
  2. **Vision Analysis**: Running local `gemma4:e2b-it-qat` vision model to generate high-level context descriptions, identify program/app types, and map unique, reusable tags.
  3. **Joint Embedding Generation**: Creating a 1024-dimensional semantic coordinate vector using `embeddinggemma` over a joint string representation: `Description: ... \n\nExtracted Screen Text: ...`.
  4. **LanceDB Commits**: Saving metadata, raw OCR strings, and coordinate vectors into local LanceDB.
* **Storage Retention Lifecycle**: To avoid infinite disk growth, a background daemon scans LanceDB hourly and unlinks raw/processed `.png` files older than 14 days (`max_screenshot_lifetime_days`). Crucially, **the database records, descriptions, OCR texts, and semantic coordinates are kept forever**, ensuring historical activity remains queryable even after physical images are purged.

---

## 2. Work Tracking, Git & PR Habits

### Project Key Work Tracking:
* All work is tracked and organized around specific client project IDs listed in `projects.json`.
* **Standard Project Keys**: Standard keys follow the format **`PRJ-YYYY-XXX`** (e.g., `PRJ-2026-042` or `PRJ-2026-089`).
* **Rule**: Before writing code, ensure your active development branch is named using the project key in uppercase as a prefix, followed by lowercase description tokens:
  ```bash
  PRJ-2026-042_setup_linting_and_precommit
  ```

### Git Commit Standards:
* **Bracketed Project Prefix**: Every git commit title and Pull Request title **MUST** start with the bracketed project identifier matching the work:
  ```text
  [PRJ-2026-042] Integrate python code linters and pre-commit hooks
  ```
* **No Conventional Tags**: Do **NOT** use conventional/semantic commit prefix tags (such as `feat:`, `fix:`, `chore:`, `refactor:`) in commit or PR titles.
* **Commit Description**: Write clear commit messages detailing the *why* (the problem/rationale) and the *how* (the implementation strategy).

### Pull Request & Review Flow:
* **Branch Isolation**: **Never** commit directly to `master`, `main`, or `stable` branches. Create separate topic branches.
* **Draft PR Policy**: AI Agents **MUST** open all Pull Requests in **DRAFT** state on GitHub.
* **Closed-Loop CI Checks**: Actively monitor the automated status checks on your branch. If any linter, formatter, or test check fails, push immediate corrective fixes.
* **Visual Evidence Mandate**: If your changes impact the user interface (e.g., the Vision tab UI in `aw-webui`), you **must** attach visual evidence (screenshots or screen recordings) to the PR description on GitHub demonstrating the validated flows. Do **NOT** commit screenshot files into the Git repository.
* **Human-Only Merge**: Merging is strictly restricted to human developers. AI Agents must never attempt to merge their own pull requests.
* **Empty Initiator Checklist**: Every PR description must end with an empty checklist for the human dev who initiated the agent, which they must check off to confirm they have personally reviewed the code before switching the PR out of Draft state.

---

## 3. Directory Organization & Python Architecture

The `aw-vision` repository is organized into a clean, lightweight Python package managed by **Poetry**:

```text
aw-vision/
│
├── .flake8                  # Python linting configuration
├── .pre-commit-config.yaml  # Git pre-commit hooks configuration
├── pyproject.toml           # Poetry dependencies and group settings
├── config.toml              # User configurations (retention, models, etc.)
├── projects.json            # Configured active projects definitions
│
├── aw_vision/               # Core source package
│   ├── __init__.py          # Package initialization
│   ├── config.py            # Configuration loader and parser
│   ├── db.py                # LanceDB database schemas and query migrations
│   ├── watcher.py           # AFK-aware desktop screenshot capture loop
│   ├── processor.py         # OCR & Vision processing and retention daemon
│   ├── server.py            # FastAPI web server and backend API
│   └── agent.py             # LangGraph ReAct agent & tools registry
│
└── tests/                   # Automated unit and integration tests
```

### Module Responsibilities:
1. **`config.py`**: Reads and structures parameters from `config.toml` (or env variables) such as Ollama hosts, model configurations, and storage directories.
2. **`db.py`**: Defines Arrow table schemas, handles database writes/retrievals, manages globally sorted history queries, and executes python-dict schema migrations.
3. **`watcher.py`**: Periodically queries `aw-server`'s AFK state. If active, triggers screen-grabbing CLI utilities (like `grim` or `spectacle`) and saves raw images.
4. **`processor.py`**: Gathers raw images, runs CPU-aware checks, executes OCR (`glm-ocr:q8_0`), performs LLM Vision analysis (`gemma4:e2b-it-qat`), computes embeddings (`embeddinggemma`), and handles the hourly retention purge.
5. **`server.py`**: Serves as the FastAPI gateway running on port `5666`. Exposes history streams, status checks, Q&A agent loops, and static screenshot assets.
6. **`agent.py`**: Implements the LangGraph-based ReAct agent, defining capabilities like `search_screenshots_semantic`, `get_active_projects`, `aggregate_project_hours`, `query_github`, and `query_jira`.

---

## 4. Designing for Future AI Generated Code

* **Decomposed File Footprints**: Keep individual source files under **300 lines (max 400 lines)**. Decomposed modules are easier to load, parse, and reason about inside LLM context windows, reducing token costs and code-generation errors.
* **Reuse High-Quality Libraries**: Do not reinvent the wheel. Before writing complex bespoke algorithms (e.g., custom markdown formatters or local task schedulers), search for a mature, well-tested Python library (like `pyyaml` or `apscheduler`) and add it to the Poetry workspace dependencies.

---

## 5. Local Development Environment

To set up and run the entire local development stack, execute the following actions:

### 1. Ingestion Core Daemon (aw-server)
Ensure the standard ActivityWatch core is running. It typically runs on port `5600` or `5666`:
```bash
/usr/bin/awatcher --port 5600
```

### 2. local Ollama Models
Ensure Ollama is running and has the required models pulled:
```bash
ollama run glm-ocr:q8_0
ollama run gemma4:e2b-it-qat
ollama run embeddinggemma
```

### 3. aw-vision Python Backend
Install the project dependencies and launch the FastAPI server on port `5666`:
```bash
cd aw-vision
poetry install
poetry run uvicorn aw_vision.server:app --host 127.0.0.1 --port 5666 --reload
```

### 4. Vue Web UI Dashboard
Navigate to your active `aw-webui` directory and launch the Vue dev server on port `27180`:
```bash
cd activitywatch/aw-server/aw-webui
npm run serve
```
Open `http://localhost:27180/#/vision` to inspect the live premium dashboard!

---

## 6. Privacy, Security & Data Sovereignty

* **100% Local Processing Guarantee**: Because screenshots contain sensitive, high-fidelity user information (such as personal emails, banking details, passwords, and source code), **`aw-vision` processes everything on-device**. No screenshots, OCR texts, or metadata are ever transmitted to any remote cloud API. All deep learning models run locally via Ollama.
* **Strict Disk Purges**: To prevent unauthorized physical access to old screenshots on lost or compromised hardware, screenshot image files are permanently wiped from the host disk after 14 days, reducing the static physical security exposure.

---

## 7. Automated Pre-Commit Tooling & Closed-Loop Cycle

This repository enforces static code quality and safety rules before any git commit is written.

### Configured Pre-Commit Checks:
1. **Talisman Secret Scanner**: Automatically blocks commits containing high-entropy strings, API keys, private certificates, or passwords.
2. **Agent Tracking Blocker**: Prevents development helper files (like `task.md`, `implementation_plan.md`, `walkthrough.md`, temporary `scratch_*` files, or temporary tests) from being committed.
3. **Black & Isort**: Enforces clean styling, PEP8 compliance, and structured imports **exclusively on newly created files**, bypassing legacy code styling.
4. **Flake8**: Runs standard linting checks across all modified Python code.
5. **Local Paths References**: Blocks any hardcoded absolute home directories (like `/home/<user>/` or `/Users/<user>/`), forcing the use of relative and portable configurations.
6. **Project Prefix Checker**: Confirms that commit messages begin with a standard bracketed project reference (e.g., `[PRJ-2026-042] description`).

### Setup pre-commit locally:
Ensure `pre-commit` is installed and registered in your local Git hooks:
```bash
poetry run pre-commit install --hook-type pre-commit --hook-type commit-msg
```

### Manual execution:
You can manually run checks on staged files or across the whole repository:
```bash
# Run on all files
poetry run pre-commit run --all-files

# Run on specific files
poetry run pre-commit run --files aw_vision/db.py
```

### Hook Skip Policy:
* **For AI Agents (Strictly Blocked)**: AI agents **MUST** pass all pre-commit hooks cleanly. Agents are forbidden from skipping hooks.
* **For Human Developers**: If saving a temporary local work-in-progress, humans may skip checks by setting `SKIP_PRE_COMMIT=1` or running `git commit -m "..." --no-verify`.

---

## 8. Visual Validation & Verification (V&V) Guidelines

Before submitting any frontend changes (such as updates to `Vision.vue`), you must systematically verify visual rendering and interface usability under different states:

### State 1: Happy Path (Populated Dashboard)
* Ensure all status cards show "ACTIVE" (green pulse dots).
* Confirm historical screenshot cards render high-quality images and show complete layouts.
* Click the raw OCR text button on a card and ensure the collapsible monospaced panel expands smoothly, allowing raw text copy-paste.
* Enter a query in the Chat Agent box and ensure the ReAct loops, tool results, and markdown summaries render correctly.

### State 2: Unhappy Path (Archived Images)
* Verify that historical records older than 14 days (where `image_path` is null) render gracefully using the glassmorphic archived placeholder.
* Confirm that the metadata card shows the archive cabinet icon and the explicit message: `"Archived Metadata (Screenshot purged to save space)"`.
* Ensure that the collapsible monospaced raw OCR preview panel still expands and functions perfectly for archived rows.

### State 3: Backend Offline
* Shutdown the `server.py` FastAPI backend.
* Ensure the top alert banner displays immediately: `"aw-vision Backend is Offline"`, presenting clear terminal instructions on how to start the FastAPI server.
* Confirm that clicking "Retry Connection" executes a clean reconnection attempt and hides the banner once the backend is brought back online.
