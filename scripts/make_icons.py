"""Generate PNG icons for the web app manifest + iOS apple-touch-icon.

Square raccoon-in-medallion, dark background. Produces:
- site/icon-180.png   (apple-touch-icon for iPhone)
- site/icon-192.png   (manifest, Android home screen)
- site/icon-512.png   (manifest, splash / high-DPI)
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

BG = "#0e1013"
FACE = "#8f8d83"
STRIPE = "#ebe7da"
EAR = "#4a4a46"
RED = "#d85c3f"  # match PANDAMONIUM tier color for a bold icon read
DARK = "#0e1013"


def draw_raccoon(ax, cx: float, cy: float, scale: float) -> None:
    s = scale
    # ears (triangles)
    ax.add_patch(mpatches.Polygon(
        [(cx - 1.0 * s, cy + 0.2 * s), (cx - 0.7 * s, cy + 1.4 * s), (cx - 0.1 * s, cy + 0.3 * s)],
        color=EAR, zorder=1))
    ax.add_patch(mpatches.Polygon(
        [(cx + 1.0 * s, cy + 0.2 * s), (cx + 0.7 * s, cy + 1.4 * s), (cx + 0.1 * s, cy + 0.3 * s)],
        color=EAR, zorder=1))
    # face
    ax.add_patch(mpatches.Ellipse((cx, cy), 2.1 * s, 2.3 * s, color=FACE, zorder=2))
    # forehead stripe
    ax.add_patch(mpatches.Polygon(
        [(cx - 0.22 * s, cy + 1.0 * s), (cx + 0.22 * s, cy + 1.0 * s),
         (cx + 0.15 * s, cy - 0.4 * s), (cx - 0.15 * s, cy - 0.4 * s)],
        color=STRIPE, zorder=3))
    # mask (use PANDAMONIUM red for strong icon read)
    ax.add_patch(mpatches.FancyBboxPatch(
        (cx - 1.0 * s, cy + 0.05 * s), 2.0 * s, 0.55 * s,
        boxstyle="round,pad=0.02,rounding_size=0.2",
        color=RED, zorder=4))
    # eyes
    ax.add_patch(mpatches.Ellipse((cx - 0.55 * s, cy + 0.32 * s), 0.2 * s, 0.24 * s, color="#f5f3e8", zorder=5))
    ax.add_patch(mpatches.Ellipse((cx + 0.55 * s, cy + 0.32 * s), 0.2 * s, 0.24 * s, color="#f5f3e8", zorder=5))
    ax.add_patch(mpatches.Ellipse((cx - 0.55 * s, cy + 0.32 * s), 0.08 * s, 0.11 * s, color=DARK, zorder=6))
    ax.add_patch(mpatches.Ellipse((cx + 0.55 * s, cy + 0.32 * s), 0.08 * s, 0.11 * s, color=DARK, zorder=6))
    # snout
    ax.add_patch(mpatches.Ellipse((cx, cy - 0.75 * s), 0.9 * s, 0.55 * s, color="#f1eddf", zorder=5))
    # nose
    ax.add_patch(mpatches.Ellipse((cx, cy - 0.52 * s), 0.22 * s, 0.15 * s, color=DARK, zorder=7))


def render_icon(size: int, out: Path) -> None:
    # Build the figure at the exact target pixel size. No bbox_inches="tight" —
    # iOS and manifest tooling care about the actual nominal dimensions.
    fig = plt.figure(figsize=(size / 100, size / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    # Medallion ring
    ax.add_patch(mpatches.Circle((5, 5), 4.3, fill=False, edgecolor=EAR, linewidth=max(2, size / 80)))
    # Raccoon face centered and large
    draw_raccoon(ax, 5, 5, scale=1.9)
    fig.savefig(out, dpi=100, facecolor=BG)
    plt.close(fig)
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")


def main() -> None:
    for size in (180, 192, 512):
        render_icon(size, SITE / f"icon-{size}.png")


if __name__ == "__main__":
    main()
