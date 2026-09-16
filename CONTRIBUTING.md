# Contributing

Every change to this repository — including a single-line fix — follows this
flow. No exceptions, because the exception is how a repo ends up with untracked
history again.

## 1. Open an issue first

Every change starts as a GitHub issue: `gh issue create` or the web UI. The
issue is the ticket; its number is the change's identity from branch name
through commit message to PR.

State what the change is and why in the issue body. "Fix bug" is not a ticket —
name the failure and its cause.

## 2. Branch from `develop`, named after the ticket

```bash
git checkout develop
git pull
git checkout -b <type>/<issue-number>-<short-slug>
```

`<type>` is one of `feat`, `fix`, `chore`, `docs`, `refactor`, `test`. Example:

```bash
git checkout -b fix/17-x-media-poll-timeout
```

Never commit directly to `develop` or `main`.

## 3. Commit referencing the ticket

```
<type>: <summary>

<body if needed>

Refs #<issue-number>
```

Use `Closes #<issue-number>` in the PR description (not the commit) so merging
the PR closes the issue automatically.

## 4. Open a PR into `develop`

```bash
gh pr create --base develop --title "<type>: <summary>" --body "Closes #<issue-number>"
```

CI must be green before merge: `pytest`, `ruff check`, `bandit -r src scripts`.
Squash-merge into `develop`.

## 5. Promote `develop` to `main`

Once `develop`'s tests are green and it's in a shippable state, open a PR from
`develop` into `main`. This is the only path onto `main` — never branch a
feature from `main`, never merge a feature branch into it directly.

```bash
gh pr create --base main --head develop --title "release: <date or version>"
```

Merge only when CI on that PR is green.

## Branch map

```
main       <- only ever receives a merge from develop, only when green
  ^
develop    <- every feature/fix branch merges here first
  ^
fix/17-…   <- one branch per ticket
feat/22-…
```

## Local checks before opening a PR

```bash
pytest
ruff check src tests scripts
bandit -q -r src scripts
```

All three must be clean. `pytest` also enforces the coverage floor via
`pyproject.toml`.
