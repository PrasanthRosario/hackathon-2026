# Offset — Architecture As It Actually Exists (2026-08-21, updated after fix pass)

Five-minute read before a demo. This describes what the code actually does today, not the original plan.

> **Update note:** the initial audit (below, in "Where this breaks") found the Kit render worker orphaned from the UI and the fix-verification loop never closing. Both have since been wired up and verified live in-browser — see "What was fixed" underneath. The physics-side gap (item 3) is still open.

## The real pipeline, step by step (current)

1. **Chat** — Director types a set description in the left panel ([LeftPanel.jsx](ui/src/components/LeftPanel.jsx)). Each turn POSTs to `/api/chat`, handled by [router.py:37](backend/src/modules/offset_agent/router.py:37). A keyword check or a 3rd user turn switches from clarifying questions ([chains.py](backend/src/modules/offset_agent/chains.py), Haiku) to structured extraction (Sonnet) — real, distinct OpenRouter calls.
2. **Live preview** — [ThreeCanvas.jsx](ui/src/components/ThreeCanvas.jsx) renders walls/floor/camera dolly path/frustum live from the same `scene_config` schema the backend emits — no drift.
3. **Confirm & Generate USD** — `POST /api/generate-usd` ([router.py:80](backend/src/modules/offset_agent/router.py:80)) builds a real `.usda` via `pxr.Usd`, and now also reads the file back and returns its text as `usd_content` in the response, so the frontend has real USD text on hand without a second round trip.
4. **Render in Kit** — A new button in [RenderView.jsx](ui/src/components/RenderView.jsx) (top-right of the viewport) calls `handleRenderInKit` in [App.jsx](ui/src/App.jsx), which `POST`s `usd_content` + a unique `scene_id` to `/api/render`. That endpoint ([router.py:160](backend/src/modules/offset_agent/router.py:160)) subprocess-invokes [kit_render_worker.py](kit_render_worker.py) and returns `render_files`/`coverage_flags`/`physics_flags`. Results render in a new **Kit Render Result** tab ([KitRenderResultView.jsx](ui/src/components/KitRenderResultView.jsx)) — thumbnails plus flag lists, served through a new `/renders` Vite proxy.
5. **Fast heuristic checks (unchanged, optional)** — The "Advanced Validation Suite" in the left panel still offers `/api/check-coverage` / `/api/check-physics`, one-line heuristics that don't touch USD or the Kit worker. Kept intentionally as a quick smoke-check tier; not the real validation path.
6. **Propose Fix & Re-verify** — When the Kit Render Result tab has any coverage or physics flags, a "Propose Fix & Re-verify" button appears. It calls `handleProposeFixAndReverify` in [App.jsx](ui/src/App.jsx), which: `POST /api/propose-fix` (now backed by [fix_agent.py](backend/src/modules/offset_agent/fix_agent.py)'s `propose_fixes`/`apply_fix`, the spec-matching implementation) → applies the returned fixes to `scene_config` → re-`POST`s `/api/generate-usd` → re-`POST`s `/api/render` → posts a before/after flag-count message to chat. **Verified live**: a `north_top` coverage flag (24mm lens) was fixed by Sonnet proposing `change_lens` → 35mm, and the re-render confirmed the flag actually cleared (1 → 0), not just that a fix was suggested.
7. **Report** — Still no separate unified report screen; the Kit Render Result tab (thumbnails + flags) is the report surface. `OmniverseStreamView.jsx` remains an explicit, labeled stub — correctly never wired to a live feed.

## What was fixed (this session)

- **Kit render worker wired into the UI** ([App.jsx](ui/src/App.jsx), [RenderView.jsx](ui/src/components/RenderView.jsx), [KitRenderResultView.jsx](ui/src/components/KitRenderResultView.jsx), `/renders` proxy in [vite.config.js](ui/vite.config.js)). Previously implemented but never called from the frontend.
- **Fix-proposal path unified** onto `fix_agent.py` (spec-matching fixed fix-type enum + `apply_fix` mutator). The duplicate freeform implementation (`chains.run_sonnet_fix_proposal`) was deleted from [chains.py](backend/src/modules/offset_agent/chains.py); `/api/propose-fix` in [router.py](backend/src/modules/offset_agent/router.py) now has a typed request/response ([models.py](backend/src/modules/offset_agent/models.py)) and calls `fix_agent.propose_fixes` + `fix_agent.apply_fix`.
- **Fix loop actually closes**: propose → apply → regenerate USD → re-render → re-verify, all automatic, with an explicit before/after flag count surfaced in chat. Confirmed working for coverage flags end-to-end in a live browser test.
- **Real dependency gap found and fixed**: `chains.py`/`fix_agent.py`/`tools.py` import `langchain_openai`, `langchain_core`, `python-dotenv` — none of which were declared in [backend/pyproject.toml](backend/pyproject.toml). The app only "worked" because two stale processes on port 8000 were running from an untracked, manually-pip-installed environment (`pyenv` global site-packages, not the project's `uv` venv). A fresh clone or the real EC2 box would have failed at import time. Added the missing deps, relocked, killed the stale processes, and verified a clean boot from the declared environment.
- **`make backend-dev` now requests `--extra usd`**, so `pxr` is reliably present instead of depending on venv history.

## Where this breaks from the plan (original audit, mostly resolved)

- ~~Kit worker orphaned from the UI~~ — **fixed**, see above.
- ~~Two duplicate fix-proposal implementations, neither re-verifying~~ — **fixed**, unified onto `fix_agent.py` with automatic re-verification.
- **Still open**: `kit_render_worker.py`'s physics check ([kit_render_worker.py:183-207](kit_render_worker.py:183)) is a hardcoded string/threshold heuristic (`if "LightStandA" in path_str`, `pos[2] > 2.5`) that doesn't read any bracing/mass metadata a fix would add — so `add_bracing`/`add_mass` fixes structurally *cannot* change the worker's verdict even now that the loop mechanically closes. This needs the worker (and probably `SceneConfigSchema`) extended to carry rig/bracing state before a physics-flag demo would show a real before/after. Coverage-flag fixes (`change_lens`, `reposition_camera`) work correctly today because focal length and camera position are real USD attributes the worker actually reads.
- **"RTX render" and "PhysX simulation" are still placeholders dressed as the real thing.** The `HAS_OMNI` (real Kit/Replicator) path in `kit_render_worker.py` is written but almost certainly never exercised outside an actual Kit runtime; the practical fallback draws a flat placeholder PNG. This is unchanged and out of scope for a plumbing fix — it needs an actual Kit/Replicator environment to test.
- **Camera rig collision sweep** (optional per spec) still not built — no `collision_flags` in `result.json`.

## Component map

| Component | File(s) | Status |
|---|---|---|
| A. Chat agent | [router.py](backend/src/modules/offset_agent/router.py), [chains.py](backend/src/modules/offset_agent/chains.py) | ✅ Fully wired, model routing confirmed real |
| B. Three.js preview | [ThreeCanvas.jsx](ui/src/components/ThreeCanvas.jsx), [RenderView.jsx](ui/src/components/RenderView.jsx) | ✅ Fully wired, schema matches backend exactly |
| C. USD generation | [router.py:80](backend/src/modules/offset_agent/router.py:80) (wired), [tools.py](backend/src/modules/offset_agent/tools.py) (duplicate, still unwired — not touched this pass) | ✅ Wired |
| D. Kit render worker | [kit_render_worker.py](kit_render_worker.py) | ✅ Wired end-to-end from the UI; render/physics/coverage logic itself is still placeholder-level (see above) |
| E. FastAPI `/render` + status | [router.py:160](backend/src/modules/offset_agent/router.py:160), [router.py:241](backend/src/modules/offset_agent/router.py:241) | ✅ Wired and called from the frontend now |
| F. fix_agent.py | [fix_agent.py](backend/src/modules/offset_agent/fix_agent.py) | ✅ Now the single, live fix-proposal path, with automatic re-verification |

## Riskiest points for a demo (updated)

1. **Physics-flag fixes won't visibly resolve** — the demo-safe story is a coverage-flag fix (lens change / reposition), which is verified working. Don't promise a physics `add_bracing` fix will clear a flag live; it structurally can't yet (see above).
2. **The Kit worker path (`HAS_OMNI`) has probably never run against a real Kit/Replicator install** in this repo — renders will be flat placeholder PNGs on this machine. If demoing actual RTX renders on the EC2 GPU box, budget time to verify `omni.replicator.core`'s calls actually work there, not just that the fallback PNG path works (which is what's exercised on dev machines).
3. **`/render`'s EC2-path detection** (`/home/ubuntu/scenes`, `/home/ubuntu/renders`) silently switches directories based on `os.access("/home/ubuntu", os.W_OK)` ([router.py:173](backend/src/modules/offset_agent/router.py:173)) — untested branching logic on the actual demo box, worth a smoke test there specifically.
4. **Verify the EC2 box's environment isn't in the same "stale untracked install" state** the dev machine was in — now that `pyproject.toml`/`uv.lock` are correct, a `uv sync --extra usd` (or equivalent) on the demo box before going live is cheap insurance.

## Dead code / duplication inventory (not removed — audit only)

- **`legacy/`** (`generate_room.py`, `make_set.py`, `export_scene.py`, `scene_service.py`, `paths.py`) — an entire earlier prototype, not imported by anything in `backend/` or `kit_render_worker.py`. Notably, `legacy/scene_service.py` implements *real* frustum-corner math, occlusion, and clearance checks — more sophisticated than the heuristics currently wired into `/api/check-coverage`/`/api/check-physics`. Worth a look before writing off as "just legacy."
- **`scenes/issac_script.py`** — reference-only script meant to be pasted into Isaac Sim's Script Editor (`import omni.physx`, `import omni.kit.app`). Not imported by any pipeline code, so it's not a functional Isaac Sim dependency, but the filename/content is a copy-paste risk if someone assumes it's part of the active pipeline. `legacy/generate_room.py`'s docstring also references Isaac Sim by name (comments only, no `omni.*` import).
- **Duplicate USD generation**: [router.py:80-149](backend/src/modules/offset_agent/router.py:80) (`generate_usd_stage`, actually called) and [tools.py:18-95](backend/src/modules/offset_agent/tools.py:18) (`generate_usd_tool`, a LangChain `@tool`-wrapped near-identical copy, only reachable via `get_agent_with_tools()` which nothing currently calls) are the same logic written twice.
- **Duplicate fix-proposal logic**: `fix_agent.py` (spec-matching, dead) vs. `chains.run_sonnet_fix_proposal` (actually wired, freeform).
- **`test_openrouter_sonnet.py`** at repo root — a manual smoke-test script, harmless but not part of the app; fine to leave or move into `backend/tests/`.
- **No stray Isaac Sim import in any actively-executed path** — confirmed via `grep -rli isaac` across all `.py` files: only the two files above, neither on the live request path.
- **No WebRTC dependency anywhere** (`grep -rli webrtc` across `.py`, `docker-compose*.yml`, `Dockerfile` — zero hits; `package.json` has no WebRTC lib either). `OmniverseStreamView.jsx` is UI-only chrome with a fake status readout, clearly labeled as a stub. Architecture requirement satisfied.
- **Secrets**: `.env` is correctly gitignored (`*.env`, `.env.*`, `!.env.example`), confirmed not tracked by git (`git check-ignore` matches `backend/.env`), and `chains.py`/`fix_agent.py` read `OPENROUTER_API_KEY` from environment only. No hardcoded keys found.

## Prioritized punch list

**Done this pass:**
1. ~~Wire a "Render in Kit" action in the UI~~ — done, verified live (thumbnails + flags render in a new tab).
2. ~~Decide on one fix-proposal path and make the loop actually close~~ — done, unified onto `fix_agent.py`, verified live with a real before/after flag-count drop (1 → 0).
3. ~~Missing `langchain-openai`/`python-dotenv` in `pyproject.toml`~~ (found while verifying #1/#2, not in the original audit) — fixed, relocked, confirmed clean boot from the declared `uv` environment.

**Worth fixing before the demo if time allows:**
1. If demoing the physics angle specifically, `kit_render_worker.py`'s physics check needs to actually read something the fix loop can change (e.g. a bracing/mass attribute written onto the USD prim, and a matching field on `SceneConfigSchema`) instead of a hardcoded `"LightStandA" in path_str` check — otherwise no physics fix will ever visibly resolve the flag on stage. Coverage-flag fixes already demo cleanly; lead with those.
2. Smoke-test the actual EC2 box specifically: confirm `uv sync --extra usd` (or equivalent) has run there so it isn't relying on a stale out-of-band install the way this dev machine was, and sanity-check the `/home/ubuntu/...` path-detection branch in `/render` actually lands where expected.

**Fine to leave as-is for the demo:**
- `legacy/` folder and `scenes/issac_script.py` — inert, not on any live path, no cleanup urgency before a demo (but flag for post-hackathon deletion).
- Duplicate `generate_usd_tool` in `tools.py` — unreachable, harmless, not touched this pass.
- `OmniverseStreamView.jsx` — it's an honest, labeled placeholder; nobody should mistake it for a live stream.
- The two simple stub endpoints (`/check-coverage`, `/check-physics`) — fine as a fast "smoke check" tier; just don't call them "physics simulation" out loud during the demo.
- Environment/secrets handling (`.env` gitignore, no hardcoded keys) — already correct, no action needed.
