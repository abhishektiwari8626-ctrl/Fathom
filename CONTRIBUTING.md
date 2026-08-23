# How We Work with Git — Read This Before You Push Anything

> **Golden Rule: NEVER push directly to `main`. Ever. Seriously.**

---

## Why?

`main` is what we will demo, deploy, and show to others. If someone pushes broken code there, everyone's code breaks. So we use **branches** — think of them as your own personal copy of the project where you can mess around freely without breaking anyone else's work.

---

## Step-by-Step: How to Do Your Work

### 1. First time only — Clone the repo

```bash
git clone https://github.com/PrashleshPratapSingh/Fathom.git
cd Fathom
```

### 2. Before starting any work — Pull the latest code

```bash
git checkout main
git pull origin main
```

This makes sure you're starting from the latest version, not some old one.

### 3. Create your own branch

```bash
git checkout -b feat/your-name/what-you-are-working-on
```

**Use this naming format:**

| Who        | Branch Name Example                        |
| ---------- | ------------------------------------------ |
| Prashlesh  | `feat/prashlesh/schema-and-ingestion`      |
| Abhishek   | `feat/abhishek/evaluation-engine`          |
| Rushikesh  | `feat/rushikesh/graph-api-and-rewind`      |
| Swastika   | `feat/swastika/react-flow-ui`              |

If you're fixing a bug later, use `fix/` instead of `feat/`:
```bash
git checkout -b fix/abhishek/drift-threshold-bug
```

### 4. Do your work, save your progress with commits

After you've written some code and it's working:

```bash
git add .
git commit -m "short message about what you did"
```

**Good commit messages:**
- ✅ `"added trace_spans table with parent-child FK"`
- ✅ `"built Phase 2 semantic drift evaluator"`
- ✅ `"added node inspector side panel"`

**Bad commit messages:**
- ❌ `"updates"`
- ❌ `"fixed stuff"`
- ❌ `"asdfgh"`

Commit often. Small commits are better than one giant commit at the end.

### 5. Push your branch to GitHub

```bash
git push origin feat/your-name/what-you-are-working-on
```

This puts your branch on GitHub but does NOT touch `main`. Your code is safe on your branch and nobody else is affected.

### 6. When your work is done — Create a Pull Request (PR)

1. Go to the repo on GitHub
2. You'll see a banner saying **"your-branch had recent pushes — Compare & pull request"** → Click it
3. Fill in:
   - **Title:** What you built (e.g., "Evaluation Engine - All 3 Phases")
   - **Description:** Briefly explain what your code does and how to test it
4. **Set the base branch to `main`**
5. **Add at least 1 reviewer** (tag Prashlesh or anyone else on the team)
6. Click **"Create pull request"**

### 7. Wait for review

- Someone will look at your code
- They might leave comments like "change this variable name" or "this might break if X happens"
- Fix those comments, commit again, and push — the PR updates automatically
- Once approved → **Merge it** 🎉

---

## Quick Cheat Sheet

```
I want to...                         Command
─────────────────────────────────    ──────────────────────────────────────
Start fresh from latest main         git checkout main && git pull
Create my branch                     git checkout -b feat/myname/feature
Save my work                         git add . && git commit -m "message"
Push to GitHub                       git push origin feat/myname/feature
Update my branch with latest main    git checkout main && git pull && git checkout feat/myname/feature && git merge main
Delete a branch after merging        git branch -d feat/myname/feature
```

---

## What If I Get a Merge Conflict?

This happens when two people edited the same file in the same place. Don't panic.

1. Git will tell you which files have conflicts
2. Open those files — you'll see something like:
   ```
   <<<<<<< HEAD
   your code
   =======
   their code
   >>>>>>> main
   ```
3. Decide which version to keep (or combine both), delete the `<<<` `===` `>>>` markers
4. Save, then:
   ```bash
   git add .
   git commit -m "resolved merge conflict in filename"
   ```

If you're stuck, ask in the group chat. Don't just delete someone else's code.

---

## Rules Summary

| Rule | Why |
|------|-----|
| ❌ Don't push to `main` directly | Keeps main stable for everyone |
| ✅ Always work on your own branch | Your experiments don't break others' code |
| ✅ Pull latest `main` before creating a branch | Avoids outdated code and conflicts |
| ✅ Write clear commit messages | So we know what changed without reading every line |
| ✅ Create a PR when done | Someone reviews your code before it goes to main |
| ✅ Get at least 1 review before merging | Catches bugs early, keeps quality high |
| ❌ Don't edit shared files without telling Prashlesh | `enums.py`, `schemas.py`, `models.py` affect everyone |

---

## Still confused?

Message in the team group. No dumb questions. Better to ask than to push broken code to `main` and have everyone debugging at 2 AM. 🙂
