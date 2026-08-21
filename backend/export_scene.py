"""
export_scene.py

Runs the scene service against set.usda and exports everything the
3D viewer needs — prim boxes, camera frustums, and validation results
per shot — as a single JSON payload embedded into viewer.html.

Usage:
    python3 export_scene.py
    # writes scene_data.json and refreshes viewer.html
"""

import json
from pxr import Usd, UsdGeom
import scene_service as ss

SHOTS = [
    {
        "name": "Shot 1 — CamMedium on actor",
        "camera": "/World/Cameras/CamMedium",
        "target": "/World/ActorMarkA",
        "watch_intrusion": ["/World/Rig/LightStandA"],
    },
    {
        "name": "Shot 2 — CamWide establishing",
        "camera": "/World/Cameras/CamWide",
        "target": "/World/ActorMarkA",
        "watch_intrusion": ["/World/Rig/LightStandA"],
        "clearance_pairs": [
            {"a": "/World/Props/CrateA", "b": "/World/Props/CrateB", "min_distance": 0.5},
        ],
    },
    {
        "name": "Shot 3 — CamCloseup",
        "camera": "/World/Cameras/CamCloseup",
        "target": "/World/ActorMarkA",
        "clearance_pairs": [
            {"a": "/World/Cameras/CamCloseup", "b": "/World/Room/WallWest", "min_distance": 0.3},
        ],
    },
]


def export(usda_path="set.usda", out_path="scene_data.json"):
    stage = Usd.Stage.Open(usda_path)
    bc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    xc = UsdGeom.XformCache(Usd.TimeCode.Default())

    boxes = []
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Gprim):
            continue
        rng = bc.ComputeWorldBound(prim).ComputeAlignedRange()
        if rng.IsEmpty():
            continue
        path = str(prim.GetPath())
        group = path.split("/")[2] if len(path.split("/")) > 2 else "Other"
        boxes.append({
            "path": path,
            "type": str(prim.GetTypeName()),
            "group": group,
            "min": [round(v, 4) for v in rng.GetMin()],
            "max": [round(v, 4) for v in rng.GetMax()],
        })

    cameras = []
    shot_results = []
    for shot in SHOTS:
        result = ss.validate_shot(stage, shot)
        cam_path = shot["camera"]
        pos = xc.GetLocalToWorldTransform(stage.GetPrimAtPath(cam_path)).ExtractTranslation()
        corners = ss.camera_frustum_corners(stage, cam_path, near=0.1, far=6.0)
        cameras.append({
            "path": cam_path,
            "shot_name": shot["name"],
            "pos": [round(v, 4) for v in pos],
            "frustum_corners": [[round(v, 4) for v in c] for c in corners],
            "ok": result["ok"],
        })
        shot_results.append({
            "name": shot["name"],
            "camera": cam_path,
            "ok": result["ok"],
            "issues": result["issues"],
        })

    payload = {"boxes": boxes, "cameras": cameras, "shots": shot_results}
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote {out_path}: {len(boxes)} boxes, {len(cameras)} cameras, "
          f"{sum(1 for s in shot_results if not s['ok'])}/{len(shot_results)} shots failing")
    return payload


if __name__ == "__main__":
    export()