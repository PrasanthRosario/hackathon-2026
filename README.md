# Off-frame

**A previz co-pilot for physical sets.** A director describes a shot in plain
language, the set builds live in the browser, and the camera move is checked
with real physics — PhysX collisions and an RTX render on the same USD stage —
*before* anything gets built for real.

`OpenUSD` · `NVIDIA Omniverse Kit` · `PhysX` · `React` · `FastAPI` · Two LLM agents

Built for **Presidio Hackathon 2026**.

## Why

Physical sets are expensive to get wrong. A render shows what looks right, not
what's physically wrong — a camera move that clips through a wall, or a shot
that strays off the built set into "nothing," is usually found on set, paid
for twice. Off-frame moves that discovery onto a laptop, days before the
build, by running the same physics engine that would catch it on the day.

## How it works

1. **Talk** — describe the shot in the chat panel, no 3D tool required.
2. **Generate** — the agent emits a typed `scene_config`, which the backend
   turns into a real `.usda` stage; the browser shows the generated USD file
   and the cameras it contains (there's no live 3D preview in the browser
   today — that's the biggest gap between this build and the target
   architecture in `docs/architecture.html`, see Current status below).
3. **Verify** — the stage is checked in NVIDIA Omniverse Kit: PhysX casts
   frustum-corner rays against real collision meshes to flag off-set shots
   and rig/camera collisions, and RTX renders the move for review — results
   land back in the browser as frames/video plus a flag list.
4. **Fix and re-verify** — a validation agent reads the flags and proposes
   typed, testable fixes (never free text). Nothing is applied until the
   director approves; once applied, the stage is rebuilt and the identical
   checks run again, so the before/after flag count is real, not asserted.

## Architecture

| Component | Role |
|---|---|
| **Web app** | React. Chat panel, generated-USD/camera panel, and the render/validate review panel side by side. No live 3D preview yet — see Current status. |
| **Backend orchestrator** | FastAPI (`/chat`, `/generate-usd`, `/render`, `/propose-fix`). The only component that talks to everything else — holds the conversation thread, owns the scene, authors USD with `pxr.Usd`, and keys every stage/render/report to one `scene_id`. |
| **Set Design Agent** | Turns a sentence into a scene graph. Asks clarifying questions first; only emits the typed `scene_config` once the brief is complete — never free text the renderer has to parse. |
| **Omniverse Kit runtime** | One USD stage serves the scene graph, physics, and the renderer — nothing is exported between tools, so the thing being validated is the thing being shown. |
| **Validation Agent** | Reads the render/physics flags and writes a plain-language report: summary, issues, and typed fixes constrained to what the simulator can actually re-check. Read-only until the director says apply. |
| **Fix & re-verify loop** | Applies a fix by mutating `scene_config`, regenerates USD, and re-runs the same checks — a fix that fails to clear its flag is reported unresolved, not silently dropped. |

**Design intent:** two boundaries carry this architecture. The schema
boundary — `scene_config` is the only description of the set, so the USD
stage and the validator can never disagree about what's being built (this is
also meant to extend to a live browser preview — not yet built, see Current
status). And the process boundary at the GPU host — reasoning happens
outside it, physics happens inside it, and only files cross.

For the full interactive system diagram (data payloads, per-flow walkthroughs,
go-to-market), open [docs/architecture.html](docs/architecture.html) in a
browser. For an as-built technical audit — what's actually wired up today
versus still a placeholder — see [ARCHITECTURE.md](ARCHITECTURE.md).

## Repo structure

```
backend/          FastAPI orchestrator + chat/set-design/fix agents (backend/src/modules/offset_agent)
ui/                React web app
kit_render_worker.py   Subprocess invoked by the backend to render/validate a .usda in Kit
scenes/            Sample .usda stages, Isaac Sim scripts, and the Kit bridge extension
docs/              Interactive architecture diagram (docs/architecture.html)
scripts/           Local dev helpers (scripts/dev.sh, scripts/backend.sh)
legacy/            Earlier prototype (frustum/occlusion math), not on the live path — see ARCHITECTURE.md
```

*Note: the codebase still uses "Offset" as an internal codename in places
(the `offset_agent` module, `ui`'s package name) — that's the same project,
pre-rename.*

## Getting started

**Backend** (requires [uv](https://docs.astral.sh/uv/)):
```bash
cp backend/.env.example backend/.env   # add your OPENROUTER_API_KEY
make backend-dev                       # uv run --extra usd uvicorn ... --reload
```

**UI**:
```bash
cd ui
npm install
npm run dev
```

**Or with Docker Compose** (backend + Postgres + UI):
```bash
make compose-up
```

Run `make help` for all available targets (tests, lint, Docker build/teardown).

## Current status

Chat → USD generation → Kit render/validate → fix report → apply & re-verify
is wired end-to-end and verified live for coverage-flag fixes (e.g. a flagged
shot resolved by a lens change, confirmed 1 → 0 on re-render). A few things
are still open — see [ARCHITECTURE.md](ARCHITECTURE.md) for the full list:

- **No live 3D preview in the browser yet.** `ui/src/components/ThreeCanvas.jsx`
  exists but isn't wired into the app — `docs/architecture.html`'s own
  technical diagram labels this panel "NO 3D PREVIEW," matching the current
  code. The web app shows the generated USD file/cameras and, after a run,
  the Kit render output — not a live scene as the shot is described.
- Physics-flag fixes (bracing/mass) don't yet visibly resolve — the worker's
  physics check doesn't read the metadata a fix would add.
- The real Kit/Replicator RTX path is written but largely unexercised outside
  a live Omniverse Kit runtime; the practical fallback is a placeholder render.
- Camera-rig collision sweeps from Isaac Sim reach the fix agent, but the
  in-app re-render step doesn't recompute them (needs a re-run + re-ingest).

## Roadmap

The same physics-grounded approach, extended past one shot in one scene:

- **Sequencing** — multi-scene shot lists, generated consecutively.
- **Recommend** — smarter scene layouts matched to what the brief needs.
- **Blocking** — item placement validation, built for stage & theater too.
- **Choreography** — validating actor movement paths through the set.
