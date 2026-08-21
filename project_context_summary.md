# Project context: pre-viz shot validation tool (for continuing in a new chat)

## The idea
Pre-visualization validation for physical film/TV sets. An AI agent validates a
shot list against a 3D set model *before* anything is physically built: it
projects each camera's frustum through its planned move, flags shots that
stray off-set (see past the physical set into "nothing"), and proposes fixes.
Currently prototyped around a podcast-room use case as the demo set.

## Context / event
Hackathon build, 4-person team, ~22-hour build window. Judged with a 5-minute
pitch to an L1 (first-round/screening) judge.

## Core technical decisions made so far
- **Platform: NVIDIA Omniverse / Isaac Sim**, built on OpenUSD. Chosen over a
  generic 3D tool because rendering (RTX), physics (PhysX), and the scene
  graph (USD) all share one stage — no exporting between tools. Free for
  dev/production/redistribution as of May 2026.
- **Physics angle** (this is a real differentiator, not just marketing): the
  tool doesn't just check frustum-vs-geometry with hand-rolled math — it runs
  actual PhysX raycasts against real collision meshes on the same stage the
  director sees. Three physics domains involved: optics/projective geometry
  (lens math), rigid-body collision (frustum vs set), and (roadmap, not yet
  built) rig-motion feasibility (can a real crane/dolly/drone achieve the
  move's velocity/acceleration).
- **Environment**: AWS Marketplace "NVIDIA Isaac Sim™ Development Workstation
  (Linux)" AMI, EC2 g6e.2xlarge, connected via NICE DCV. Isaac Sim ships its
  own Python (`./python.sh`) with `omni.*` modules — a plain `python3` cannot
  import `omni.*`.
- **Chat/agent architecture**: after iterating, settled on keeping the chat
  agent + web UI **outside** Kit/Isaac Sim as a separate web app (not an
  `omni.ui` extension panel inside Kit). This required building a bridge
  between the two processes (see below).
- **Bridge pattern**: a simple file-based polling bridge, not a full HTTP/
  WebSocket server inside Kit (chosen for hackathon time constraints over the
  "more proper" option). Web backend writes a JSON command file with a UUID;
  a script running inside Isaac Sim's Script Editor polls a folder every
  frame (via `omni.kit.app` update-event subscription), executes the
  matching action, writes a JSON result file back; the web backend polls for
  that result file. This round-trip protocol was verified working with a
  mock test (see Verified section below).
- **Web viewer plan (not yet built)**: use Kit's native WebRTC viewport
  streaming (ports TCP 49100 / UDP 47998, already opened in the AWS security
  group per the AMI setup steps) so the browser shows the live 3D scene
  directly, independent of the command/result bridge — two separate
  channels: control via file bridge, video via WebRTC.

## Files built so far (in /mnt/user-data/outputs across the conversation)
1. **hackathon_build_checklist.md** — hour-by-hour, 4-person task split
   (Scene Lead / Geometry Lead / Logic Lead / Viz-Demo Lead) for the 22-hour
   build, plus a risk list (coordinate mismatch, instance restarts, scope
   creep, no backup recording).
2. **room_set.usda** + **generate_room.py** — first-pass generic room
   (walls, floor, off-set gap, backstage void, starter camera). Superseded
   by the podcast-specific version below.
3. **podcast_room.usda** + **generate_podcast_room.py** — the real demo set:
   6m×5m×2.7m room, desk, 2 chairs, mic stands, 18-panel acoustic wall grid,
   ring light, and a camera. Contains `look_at_matrix()` / `point_camera_at()`
   — real vector math (forward/right/up basis, built as a `Gf.Matrix4d`) that
   correctly orients the USD camera, fixing an earlier bug where the camera
   was left at rotation (0,0,0) and pointed straight down. Also contains
   `animate_camera_move()` which bakes real USD time-sampled keyframe
   animation (verified: interpolates correctly frame-by-frame) for a 3-second
   dolly-in move on the desk.
4. **podcast_room_bad_shot.usda** — same room, camera deliberately re-aimed
   at the off-set door gap instead of the desk. Used to prove the validator
   actually catches failures, not just always says OK.
5. **validate_shot.py** — standalone, pure-`pxr`/USD validator (no Isaac Sim
   needed, runs with plain `python3` + `pip install usd-core`). Casts 4
   frustum-corner rays per sampled frame, checks ray-vs-AABB against any prim
   tagged `is_off_set=True`. **Verified working both ways**: returns
   `SHOT OK` on `podcast_room.usda` and `SHOT FLAGGED` with exact
   frame/corner/prim detail on `podcast_room_bad_shot.usda`.
6. **isaac_sim_live_validate.py** — live, per-frame version for Isaac Sim's
   Script Editor. Subscribes to the app update loop, reads the *current*
   playhead time each tick, casts real PhysX raycasts (not just AABB) through
   the frustum corners, prints `OK`/`FLAG` per frame and a final `SHOT OK` /
   `SHOT FLAGGED` summary when the timeline reaches its end. Not yet run
   successfully end-to-end in Isaac Sim (see Known issue below).
7. **standalone_validate.py** — headless CLI version, run via Isaac Sim's own
   interpreter (`./python.sh standalone_validate.py --usd <path>`), using
   `SimulationApp(headless=True)`. Useful for batch-checking many shots
   without any GUI. Not yet run/verified end-to-end (same caveat).
8. **kit_bridge_extension.py** — the current, fully self-contained (no
   external file imports) Kit-side script. Paste-and-run in Script Editor.
   Contains inlined: camera math (`look_at_matrix`, `point_camera_at`,
   `animate_camera_move`, `get_frustum_corner_dirs`), scene building
   (`make_box`, `make_cyl`, `build_podcast_room`), and three bridge actions
   (`build_scene`, `move_camera`, `run_validation`) wired to a folder-polling
   loop watching `/home/ubuntu/bridge/commands` and writing to
   `/home/ubuntu/bridge/results`.
9. **web_backend_client.py** — the external web app's client-side function,
   `call_kit(action, params, timeout)`, meant to be imported into whatever
   backend hosts the chat/LLM tool-calling loop. Includes a runnable
   `__main__` example calling `move_camera` then `run_validation`.

## Verified vs. not-yet-verified (important distinction)
**Actually run and confirmed working in this conversation:**
- `generate_podcast_room.py` scene generation (47 prims, correct structure)
- Camera look-at math (forward vector numerically checked, points at desk)
- Baked keyframe animation (interpolation checked frame-by-frame)
- `validate_shot.py` — both PASS and FLAGGED cases proven
- The file-based bridge protocol itself (mock round-trip test passed)

**Written correctly by construction but NOT yet run inside real Isaac Sim**
(because this environment has no `omni.*`/GPU access — only plain `pxr`/
usd-core is available here):
- `isaac_sim_live_validate.py`
- `standalone_validate.py`
- `kit_bridge_extension.py`'s actual `omni.physx`/`omni.usd` calls (the pure
  USD parts of it were separately re-verified after being inlined)

## Known issue in progress (most recent)
Hit a `Boost.Python.ArgumentError` on `stage.GetTimeCodesPerSecond()` inside
`isaac_sim_live_validate.py`'s `on_update` callback — traceback pointed to
line 75. Root cause: the `stage` variable was likely captured once at script
load time, before the stage was fully valid, or went stale. **Fix given**:
use `timeline.get_time_codes_per_second()` instead of going through `stage`
for that value, and re-fetch `stage = omni.usd.get_context().get_stage()`
fresh *inside* `on_update` rather than relying on a module-level capture.
This fix has been described but not yet confirmed applied/re-tested.

## Open next steps (not yet done)
1. Confirm the `Boost.Python.ArgumentError` fix resolves the error in Isaac
   Sim, re-test `isaac_sim_live_validate.py` against both `podcast_room.usda`
   (expect OK) and `podcast_room_bad_shot.usda` (expect FLAGGED).
2. Apply the same `timeline.get_time_codes_per_second()` pattern inside
   `kit_bridge_extension.py`'s `action_run_validation` if it has the same
   stage-dependency issue (it currently still calls
   `stage.GetTimeCodesPerSecond()`-equivalent patterns implicitly via
   `Usd.TimeCode` — worth double-checking against the same bug class).
3. Run `kit_bridge_extension.py` for real inside Isaac Sim, confirm the
   `build_scene` / `move_camera` / `run_validation` actions work against the
   live stage (not just the mock protocol test).
4. Test `python3 web_backend_client.py` against the *real* running bridge
   (not the mock), on the same AWS instance, confirming the full round trip
   end-to-end.
5. Decide and build the actual web app frontend (chat UI) and backend (LLM
   tool-calling loop deciding when to call `build_scene`/`move_camera`/
   `run_validation`) — not yet started.
6. Wire up Kit's native WebRTC viewport streaming into the web app frontend
   for the live 3D view — not yet started, flagged as higher-infra-risk,
   recommended as a stretch goal with DCV/screen-share as fallback.
7. Rehearse the 5-minute pitch (hook → solution → physics/Omniverse
   justification → 90s live demo → differentiation → close/ask) with actual
   timing against the real (not mock) demo.

## Pitch positioning already worked out
- Lead with the cost of the real-world problem, not the tech.
- Core differentiator to state explicitly: "we're not rendering a picture of
  the set, we're running a physics engine's collision query against it."
- Omniverse justification: one shared USD stage for chat/agent commands,
  PhysX validation, and RTX rendering — no export/sync between tools.
- Be upfront about roadmap items (rig-motion feasibility physics, multi-shot
  batch validation) rather than hiding them — read as credible, not weak.
- Name the buyer directly in the close: previz supervisors / art departments
  on productions that can't afford to build a set twice.
