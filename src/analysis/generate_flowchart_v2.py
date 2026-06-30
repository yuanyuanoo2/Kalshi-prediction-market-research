"""
Resume flowchart v2 — swimlane layout, two lanes, decision diamonds with feedback loops.
English, black/white, landscape, minimal text.
"""

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path

matplotlib.rcParams['font.family'] = 'sans-serif'
matplotlib.rcParams['font.sans-serif'] = ['Helvetica', 'Arial', 'DejaVu Sans', 'sans-serif']
matplotlib.rcParams['axes.unicode_minus'] = False

OUT_DIR = Path('/Users/yuanyuan/Desktop/Kalshi/outputs/figures')
OUT_DIR.mkdir(parents=True, exist_ok=True)

C_BLACK = '#1A1A1A'
C_LGRAY = '#888888'
C_WHITE = '#FFFFFF'
C_LANE1 = '#F8F8F8'
C_LANE2 = '#EEEEEE'


def box(ax, cx, cy, w, h, text, fontsize=7.8, bold=False, lw=1.1):
    ax.add_patch(mpatches.Rectangle(
        (cx - w/2, cy - h/2), w, h,
        facecolor=C_WHITE, edgecolor=C_BLACK, linewidth=lw, zorder=3))
    ax.text(cx, cy, text, ha='center', va='center', fontsize=fontsize,
            fontweight='bold' if bold else 'normal', color=C_BLACK, zorder=4,
            multialignment='center')


def diamond(ax, cx, cy, w, h, text, fontsize=7.5):
    pts = np.array([[cx, cy+h/2], [cx+w/2, cy], [cx, cy-h/2], [cx-w/2, cy]])
    ax.add_patch(plt.Polygon(pts, closed=True, facecolor=C_WHITE,
                             edgecolor=C_BLACK, linewidth=1.0, zorder=3))
    ax.text(cx, cy, text, ha='center', va='center', fontsize=fontsize,
            color=C_BLACK, zorder=4, multialignment='center')


def arr(ax, pts, lw=0.9):
    """Polyline with arrowhead at the last point."""
    for i in range(len(pts) - 2):
        ax.plot([pts[i][0], pts[i+1][0]], [pts[i][1], pts[i+1][1]],
                color=C_BLACK, lw=lw, zorder=2)
    ax.annotate('', xy=pts[-1], xytext=pts[-2],
                arrowprops=dict(arrowstyle='->', color=C_BLACK, lw=lw,
                                mutation_scale=9), zorder=2)


def lbl(ax, x, y, text, ha='center', fs=6.3):
    ax.text(x, y, text, ha=ha, va='center', fontsize=fs, color=C_LGRAY,
            multialignment=ha)


def main():
    fig, ax = plt.subplots(figsize=(11, 7))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 7)
    ax.axis('off')
    fig.patch.set_facecolor(C_WHITE)

    # ── Swimlane geometry ────────────────────────────────────────────────────
    LM, DIV, RM = 0.22, 5.0, 10.78
    BOT, HDR, TOP = 0.36, 6.28, 6.84
    LCX = (LM + DIV) / 2     # 2.61
    RCX = (DIV + RM) / 2     # 7.89

    # Lane fills
    ax.add_patch(mpatches.Rectangle((LM, BOT), DIV-LM, HDR-BOT,
        facecolor=C_LANE1, edgecolor='none', zorder=0))
    ax.add_patch(mpatches.Rectangle((DIV, BOT), RM-DIV, HDR-BOT,
        facecolor=C_LANE2, edgecolor='none', zorder=0))

    # Borders
    ax.add_patch(mpatches.Rectangle((LM, BOT), RM-LM, TOP-BOT,
        facecolor='none', edgecolor=C_BLACK, linewidth=1.3, zorder=1))
    ax.plot([DIV, DIV], [BOT, TOP], color=C_BLACK, lw=1.0, zorder=1)
    ax.plot([LM, RM], [HDR, HDR], color=C_BLACK, lw=1.0, zorder=1)

    # Lane headers
    ax.text(LCX, (HDR+TOP)/2, 'Me', ha='center', va='center',
            fontsize=12, fontweight='bold', color=C_BLACK, zorder=4)
    ax.text(RCX, (HDR+TOP)/2, 'AI  (Claude Code)', ha='center', va='center',
            fontsize=12, fontweight='bold', color=C_BLACK, zorder=4)

    # ── Sizes & y-coordinates ────────────────────────────────────────────────
    BW, BH = 3.30, 0.56
    DW, DH = 2.50, 0.56

    Y1  = 5.80   # Row 1: define question / collect data
    Y3  = 4.68   # Diamond 1: model accurate?
    Y4  = 3.60   # Compare + backtest
    Y5  = 2.52   # Diamond 2: result makes sense?
    Y6  = 1.52   # Review + decide
    Y7  = 0.70   # Final box

    RAIL_R = RM - 0.30   # 10.48  right feedback rail (AI lane, loop-1)

    # ── [Me] Define research question ────────────────────────────────────────
    box(ax, LCX, Y1, BW, BH,
        'Define research question\n"Can I find a tradeable price gap\nin a sports prediction market?"',
        fontsize=7.4)

    # → right to AI lane
    arr(ax, [(LCX + BW/2, Y1), (RCX - BW/2, Y1)])

    # ── [AI] Collect data + build model ──────────────────────────────────────
    box(ax, RCX, Y1, BW, BH, 'Collect data\n+ build prediction model', fontsize=7.5)

    # ↓ to diamond 1
    arr(ax, [(RCX, Y1 - BH/2), (RCX, Y3 + DH/2)])

    # ── Diamond 1: Model accurate enough? ───────────────────────────────────
    diamond(ax, RCX, Y3, DW, DH, 'Model\naccurate enough?')

    # yes ↓
    lbl(ax, RCX + 0.14, Y3 - DH/2 - 0.14, 'yes', ha='left')
    arr(ax, [(RCX, Y3 - DH/2), (RCX, Y4 + BH/2)])

    # no → right rail → up → back into node-2 right side
    lbl(ax, RCX + DW/2 + 0.10, Y3 + 0.10, 'no', ha='left')
    arr(ax, [
        (RCX + DW/2, Y3),
        (RAIL_R, Y3),
        (RAIL_R, Y1),
        (RCX + BW/2, Y1),
    ])
    lbl(ax, (RCX + BW/2 + RAIL_R) / 2, (Y3 + Y1) / 2, 'Investigate\n& revise', ha='center')

    # ── [AI] Compare model output to market prices + run backtest ────────────
    box(ax, RCX, Y4, BW, BH,
        'Compare model output to market prices\n+ run backtest', fontsize=7.5)

    # ↓ to diamond 2
    arr(ax, [(RCX, Y4 - BH/2), (RCX, Y5 + DH/2)])

    # ── Diamond 2: Result makes sense? ───────────────────────────────────────
    diamond(ax, RCX, Y5, DW, DH, 'Result\nmakes sense?')

    # yes ↓  (exits bottom of diamond → down to Y6 level → left into Review)
    lbl(ax, RCX + 0.14, Y5 - DH/2 - 0.14, 'yes', ha='left')
    arr(ax, [
        (RCX, Y5 - DH/2),
        (RCX, Y6),
        (LCX + BW/2, Y6),
    ])

    # no ← (exits left of diamond → [Me] Flag anomaly → up → right to node-4)
    lbl(ax, RCX - DW/2 - 0.10, Y5 + 0.14, 'no', ha='right')

    FLAG_W, FLAG_H = 1.90, 0.46
    FLAG_CX = LCX + 0.25    # 2.86

    # Arrow: diamond left → flag box right edge
    arr(ax, [(RCX - DW/2, Y5), (FLAG_CX + FLAG_W/2, Y5)])

    # Flag anomaly box in Me lane
    box(ax, FLAG_CX, Y5, FLAG_W, FLAG_H,
        'Flag anomaly,\nask AI to re-verify', fontsize=7.0, lw=0.9)

    # Re-check path: flag box top → up to Y4 level → right → node-4 left edge
    arr(ax, [
        (FLAG_CX, Y5 + FLAG_H/2),
        (FLAG_CX, Y4),
        (RCX - BW/2, Y4),
    ])
    lbl(ax, FLAG_CX + 0.14, (Y5 + FLAG_H/2 + Y4) / 2 + 0.08, 'Re-check data & logic', ha='left')

    # ── [Me] Review final result ──────────────────────────────────────────────
    box(ax, LCX, Y6, BW, BH,
        'Review final result,\ndecide whether to accept conclusion', fontsize=7.5)

    # ↓ to final box
    arr(ax, [(LCX, Y6 - BH/2), (LCX, Y7 + BH/2)])

    # ── Final box (spans both lanes) ─────────────────────────────────────────
    FCX = (LM + RM) / 2
    FBW = (RM - LM) - 0.44
    box(ax, FCX, Y7, FBW, BH,
        'Conclusion: strategy signal was real — but trading costs outweighed it.\nA complete, well-supported research finding.',
        fontsize=8.0, lw=1.5)

    # ── Caption ───────────────────────────────────────────────────────────────
    ax.text(FCX, 0.14,
            'AI executed the technical work.  '
            'I directed the research, reviewed results at each checkpoint, '
            'and decided when to revise or accept.',
            ha='center', va='center', fontsize=6.5, color=C_LGRAY, style='italic')

    # ── Save ──────────────────────────────────────────────────────────────────
    plt.tight_layout(pad=0.1)
    out_png = OUT_DIR / 'project_flowchart_v2.png'
    out_pdf = OUT_DIR / 'project_flowchart_v2.pdf'
    fig.savefig(out_png, dpi=300, bbox_inches='tight', facecolor='white')
    fig.savefig(out_pdf, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f'PNG: {out_png}')
    print(f'PDF: {out_pdf}')


if __name__ == '__main__':
    main()
