"""
standalone_render_and_validate.py

Fully headless entry point -- no Kit GUI, no Script Editor, no
copy-paste. Run with Isaac Sim's own interpreter:

  ./python.sh standalone_render_and_validate.py \
      --usd /path/to/studio_room_bad_shot.usda \
      --out /home/ubuntu/render_out \
      --frames 0,72 \
      --renderer PathTracing

Opens the given .usda, runs the same run_validation check the bridge
uses (imported directly from kit_bridge_extension.py -- no duplicated
scene-building/validation logic), and renders the requested frames
through MainCamera to PNG files using RTX (via omni.replicator.core,
the documented path for headless/offline capture -- it actually blocks
until each frame is rendered and written, unlike the viewport capture
utility which is async with no reliable "done" signal in headless
mode). With --renderer PathTracing it also applies the realism
settings discussed for the pitch: OptiX denoiser, higher sample
accumulation, ACES tonemapping, and a warm-up loop before each capture
so the path tracer actually converges instead of grabbing a noisy
first sample.

Output PNGs are named rgb_0000.png, rgb_0001.png, ... in capture
order (BasicWriter's own numbering, not the USD time code) -- with
--frames all this is already a contiguous sequence, ready for
frames_to_video.py as-is.

Output lands in --out on THIS machine (the Isaac Sim host, e.g. your
AWS instance) -- this script has no networking of its own. To get the
PNGs onto your laptop afterward:

  scp ubuntu@<instance>:/home/ubuntu/render_out/*.png ./local_dir/

or have your web backend serve --out as a static folder if the app
needs to fetch renders over HTTP instead.
"""

import argparse
import importlib.util
import json
import os
import sys


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--usd", help="Path to a .usda file (mutually exclusive with --scene)")
    p.add_argument("--scene", help="Shorthand scene name from kit_bridge_extension.SCENE_PATHS (e.g. scene1, scene2)")
    p.add_argument("--out", required=True, help="Output directory for rendered PNGs + validation_result.json")
    p.add_argument("--camera", default="/World/MainCamera", help="Camera prim path")
    p.add_argument("--frames", default="", help="Comma-separated time codes to render (e.g. '0,36,72'), or 'all' to render every frame in the stage's time range (needed to stitch a video afterward). Defaults to start+end only.")
    p.add_argument("--renderer", default="RayTracedLighting", choices=["RayTracedLighting", "PathTracing"])
    p.add_argument("--warmup", type=int, default=150, help="App update ticks before each capture, for path-tracer accumulation to converge")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    args = p.parse_args()
    if not args.usd and not args.scene:
        p.error("pass either --usd or --scene")
    return args


def main():
    args = parse_args()

    try:
        from isaacsim import SimulationApp  # Isaac Sim 4.x+
    except ImportError:
        from omni.isaac.kit import SimulationApp  # Isaac Sim 2023.x and earlier
    simulation_app = SimulationApp({
        "headless": True,
        "renderer": args.renderer,
        "width": args.width,
        "height": args.height,
    })

    import carb
    import omni.usd
    import omni.timeline
    import omni.replicator.core as rep

    settings = carb.settings.get_settings()
    if args.renderer == "PathTracing":
        settings.set("/rtx/pathtracing/optixDenoiser/enabled", True)
        settings.set("/rtx/pathtracing/spp", 1)
        settings.set("/rtx/pathtracing/totalSpp", 256)
        settings.set("/rtx/pathtracing/maxBounces", 6)
    settings.set("/rtx/post/tonemap/op", "AcesFilmic")

    # Reuse the bridge's action functions instead of re-implementing
    # scene-building/validation here -- this file and
    # kit_bridge_extension.py live in the same folder.
    bridge_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit_bridge_extension.py")
    spec = importlib.util.spec_from_file_location("kit_bridge_extension", bridge_path)
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)

    build_params = {"usda_path": args.usd} if args.usd else {"scene": args.scene}
    build_result = bridge.action_build_scene(build_params)
    print("build_scene:", build_result)
    if build_result["status"] != "ok":
        simulation_app.close()
        sys.exit(1)

    # Let the newly opened stage settle for a few ticks before reading
    # it back -- open_stage isn't guaranteed fully resolved same-frame.
    for _ in range(5):
        simulation_app.update()

    stage = omni.usd.get_context().get_stage()
    timeline = omni.timeline.get_timeline_interface()
    fps = stage.GetTimeCodesPerSecond() or 24.0

    start, end = stage.GetStartTimeCode(), stage.GetEndTimeCode()
    if args.frames == "all":
        frames = [start + i for i in range(int(end - start) + 1)]
    elif args.frames:
        frames = [float(f) for f in args.frames.split(",")]
    else:
        frames = [start, end]

    os.makedirs(args.out, exist_ok=True)

    # omni.replicator.core is the documented path for headless/offline
    # capture in standalone scripts -- unlike the viewport capture
    # utility (which is async with no reliable synchronous "done"
    # signal in headless mode, and turned out to silently no-op here),
    # rep.orchestrator.step() + wait_until_complete() actually blocks
    # until the frame is rendered AND written to disk.
    render_product = rep.create.render_product(args.camera, (args.width, args.height))
    writer = rep.WriterRegistry.get("BasicWriter")
    writer.initialize(output_dir=args.out, rgb=True)
    writer.attach([render_product])

    for frame in frames:
        timeline.set_current_time(frame / fps)
        for _ in range(args.warmup):
            simulation_app.update()

        rep.orchestrator.step(rt_subframes=1)
        rep.orchestrator.wait_until_complete()
        print(f"captured frame {frame:.0f} (see {args.out}/rgb_*.png -- BasicWriter numbers files by capture order, not by time code)")

    writer.detach()
    render_product.destroy()

    validation_result = bridge.action_run_validation({"camera_path": args.camera})
    print("run_validation:", validation_result)
    with open(os.path.join(args.out, "validation_result.json"), "w") as f:
        json.dump(validation_result, f, indent=2)

    simulation_app.close()


if __name__ == "__main__":
    main()
