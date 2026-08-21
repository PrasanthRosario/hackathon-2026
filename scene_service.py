"""
scene_service.py

The tool surface for the pre-viz shot-validation POC. Plain Python,
no model dependency, no GPU dependency — this is the part that has to
be rock solid before anything agentic sits on top of it.

Provides:
    inspect_scene(stage)                    -> compact scene summary
    camera_frustum_corners(stage, cam_path)  -> 8 world-space corners
    check_frame_intrusion(stage, cam, prop)  -> is prop inside frame?
    check_occlusion(stage, cam, target)      -> is target blocked?
    check_clearance(stage, a, b, min_dist)   -> too close / overlapping?
    validate_shot(stage, shot)               -> {ok, issues}

Requires no GPU. Tested with usd-core.
"""

import math
from pxr import Usd, UsdGeom, Gf


# ---------------------------------------------------------------------------
# Perception: inspect_scene
# ---------------------------------------------------------------------------

def inspect_scene(stage: Usd.Stage, root: str = "/World", max_prims: int = 200) -> dict:
    """Compact, LLM-readable summary of a USD stage: authored, not resolved
    noise. Gprims and Cameras only — the things a shot list actually cares
    about."""
    xc = UsdGeom.XformCache(Usd.TimeCode.Default())
    bc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])

    items, truncated = [], False
    root_prim = stage.GetPrimAtPath(root)
    if not root_prim.IsValid():
        raise ValueError(f"no such prim: {root}")

    for i, prim in enumerate(Usd.PrimRange(root_prim)):
        if i >= max_prims:
            truncated = True
            break
        if prim.IsA(UsdGeom.Gprim):
            pos = xc.GetLocalToWorldTransform(prim).ExtractTranslation()
            rng = bc.ComputeWorldBound(prim).ComputeAlignedRange()
            items.append({
                "path": str(prim.GetPath()),
                "type": str(prim.GetTypeName()),
                "pos": [round(v, 3) for v in pos],
                "bbox_min": [round(v, 3) for v in rng.GetMin()],
                "bbox_max": [round(v, 3) for v in rng.GetMax()],
            })
        elif prim.IsA(UsdGeom.Camera):
            pos = xc.GetLocalToWorldTransform(prim).ExtractTranslation()
            cam = UsdGeom.Camera(prim)
            items.append({
                "path": str(prim.GetPath()),
                "type": "Camera",
                "pos": [round(v, 3) for v in pos],
                "focal_length": cam.GetFocalLengthAttr().Get(),
            })

    return {"root": root, "prim_count": len(items), "truncated": truncated, "prims": items}


# ---------------------------------------------------------------------------
# Camera frustum math
# ---------------------------------------------------------------------------

def _camera_fov(stage: Usd.Stage, cam_path: str):
    """Horizontal / vertical field of view in radians, from focal length
    and aperture — the values that make 'wide' vs 'long lens' mean
    something physically, not just cosmetically."""
    cam = UsdGeom.Camera(stage.GetPrimAtPath(cam_path))
    focal = cam.GetFocalLengthAttr().Get() or 35.0
    h_ap = cam.GetHorizontalApertureAttr().Get() or 24.0
    v_ap = cam.GetVerticalApertureAttr().Get() or 18.0
    h_fov = 2 * math.atan((h_ap / 2) / focal)
    v_fov = 2 * math.atan((v_ap / 2) / focal)
    return h_fov, v_fov


def camera_frustum_corners(stage: Usd.Stage, cam_path: str,
                            near: float = 0.1, far: float = 12.0):
    """8 world-space corners of the camera frustum (4 near, 4 far),
    ordered [near_tl, near_tr, near_br, near_bl, far_tl, far_tr, far_br,
    far_bl]. USD cameras look down local -Z, +Y up."""
    prim = stage.GetPrimAtPath(cam_path)
    if not prim.IsValid() or not prim.IsA(UsdGeom.Camera):
        raise ValueError(f"no camera at {cam_path}")

    xc = UsdGeom.XformCache(Usd.TimeCode.Default())
    world = xc.GetLocalToWorldTransform(prim)

    h_fov, v_fov = _camera_fov(stage, cam_path)
    corners = []
    for dist in (near, far):
        hw = dist * math.tan(h_fov / 2)
        hh = dist * math.tan(v_fov / 2)
        # local-space corners, camera looks down -Z
        local = [
            Gf.Vec3d(-hw, hh, -dist),   # top-left
            Gf.Vec3d(hw, hh, -dist),    # top-right
            Gf.Vec3d(hw, -hh, -dist),   # bottom-right
            Gf.Vec3d(-hw, -hh, -dist),  # bottom-left
        ]
        for pt in local:
            corners.append(world.Transform(pt))
    return corners


def _frustum_planes(corners):
    """Six inward-facing planes (near, far, left, right, top, bottom) as
    (normal, point) pairs, built from the 8 frustum corners."""
    near_tl, near_tr, near_br, near_bl, far_tl, far_tr, far_br, far_bl = corners
    centroid = sum(corners, Gf.Vec3d(0, 0, 0)) / 8.0

    def plane(p0, p1, p2):
        n = Gf.Cross(p1 - p0, p2 - p0)
        if n.GetLength() > 1e-9:
            n = n.GetNormalized()
        # orient normal toward the frustum's interior (the centroid of
        # all 8 corners), not a single fixed direction — near and far
        # planes need opposite orientations, so a shared "forward"
        # reference is wrong for one of them.
        if Gf.Dot(n, centroid - p0) < 0:
            n = -n
        return (n, p0)

    return [
        plane(near_tl, near_tr, near_bl),   # near
        plane(far_tr, far_tl, far_bl),      # far
        plane(near_tl, near_bl, far_bl),    # left
        plane(near_tr, far_tr, far_br),     # right
        plane(near_tl, far_tl, far_tr),     # top
        plane(near_bl, near_br, far_br),    # bottom
    ]


def _bbox_intersects_planes(bbox_min, bbox_max, planes) -> bool:
    """Conservative AABB-vs-frustum test: for each plane, if all 8 box
    corners are on the outside, the box is fully excluded. Otherwise
    treat it as (possibly) inside — good enough for layout-level checks."""
    corners = [
        Gf.Vec3d(x, y, z)
        for x in (bbox_min[0], bbox_max[0])
        for y in (bbox_min[1], bbox_max[1])
        for z in (bbox_min[2], bbox_max[2])
    ]
    for normal, point in planes:
        if all(Gf.Dot(normal, c - point) < 0 for c in corners):
            return False
    return True


# ---------------------------------------------------------------------------
# Rule: frame intrusion — is a prop visible inside a given camera's frustum?
# ---------------------------------------------------------------------------

def check_frame_intrusion(stage: Usd.Stage, cam_path: str, prop_path: str,
                           near: float = 0.1, far: float = 12.0) -> dict:
    prop = stage.GetPrimAtPath(prop_path)
    if not prop.IsValid():
        raise ValueError(f"no such prim: {prop_path}")

    bc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    rng = bc.ComputeWorldBound(prop).ComputeAlignedRange()

    corners = camera_frustum_corners(stage, cam_path, near, far)
    planes = _frustum_planes(corners)
    inside = _bbox_intersects_planes(rng.GetMin(), rng.GetMax(), planes)

    return {
        "camera": cam_path,
        "prop": prop_path,
        "in_frame": inside,
    }


# ---------------------------------------------------------------------------
# Rule: occlusion — does anything block the camera's line of sight to target?
# ---------------------------------------------------------------------------

def _ray_aabb_intersect(origin, direction, bbox_min, bbox_max):
    """Standard slab-method ray/AABB test. Returns entry distance t, or
    None if no hit."""
    tmin, tmax = 0.0, float("inf")
    for i in range(3):
        o, d = origin[i], direction[i]
        lo, hi = bbox_min[i], bbox_max[i]
        if abs(d) < 1e-9:
            if o < lo or o > hi:
                return None
            continue
        t1, t2 = (lo - o) / d, (hi - o) / d
        if t1 > t2:
            t1, t2 = t2, t1
        tmin = max(tmin, t1)
        tmax = min(tmax, t2)
        if tmin > tmax:
            return None
    return tmin


def check_occlusion(stage: Usd.Stage, cam_path: str, target_path: str,
                     ignore=None) -> dict:
    """Casts a ray from the camera to the target's centre and checks
    whether any other Gprim's bounding box sits in the way first."""
    ignore = set(ignore or [])
    ignore.update({cam_path, target_path})

    xc = UsdGeom.XformCache(Usd.TimeCode.Default())
    bc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])

    cam_prim = stage.GetPrimAtPath(cam_path)
    target_prim = stage.GetPrimAtPath(target_path)
    if not cam_prim.IsValid() or not target_prim.IsValid():
        raise ValueError("camera or target path invalid")

    cam_pos = xc.GetLocalToWorldTransform(cam_prim).ExtractTranslation()
    target_rng = bc.ComputeWorldBound(target_prim).ComputeAlignedRange()
    target_pos = (target_rng.GetMin() + target_rng.GetMax()) / 2.0

    direction = target_pos - cam_pos
    target_dist = direction.GetLength()
    if target_dist < 1e-6:
        return {"camera": cam_path, "target": target_path, "occluded": False, "blockers": []}
    direction = direction / target_dist

    blockers = []
    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if path in ignore or not prim.IsA(UsdGeom.Gprim):
            continue
        rng = bc.ComputeWorldBound(prim).ComputeAlignedRange()
        t = _ray_aabb_intersect(cam_pos, direction, rng.GetMin(), rng.GetMax())
        if t is not None and 1e-3 < t < target_dist - 1e-3:
            blockers.append({"path": path, "distance": round(t, 3)})

    blockers.sort(key=lambda b: b["distance"])
    return {
        "camera": cam_path,
        "target": target_path,
        "occluded": len(blockers) > 0,
        "blockers": blockers,
    }


# ---------------------------------------------------------------------------
# Rule: clearance — are two prims too close / overlapping?
# ---------------------------------------------------------------------------

def _bbox_or_point(stage: Usd.Stage, path: str) -> Gf.Range3d:
    """World-space bbox for a prim. Non-Gprim prims (like Camera) have no
    renderable bounds, so fall back to a zero-size range at their world
    position — enough to measure clearance/distance against."""
    bc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    prim = stage.GetPrimAtPath(path)
    rng = bc.ComputeWorldBound(prim).ComputeAlignedRange()
    if rng.IsEmpty():
        xc = UsdGeom.XformCache(Usd.TimeCode.Default())
        pos = xc.GetLocalToWorldTransform(prim).ExtractTranslation()
        rng = Gf.Range3d(pos, pos)
    return rng


def check_clearance(stage: Usd.Stage, path_a: str, path_b: str,
                     min_distance: float = 0.0) -> dict:
    prim_a = stage.GetPrimAtPath(path_a)
    prim_b = stage.GetPrimAtPath(path_b)
    if not prim_a.IsValid() or not prim_b.IsValid():
        raise ValueError("path_a or path_b invalid")

    ra = _bbox_or_point(stage, path_a)
    rb = _bbox_or_point(stage, path_b)

    overlap = not Gf.Range3d.GetIntersection(ra, rb).IsEmpty()

    if overlap:
        distance = 0.0
    else:
        # distance between axis-aligned boxes, per axis gap, combined
        gap = [0.0, 0.0, 0.0]
        for i in range(3):
            if ra.GetMax()[i] < rb.GetMin()[i]:
                gap[i] = rb.GetMin()[i] - ra.GetMax()[i]
            elif rb.GetMax()[i] < ra.GetMin()[i]:
                gap[i] = ra.GetMin()[i] - rb.GetMax()[i]
        distance = math.sqrt(sum(g * g for g in gap))

    return {
        "a": path_a,
        "b": path_b,
        "overlap": overlap,
        "distance": round(distance, 3),
        "min_required": min_distance,
        "ok": (not overlap) and distance >= min_distance,
    }


# ---------------------------------------------------------------------------
# Orchestration: validate_shot
# ---------------------------------------------------------------------------

def validate_shot(stage: Usd.Stage, shot: dict) -> dict:
    """
    A `shot` dict looks like:
        {
            "name": "Shot 3 - wide establishing",
            "camera": "/World/Cameras/CamWide",
            "target": "/World/ActorMarkA",       # optional, for occlusion
            "watch_intrusion": ["/World/Rig/LightStandA"],  # optional
            "clearance_pairs": [                  # optional
                {"a": "...", "b": "...", "min_distance": 0.3}
            ],
        }
    Returns {"ok": bool, "issues": [...]} — issues are prompt-ready dicts,
    formatted for feeding straight back to an LLM on retry.
    """
    issues = []

    cam_path = shot["camera"]
    if not stage.GetPrimAtPath(cam_path).IsValid():
        return {"ok": False, "issues": [{"rule": "camera_missing", "detail": cam_path}]}

    if shot.get("target"):
        occl = check_occlusion(stage, cam_path, shot["target"])
        if occl["occluded"]:
            issues.append({
                "rule": "occlusion",
                "detail": f"{shot['target']} is blocked from {cam_path} by "
                          f"{occl['blockers'][0]['path']}",
            })

    for prop_path in shot.get("watch_intrusion", []):
        intrusion = check_frame_intrusion(stage, cam_path, prop_path)
        if intrusion["in_frame"]:
            issues.append({
                "rule": "frame_intrusion",
                "detail": f"{prop_path} is visible in frame from {cam_path}",
            })

    for pair in shot.get("clearance_pairs", []):
        clr = check_clearance(stage, pair["a"], pair["b"], pair.get("min_distance", 0.0))
        if not clr["ok"]:
            issues.append({
                "rule": "clearance",
                "detail": f"{pair['a']} and {pair['b']} are too close "
                          f"({clr['distance']}m, need {clr['min_required']}m)",
            })

    return {"ok": len(issues) == 0, "issue_count": len(issues), "issues": issues}


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    stage = Usd.Stage.Open("set.usda")

    print("=== inspect_scene ===")
    summary = inspect_scene(stage)
    print(f"{summary['prim_count']} prims (truncated={summary['truncated']})")
    for p in summary["prims"]:
        print(f"  {p['path']:35s} {p['type']}")

    shots = [
        {
            "name": "Shot 1 - CamMedium on actor",
            "camera": "/World/Cameras/CamMedium",
            "target": "/World/ActorMarkA",
            "watch_intrusion": ["/World/Rig/LightStandA"],
        },
        {
            "name": "Shot 2 - CamWide establishing",
            "camera": "/World/Cameras/CamWide",
            "target": "/World/ActorMarkA",
            "watch_intrusion": ["/World/Rig/LightStandA"],
            "clearance_pairs": [
                {"a": "/World/Props/CrateA", "b": "/World/Props/CrateB", "min_distance": 0.5},
            ],
        },
        {
            "name": "Shot 3 - CamCloseup",
            "camera": "/World/Cameras/CamCloseup",
            "target": "/World/ActorMarkA",
            "clearance_pairs": [
                {"a": "/World/Cameras/CamCloseup", "b": "/World/Room/WallWest", "min_distance": 0.3},
            ],
        },
    ]

    print("\n=== validate_shot ===")
    for shot in shots:
        result = validate_shot(stage, shot)
        status = "PASS" if result["ok"] else "FAIL"
        print(f"\n[{status}] {shot['name']}")
        for issue in result["issues"]:
            print(f"    - ({issue['rule']}) {issue['detail']}")