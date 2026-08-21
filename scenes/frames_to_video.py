"""
frames_to_video.py

Stitches the frame_####.png sequence from standalone_render_and_validate.py
(run with --frames all) into an MP4. Thin wrapper around ffmpeg -- no
Isaac Sim/omni.* needed, runs anywhere ffmpeg is installed, including
right where the PNGs already are on the AWS instance (no need to
download frames just to build the clip).

Usage:
  python3 frames_to_video.py --frames_dir /home/ubuntu/render_out --fps 24 --out shot.mp4

Requires ffmpeg on PATH (Ubuntu: sudo apt install ffmpeg).
"""

import argparse
import glob
import os
import subprocess
import sys


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--frames_dir", required=True, help="Directory containing frame_####.png files")
    p.add_argument("--pattern", default="frame_%04d.png", help="printf-style filename pattern (must match what standalone_render_and_validate.py wrote)")
    p.add_argument("--fps", type=float, default=24.0, help="Playback frame rate of the output video")
    p.add_argument("--out", required=True, help="Output video path, e.g. shot.mp4")
    return p.parse_args()


def main():
    args = parse_args()

    existing = sorted(glob.glob(os.path.join(args.frames_dir, "frame_*.png")))
    if not existing:
        print(f"No frame_*.png files found in {args.frames_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(existing)} frames, first={os.path.basename(existing[0])} last={os.path.basename(existing[-1])}")

    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(args.fps),
        "-i", os.path.join(args.frames_dir, args.pattern),
        "-pix_fmt", "yuv420p",   # widest player/codec compatibility
        "-c:v", "libx264",
        args.out,
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"Saved {args.out}")


if __name__ == "__main__":
    main()
