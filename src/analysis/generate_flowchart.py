"""
简历用项目流程图生成脚本

风格参考: images.png (极简黑白，细线条，专业印刷感)
输出: PNG (300 DPI) + PDF (矢量)
语言: 简体中文
"""

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
from pathlib import Path

# 中文字体设置
matplotlib.rcParams['font.family'] = 'sans-serif'
matplotlib.rcParams['font.sans-serif'] = [
    'PingFang SC', 'Heiti SC', 'STHeiti',
    'Hiragino Sans GB', 'Arial Unicode MS', 'sans-serif'
]
matplotlib.rcParams['axes.unicode_minus'] = False

OUT_DIR = Path('/Users/yuanyuan/Desktop/Kalshi/outputs/figures')
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 配色（贴近参考图：黑白+极浅灰，结论节点略深）──────────────────────────
C_WHITE    = '#FFFFFF'
C_NODE_BG  = '#FFFFFF'
C_NODE_EDGE= '#2A2A2A'
C_TEXT     = '#1A1A1A'
C_SUB      = '#4A4A4A'
C_STEP     = '#AAAAAA'
C_CONC_BG  = '#F2F2F2'   # 结论节点略深
C_CONC_EDG = '#111111'   # 结论节点边框更重
C_CHK_BG   = '#FAFAFA'
C_CHK_EDG  = '#AAAAAA'
C_CHK_TEXT = '#555555'
C_ARROW    = '#2A2A2A'
C_DIVIDER  = '#DDDDDD'
C_POS      = '#1B5E20'   # 深绿（正向指标，仅微量使用）
C_CONC_HL  = '#7B1A1A'   # 深红（结论关键句）


def rounded_box(ax, xl, yb, w, h, fc, ec, lw=1.2, ls='solid', r=0.07, z=2):
    patch = FancyBboxPatch(
        (xl, yb), w, h,
        boxstyle=f'round,pad={r}',
        facecolor=fc, edgecolor=ec, linewidth=lw, linestyle=ls, zorder=z
    )
    ax.add_patch(patch)


def arrow_down(ax, x, y_from, y_to):
    """从 y_from（上节点底部）向下画箭头到 y_to（下节点顶部）。"""
    ax.annotate(
        '', xy=(x, y_to + 0.03), xytext=(x, y_from - 0.03),
        arrowprops=dict(arrowstyle='->', color=C_ARROW, lw=1.0, mutation_scale=10),
        zorder=1
    )


def main():
    # ── 画布 ────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(7.5, 9.0))
    ax.set_xlim(0, 7.5)
    ax.set_ylim(0, 9.0)
    ax.axis('off')
    fig.patch.set_facecolor(C_WHITE)

    # ── 布局常量 ──────────────────────────────────────────────────────────
    # 主节点：左对齐偏中（为右侧 checker 留空间）
    NX_L = 0.30          # 主节点左边
    NX_R = 5.00          # 主节点右边
    NW   = NX_R - NX_L  # 宽度 4.70
    NC   = NX_L + NW/2  # 中心 x = 2.65

    CK_L  = 5.20         # checker 框左边
    CK_R  = 7.25         # checker 框右边
    CKW   = CK_R - CK_L # checker 宽度 2.05
    CKC   = CK_L + CKW/2

    # 节点：(y_bottom, height)
    N = [
        (7.15, 0.80),   # 节点 1 收集数据
        (5.80, 1.05),   # 节点 2 训练模型
        (4.55, 0.88),   # 节点 3 对比价格
        (3.30, 0.88),   # 节点 4 回测
        (1.00, 1.55),   # 节点 5 结论
    ]
    # 各节点中心 y
    NY = [yb + h/2 for yb, h in N]

    # ── 标题 ────────────────────────────────────────────────────────────
    ax.text(NC, 8.72, 'Kalshi NBA 预测市场量化研究 — 项目全流程',
            ha='center', va='center', fontsize=11, fontweight='bold', color=C_TEXT)
    ax.plot([NX_L, NX_R], [8.52, 8.52], color=C_DIVIDER, lw=0.8)

    # ── 节点 1：收集数据 ────────────────────────────────────────────────
    yb, h = N[0]
    rounded_box(ax, NX_L, yb, NW, h, C_NODE_BG, C_NODE_EDGE)
    ax.text(NX_L + 0.14, yb + h - 0.09, '01', fontsize=6, color=C_STEP, va='top')
    ax.text(NC, NY[0] + 0.12, '① 收集数据',
            ha='center', va='center', fontsize=9.5, fontweight='bold', color=C_TEXT)
    ax.text(NC, NY[0] - 0.18,
            'NBA历史比分（1,323场，668,207条记录）+ Kalshi预测市场成交数据（293,323笔）',
            ha='center', va='center', fontsize=7.2, color=C_SUB)

    arrow_down(ax, NC, yb, N[1][0] + N[1][1])

    # ── 节点 2：训练预测模型 ─────────────────────────────────────────────
    yb, h = N[1]
    rounded_box(ax, NX_L, yb, NW, h, C_NODE_BG, C_NODE_EDGE)
    ax.text(NX_L + 0.14, yb + h - 0.09, '02', fontsize=6, color=C_STEP, va='top')
    ax.text(NC, NY[1] + 0.26, '② 训练预测模型',
            ha='center', va='center', fontsize=9.5, fontweight='bold', color=C_TEXT)
    ax.text(NC, NY[1] + 0.01,
            'Logistic Regression，预测比赛实时胜率\n含赛前隐含胜率（Kalshi 开赛前最后成交价，全场固定）',
            ha='center', va='center', fontsize=7.2, color=C_SUB, linespacing=1.4)
    ax.text(NC, NY[1] - 0.29,
            '校准误差：9.8%（常规赛）/ 7.3%（季后赛）— 均通过验证阈值（<10%）',
            ha='center', va='center', fontsize=7.0, color=C_POS)

    # Checker 2
    cky = NY[1]; ckh = 0.60
    rounded_box(ax, CK_L, cky - ckh/2, CKW, ckh, C_CHK_BG, C_CHK_EDG,
                lw=0.8, ls='dashed', r=0.06)
    ax.plot([NX_R, CK_L], [cky, cky], color=C_CHK_EDG, lw=0.7, ls='--', zorder=1)
    ax.text(CKC, cky, '人工介入\n校准误差超标 → 分析根因\n判断补充「赛前实力」特征',
            ha='center', va='center', fontsize=6.2, color=C_CHK_TEXT, linespacing=1.35)

    arrow_down(ax, NC, yb, N[2][0] + N[2][1])

    # ── 节点 3：对比市场价格 ─────────────────────────────────────────────
    yb, h = N[2]
    rounded_box(ax, NX_L, yb, NW, h, C_NODE_BG, C_NODE_EDGE)
    ax.text(NX_L + 0.14, yb + h - 0.09, '03', fontsize=6, color=C_STEP, va='top')
    ax.text(NC, NY[2] + 0.16, '③ 对比市场价格',
            ha='center', va='center', fontsize=9.5, fontweight='bold', color=C_TEXT)
    ax.text(NC, NY[2] - 0.14,
            '计算模型胜率与市场价格的差距（价差 / spread）\n价差收敛时间中位数约 40–70 秒（过滤振荡噪声后）',
            ha='center', va='center', fontsize=7.2, color=C_SUB, linespacing=1.4)

    # Checker 3
    cky = NY[2]; ckh = 0.60
    rounded_box(ax, CK_L, cky - ckh/2, CKW, ckh, C_CHK_BG, C_CHK_EDG,
                lw=0.8, ls='dashed', r=0.06)
    ax.plot([NX_R, CK_L], [cky, cky], color=C_CHK_EDG, lw=0.7, ls='--', zorder=1)
    ax.text(CKC, cky, '人工介入\n统计异常（收敛时间≈1秒）\n→ 要求重新验证测量方法',
            ha='center', va='center', fontsize=6.2, color=C_CHK_TEXT, linespacing=1.35)

    arrow_down(ax, NC, yb, N[3][0] + N[3][1])

    # ── 节点 4：设计交易规则并回测 ─────────────────────────────────────
    yb, h = N[3]
    rounded_box(ax, NX_L, yb, NW, h, C_NODE_BG, C_NODE_EDGE)
    ax.text(NX_L + 0.14, yb + h - 0.09, '04', fontsize=6, color=C_STEP, va='top')
    ax.text(NC, NY[3] + 0.16, '④ 设计交易规则并回测',
            ha='center', va='center', fontsize=9.5, fontweight='bold', color=C_TEXT)
    ax.text(NC, NY[3] - 0.14,
            '严格区分训练集/验证集，避免过拟合\n扣费前胜率 59–67%，训练集与验证集方向一致',
            ha='center', va='center', fontsize=7.2, color=C_SUB, linespacing=1.4)

    # Checker 4
    cky = NY[3]; ckh = 0.60
    rounded_box(ax, CK_L, cky - ckh/2, CKW, ckh, C_CHK_BG, C_CHK_EDG,
                lw=0.8, ls='dashed', r=0.06)
    ax.plot([NX_R, CK_L], [cky, cky], color=C_CHK_EDG, lw=0.7, ls='--', zorder=1)
    ax.text(CKC, cky, '人工介入\n扣费后结果转负\n→ 确认接受，不再反复调参',
            ha='center', va='center', fontsize=6.2, color=C_CHK_TEXT, linespacing=1.35)

    arrow_down(ax, NC, yb, N[4][0] + N[4][1])

    # ── 节点 5：研究结论（略深背景、加粗边框）─────────────────────────
    yb, h = N[4]
    rounded_box(ax, NX_L, yb, NW, h, C_CONC_BG, C_CONC_EDG, lw=1.8)
    ax.text(NX_L + 0.14, yb + h - 0.09, '05', fontsize=6, color=C_STEP, va='top')
    ax.text(NC, yb + h - 0.26, '⑤ 研究结论',
            ha='center', va='center', fontsize=9.5, fontweight='bold', color=C_TEXT)
    # 分隔线
    ax.plot([NX_L + 0.15, NX_R - 0.15], [yb + h - 0.42, yb + h - 0.42],
            color=C_DIVIDER, lw=0.7)
    ax.text(NC, yb + h - 0.62,
            '策略预测方向准确（扣费前胜率 59–67%，训练集/验证集一致）',
            ha='center', va='center', fontsize=7.2, color=C_SUB)
    ax.text(NC, yb + h - 0.88,
            '手续费成本（约 $0.025 / 笔）约为可捕获收益（约 $0.012 / 笔）的 2 倍',
            ha='center', va='center', fontsize=7.2, color=C_SUB)
    ax.text(NC, yb + h - 1.17,
            '→ 扣费后无法盈利：Kalshi 手续费结构性地消耗了模型发现的定价偏差',
            ha='center', va='center', fontsize=7.5, color=C_CONC_HL, fontweight='bold')
    ax.text(NC, yb + h - 1.40,
            '这是有精确归因的研究结论，不是执行失败',
            ha='center', va='center', fontsize=6.8, color=C_SUB, style='italic')

    # ── 底部说明：Maker / Checker ──────────────────────────────────────
    ax.plot([NX_L, 7.25], [0.72, 0.72], color=C_DIVIDER, lw=0.6)
    ax.text(3.75, 0.52,
            '人工在关键节点介入审查 (Checker)  |  AI 负责执行代码与数据分析 (Maker)',
            ha='center', va='center', fontsize=5.8, color=C_CHK_TEXT)

    # ── 输出 ───────────────────────────────────────────────────────────
    plt.tight_layout(pad=0.2)

    out_png = OUT_DIR / 'project_flowchart.png'
    out_pdf = OUT_DIR / 'project_flowchart.pdf'
    fig.savefig(out_png, dpi=300, bbox_inches='tight', facecolor='white')
    fig.savefig(out_pdf, bbox_inches='tight', facecolor='white')
    plt.close()

    print(f'PNG (300 DPI): {out_png}')
    print(f'PDF (矢量):    {out_pdf}')


if __name__ == '__main__':
    main()
