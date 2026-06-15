# Change Review

**Branch:** main  
**Compared to:** `14550e1` (Ready for Teams)  
**Reviewed:** 2026-06-01  

## Summary

Four areas changed since the last commit: the project README was rewritten, `planning/PLAN.md` received several spec clarifications, `.claude/settings.json` had its enabled plugins swapped, and a new `independent-reviewer` plugin was added. The plan clarifications are well-reasoned and improve downstream agent clarity. However, two **High** issues in the README will break the quick-start flow for anyone following the documentation.

---

## High

### 1. README quick-start references scripts that don't exist

`README.md` instructs users to run `./scripts/start_mac.sh` and `.\scripts\start_windows.ps1`, but the `scripts/` directory has not been created yet (`ls scripts/` returns no such directory). Anyone following the README will hit an immediate dead end.

**Fix:** Either stub out the scripts directory with placeholder scripts, or replace the quick-start block with the raw `docker build` / `docker run` commands from the previous README version until the scripts are built.

---

### 2. README references `.env.example` which doesn't exist

The quick-start step `cp .env.example .env` will fail — there is no `.env.example` file in the repo. The previous README didn't include this step.

**Fix:** Create `.env.example` with the three documented variables (commented out, safe to commit), or remove the `cp` step and tell users to create `.env` manually.

---

## Medium

### 3. Three official plugins removed from settings — may block frontend work

`.claude/settings.json` dropped `frontend-design@claude-plugins-official`, `context7@claude-plugins-official`, and `playwright@claude-plugins-official` in favour of `independent-reviewer@zee-tools`. The frontend and E2E test phases haven't started yet; removing `frontend-design` and `playwright` now means they'll need to be re-enabled before that work begins.

**Fix:** Keep the official plugins enabled alongside the new one, or note in the project memory that they need to be re-added before the frontend phase.

---

### 4. `independent-reviewer` plugin directory is untracked

The `independent-reviewer/` directory is listed as untracked in git. If the repo is cloned fresh (e.g., by another agent or collaborator), the plugin won't exist and the hook will silently fail.

**Fix:** Commit `independent-reviewer/` to the repo.

---

## Low

### 5. README lost the project directory structure section

The rewrite removed the directory tree (`frontend/`, `backend/`, `planning/`, `test/`, etc.) that gave readers a quick orientation to the codebase layout. The new README is leaner but less informative for someone cloning the project for the first time.

**Suggestion:** Add a compact directory tree back, or accept the loss if brevity is preferred.

---

### 6. README lost the License reference

The previous README had a `## License` section linking to `LICENSE`. The file exists in the repo but is no longer referenced anywhere in the README.

**Fix:** Add a one-line `## License` section back, or leave as-is if the audience is internal only.

---

### 7. Trailing blank lines at end of PLAN.md

Two blank lines were appended to the end of `planning/PLAN.md` with no content. Minor cosmetic issue.

---

## Positive Notes

- **PLAN.md clarifications are high quality.** The additions — rolling history buffer, `init` SSE burst, daily change tracking, explicit mock response JSON, watchlist-or-held-position streaming scope, startup portfolio snapshot, 20-message chat cap — all reduce ambiguity for the agents building downstream components.
- **Fixed mock response** is well-specified and directly actionable for E2E test assertions.
- **Trade bar spec** improved significantly: fractional quantity support, watchlist validation behaviour, and inline error display are now explicit.
