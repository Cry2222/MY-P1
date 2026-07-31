# Running MY-P1 as an Acme target repository

[Acme Software Factory](https://github.com/eimg/acme-software-factory) is a
local-first development environment, not a runtime your bot sits on top of.
Its services help you *build* software; MY-P1 is the software being built.

In Acme's own terms, MY-P1 occupies the same slot as `acme-todo`: a target
application that Helix operates on. Nothing in `myp1/` imports anything from
the suite, and the bot runs perfectly well with no Acme service running.

## The suite

| Service | Port | Role |
|---|---:|---|
| Acme Identity | 8316 | sessions and scoped service tokens |
| Primer | 8317 | knowledge retrieval with citations |
| Prelude | 8318 | project inception, bootstrap artifacts |
| Helix | 8319 | agent workflow and PR control plane |
| Acme Issues | 8320 | work items, PR evidence, human merge gate |
| Acme Projects | 8321 | feature exploration board |
| Acme Observability | 8322 | optional read-only operational view |
| Acme Todo | 8331 | their disposable example target |

Helix is deliberately **not** started by the suite launcher, because it
resolves its workspace and configuration from whichever repository it is
pointed at. That is the hook MY-P1 plugs into.

## Setup

Requires Node.js 22.19+ (24 LTS works), npm, `curl` and `pgrep`.

```bash
git clone --recurse-submodules https://github.com/eimg/acme-software-factory.git
cd acme-software-factory

for project in acme-identity primer prelude helix acme-issues acme-projects acme-obs acme-todo; do
  npm --prefix "$project" install
done
```

Start the suite. It brings services up in dependency order and waits on each
health check:

```bash
./start-acme.sh                      # interactive: choose auth mode
ACME_AUTH_MODE=off ./start-acme.sh   # no sign-in, development admin
ACME_AUTH_MODE=local ./start-acme.sh # Identity sign-in and token enforcement
```

Before the first `local`-mode run, provision the scoped machine credentials:

```bash
./start-acme.sh --provision-auth
```

That writes tokens into gitignored local env files and rotates every suite
service token, so restart the consumers afterwards. `Ctrl-C` stops everything
the launcher started.

## Pointing Helix at MY-P1

Helix runs from inside the target repository, not from the suite root:

```bash
cd /path/to/MY-P1
helix serve
```

Helix is language-agnostic about its target — it operates on the repository's
files and git history, so a Python target is no different from their Node one.
The Python toolchain stays entirely on MY-P1's side:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## The workflow

Acme's two paths, applied to this repo:

**Existing project** (what MY-P1 is now):

```
Acme Projects (8321)     explore a feature — "add an RSI strategy"
        │                 a ready card creates a NON-triggering issue
        ▼
Acme Issues (8320)       a human starts implementation from the issue
        │
        ▼
Helix (8319)             runs inside MY-P1, implements, opens a PR
        │
        ▼
Acme Issues              review evidence lands back here
        │
        ▼
human merge              always a person, never automation
```

Projects never calls Helix directly. The handoff is deliberate, and the merge
is a human decision — that boundary is the point of the design, not an
incomplete feature.

**New project**: Primer evidence → Prelude inception → exported bootstrap →
Helix initializes a fresh workspace. Relevant if you spin off a second bot
rather than extending this one.

## Git discipline

The suite root pins each product as a submodule at an exact commit. If you
work inside the suite:

- Commit and push inside the child repository first.
- Only then commit the root's updated gitlink, as a separate commit.
- Never track `workspace/`, secrets, env files, or runtime databases.

MY-P1 is not a submodule of the suite — it is an independent repository Helix
targets. Its own history is entirely its own.

## What this does and does not give you

It gives you a structured pipeline for *developing* MY-P1: exploration,
tracked work items, agent implementation, review evidence, and a human merge
gate.

It does not give you deployment, uptime, or monitoring for a running bot. The
suite is local-first and expects to be stopped with `Ctrl-C`. A bot trading
24/7 needs its own answer to that — a systemd unit, a container, a VPS — and
that is outside what Acme covers. Acme Observability (8322) watches suite
workflow and source health, not your open positions; MY-P1's own `/status`
and journal are what tell you about those.
