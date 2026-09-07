# GitHub Upload Guide — ERP AI Agent
# ============================================================================

This document explains (1) the verified secret-safety status of this project,
(2) exactly how to publish it to GitHub safely, and (3) whether to use a
GitHub MCP server or plain git — and what credential GitHub requires for
either route.

---

## PART 1 — Secret-safety verification (already performed)

The following audit was performed on this project before publication:

| Check | Result |
|---|---|
| Was this ever a git repository? | **No** — `E:\Qoder\Ai Accountant\ERP` has no `.git` folder. Nothing has ever been committed, so **no secret can exist in any commit history**. |
| `.env` / `.env.*` ignored? | **Yes** — root `.gitignore` contains `.env`, `.env.*`, `!.env.example`; `frontend/.gitignore` contains `.env*`. |
| `.env.example` contains placeholders only? | **Yes** — verified line by line (`<your-model-studio-workspace-api-key>`, `change-me-to-a-random-64-char-hex-string`, etc.). No real key. |
| Hardcoded key scan of all source files | **Clean** — patterns scanned: `sk-ws-…` (Qwen), `eyJ…` (JWTs), `ghp_…`/`github_pat_…` (GitHub), `AIza…` (Google), service-role JWTs. No matches in project source. |
| Stray credential artifacts | One live Supabase session file (`E:\Qoder\session.json`, **outside** the repo) was found and **deleted**. |

> If you EVER committed a secret to any repository in the past: rotate/revoke
> it first (Qwen key in the Alibaba Cloud Model Studio console, Supabase keys
> in the Supabase dashboard, GitHub tokens in GitHub settings). Deleting the
> file alone does NOT remove it from git history.

---

## PART 2 — Publishing to GitHub, step by step

### Step 0 — Install git (one time)
This machine currently has **no git installed** (verified: `'git' is not recognized`).
Install it from <https://git-scm.com/download/win> (default options are fine —
this also installs **Git Credential Manager**, which securely stores your
GitHub login in Windows Credential Manager).

Verify in a NEW terminal:

```bat
git --version
```

### Step 1 — Initialize the repository

```bat
cd /d "E:\Qoder\Ai Accountant\ERP"
git init
git status
```

**Sanity-check the `git status` output before committing.** You should see:
- INCLUDED: `app/`, `frontend/` (source only — no `node_modules`, no `.next`), `scripts/`, `requirements.txt`, `Runapp.bat`, `*.md` docs, `.env.example`, `.gitignore`
- EXCLUDED (must NOT appear): `.env`, `venv/`, `env/`, `node_modules/`, `.next/`, `__pycache__/`, `backend.log`, `frontend.log`, `.pytest_cache/`

If `.env` or `venv/` appears, STOP — fix `.gitignore` first.

### Step 2 — First commit

```bat
git add .
git commit -m "Initial commit: AI-Native ERP with AI Accountant agent"
```

### Step 3 — Create the GitHub repository
1. Log in at <https://github.com> → click **+** (top-right) → **New repository**.
2. Name: e.g. `ai-native-erp`. Keep it **Private** while you finish, switch to Public later if desired.
3. Do **NOT** add a README / .gitignore / license on GitHub (that would conflict with your local commit).
4. Click **Create repository**.

### Step 4 — Connect and push

```bat
git branch -M main
git remote add origin https://github.com/<YOUR-USERNAME>/ai-native-erp.git
git push -u origin main
```

On the first push, a GitHub sign-in window appears — sign in with your
browser. Git Credential Manager stores the token securely in Windows
Credential Manager. **Never paste a token into a chat, file, or script.**

### Step 5 — After the first push (recommended)
- GitHub → repo → **Settings → Code security**: enable **Secret scanning** and **Push protection** (on public repos these are on by default; push protection will BLOCK pushes containing detected secrets).
- Verify in the GitHub web UI that `venv/`, `node_modules/`, `.env` are absent.
- Add topics/description, and a README if desired.

---

## PART 3 — How do you authenticate? (GitHub MCP vs plain git)

### What GitHub requires in both cases: a **Personal Access Token (PAT)**
GitHub no longer accepts account passwords for git over HTTPS. Everything
(MCP included) authenticates with a PAT:

**How to create one (do this yourself — never share the token value):**
1. GitHub → click your avatar → **Settings**.
2. Left sidebar → **Developer settings** (bottom of the list).
3. **Personal access tokens**:
   - **Fine-grained tokens** (recommended): *Generate new token* → token name → expiration (30–90 days) → **Repository access**: "Only select repositories" → your ERP repo → **Permissions → Repository permissions → Contents: Read and write** → Generate.
   - (Classic alternative: *Generate new token (classic)* → scope `repo` → Generate.)
4. Copy the token ONCE (it starts with `github_pat_…` or `ghp_…`). It is shown only once.

Treat the PAT as a password: minimum scope, set an expiry, revoke when done.

### Option A — plain git CLI (RECOMMENDED for this one-time push)
- **Simplest and safest.** Nothing to configure in tools; Credential Manager
  handles the token invisibly (Step 4 above). Your token never appears in any
  file, log, or chat.

### Option B — GitHub MCP server (useful for ongoing automation, not required)
A GitHub MCP server lets an AI coding assistant (e.g. Cline) call GitHub
APIs directly — create repos, push files, open PRs, read issues.

- **What it requires from you:** the same kind of GitHub PAT (fine-grained, `Contents: Read and write` on the target repo), pasted into the MCP server configuration in your editor's MCP settings — **not** into this chat, and never committed to the repo.
- **Where to configure:** your editor's MCP/MCP-servers settings file (the GitHub MCP server is published by GitHub as `github-mcp-server`; docs: <https://github.com/github/github-mcp-server>).
- **Verdict for this project:** you do NOT need MCP to upload. MCP makes sense later if you want the assistant to manage PRs/issues/releases continuously. For the initial publication, Option A is less risky (fewer places the token lives) and fully sufficient.

---

## PART 4 — Final pre-push checklist

- [ ] `git status` shows no `.env`, `venv/`, `env/`, `node_modules/`, `.next/`, `backend.log`, `frontend.log`
- [ ] `.env.example` present with placeholder values only
- [ ] `Ai Accountant.png` at the repo root — decide whether it belongs in the repo (branding asset) or should be removed/ignored
- [ ] No tokens, passwords, or session files anywhere in the tree
- [ ] Secret scanning + push protection enabled after publishing
- [ ] (If a secret ever HAD been committed anywhere) keys rotated BEFORE the repo went public

---

*Generated as part of the ERP AI Agent project audit. Keep this file in the
repo if you like (it contains no secrets) or delete it before pushing — your choice.*
