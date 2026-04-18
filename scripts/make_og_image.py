"""Generate the Open Graph / Twitter card preview image.

1200x630 PNG — the standard OG card size. Dark background, project title,
UNOFFICIAL stamp, simple raccoon mascot, URL. Committed to site/og-image.png
so social shares render with a proper preview.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.path import Path as MplPath

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "og-image.png"

BG = "#0e1013"
FG = "#e8e6df"
DIM = "#8a8680"
RED = "#d85c3f"
ACCENT = "#c8d18a"
FACE = "#8f8d83"
STRIPE = "#ebe7da"
EAR = "#4a4a46"
DARK = "#0e1013"


def draw_raccoon(ax, cx: float, cy: float, scale: float = 1.0) -> None:
    """Simplified raccoon face in matplotlib shapes. Scale in axis units."""
    s = scale

    def ellipse(x, y, w, h, color):
        ax.add_patch(mpatches.Ellipse((cx + x * s, cy + y * s),
                                       w * s, h * s, color=color, zorder=2))

    # ears (triangles)
    left_ear = mpatches.Polygon(
        [(cx - 1.0 * s, cy + 0.2 * s), (cx - 0.7 * s, cy + 1.4 * s), (cx - 0.1 * s, cy + 0.3 * s)],
        color=EAR, zorder=1)
    right_ear = mpatches.Polygon(
        [(cx + 1.0 * s, cy + 0.2 * s), (cx + 0.7 * s, cy + 1.4 * s), (cx + 0.1 * s, cy + 0.3 * s)],
        color=EAR, zorder=1)
    ax.add_patch(left_ear)
    ax.add_patch(right_ear)

    # face (ellipse, slightly pointy chin by stacking)
    ellipse(0, 0, 2.1, 2.3, FACE)
    # forehead stripe
    stripe = mpatches.Polygon(
        [(cx - 0.22 * s, cy + 1.0 * s), (cx + 0.22 * s, cy + 1.0 * s),
         (cx + 0.15 * s, cy - 0.4 * s), (cx - 0.15 * s, cy - 0.4 * s)],
        color=STRIPE, zorder=3)
    ax.add_patch(stripe)
    # bandit mask (red rectangle, curved with patches)
    mask = mpatches.FancyBboxPatch(
        (cx - 1.0 * s, cy + 0.05 * s), 2.0 * s, 0.55 * s,
        boxstyle="round,pad=0.02,rounding_size=0.2",
        color=RED, zorder=4)
    ax.add_patch(mask)
    # eyes
    ellipse(-0.55, 0.32, 0.2, 0.24, "#f5f3e8")
    ellipse(0.55, 0.32, 0.2, 0.24, "#f5f3e8")
    ellipse(-0.55, 0.32, 0.08, 0.11, DARK)
    ellipse(0.55, 0.32, 0.08, 0.11, DARK)
    # snout
    ellipse(0, -0.75, 0.9, 0.55, "#f1eddf")
    # nose
    ellipse(0, -0.52, 0.22, 0.15, DARK)


def main() -> None:
    fig, ax = plt.subplots(figsize=(12, 6.3), dpi=100)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6.3)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    # Decorative medallion ring around the raccoon (civic-crest echo)
    ring_cx, ring_cy = 9.6, 3.15
    ax.add_patch(mpatches.Circle((ring_cx, ring_cy), 2.05, fill=False,
                                 edgecolor=EAR, linewidth=2))
    ax.add_patch(mpatches.Circle((ring_cx, ring_cy), 1.9, fill=False,
                                 edgecolor="#2a2c30", linewidth=0.6))
    # cardinal dots
    for (dx, dy) in [(0, 2.05), (2.05, 0), (0, -2.05), (-2.05, 0)]:
        ax.add_patch(mpatches.Circle((ring_cx + dx, ring_cy + dy), 0.05,
                                     color=EAR))

    draw_raccoon(ax, ring_cx, ring_cy, scale=0.95)

    # Title
    ax.text(0.55, 4.5, "TORONTO RACCOON",
            fontsize=62, color=FG, weight="bold", family="sans-serif",
            ha="left", va="center")
    ax.text(0.55, 3.4, "ACTIVITY INDEX",
            fontsize=62, color=FG, weight="bold", family="sans-serif",
            ha="left", va="center")

    # Unofficial badge
    ax.text(0.55, 2.4, "· UNOFFICIAL ·",
            fontsize=22, color=RED, weight="bold", family="sans-serif",
            ha="left", va="center")

    # Tagline
    ax.text(0.55, 1.65, "A parody civic advisory system for the city's",
            fontsize=22, color=DIM, family="serif", ha="left", va="center")
    ax.text(0.55, 1.15, "unofficial mascot.",
            fontsize=22, color=DIM, family="serif", ha="left", va="center")

    # URL
    ax.text(0.55, 0.4, "raccoonindex.ca",
            fontsize=22, color=ACCENT, family="monospace",
            ha="left", va="center")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, facecolor=BG, dpi=100)
    plt.close(fig)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
