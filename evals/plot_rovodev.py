"""
Generate boxplot + bar chart showing token compression for the Rovo Dev eval.

Uses API-reported token counts (no tiktoken needed).

Reads: evals/snapshots/results_rovodev.json
Writes:
  - evals/snapshots/results_rovodev.html  (interactive Plotly)
  - evals/snapshots/results_rovodev.png   (static export for README/PR)

Run:
  uv run --with plotly --with kaleido python evals/plot_rovodev.py
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

SNAPSHOT = Path(__file__).parent / "snapshots" / "results_rovodev.json"
HTML_OUT = Path(__file__).parent / "snapshots" / "results_rovodev.html"
PNG_OUT = Path(__file__).parent / "snapshots" / "results_rovodev.png"

ARM_COLORS = {
    "baseline": "#e74c3c",
    "terse": "#f39c12",
    "caveman": "#2ca02c",
}

ARM_LABELS = {
    "baseline": "Baseline (no prompt)",
    "terse": 'Terse ("Answer concisely.")',
    "caveman": "Caveman",
}


def main() -> None:
    data = json.loads(SNAPSHOT.read_text())
    run_log = data["metadata"]["run_log"]
    meta = data["metadata"]

    # Group by arm
    arms: dict[str, list[dict]] = {}
    for entry in run_log:
        arms.setdefault(entry["arm"], []).append(entry)

    arm_order = ["baseline", "terse", "caveman"]
    arm_order = [a for a in arm_order if a in arms]

    # ── Figure 1: Boxplot — tokens per response by arm ──────────
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=(
            "Tokens per Response (distribution)",
            "Total Tokens by Arm",
        ),
        column_widths=[0.6, 0.4],
        horizontal_spacing=0.12,
    )

    # Boxplot
    for arm in arm_order:
        tokens = [e["output_tokens"] for e in arms[arm]]
        fig.add_trace(
            go.Box(
                y=tokens,
                name=ARM_LABELS.get(arm, arm),
                boxpoints="all",
                jitter=0.4,
                pointpos=0,
                marker=dict(color=ARM_COLORS.get(arm, "#999"), size=8, opacity=0.7),
                line=dict(color="#2c3e50", width=2),
                fillcolor=f"rgba({','.join(str(int(ARM_COLORS.get(arm, '#999')[i:i+2], 16)) for i in (1, 3, 5))}, 0.25)",
                boxmean=True,
                hovertemplate="<b>%{x}</b><br>%{y} tokens<extra></extra>",
            ),
            row=1, col=1,
        )

    # Bar chart — totals
    totals = []
    avgs = []
    for arm in arm_order:
        tokens = [e["output_tokens"] for e in arms[arm]]
        totals.append(sum(tokens))
        avgs.append(statistics.mean(tokens))

    baseline_total = totals[0] if totals else 1

    fig.add_trace(
        go.Bar(
            x=[ARM_LABELS.get(a, a) for a in arm_order],
            y=totals,
            marker_color=[ARM_COLORS.get(a, "#999") for a in arm_order],
            text=[
                f"{t:,} tokens<br>({(1 - t / baseline_total) * 100:.0f}% saved)"
                if i > 0 else f"{t:,} tokens"
                for i, t in enumerate(totals)
            ],
            textposition="outside",
            textfont=dict(size=12),
            hovertemplate="<b>%{x}</b><br>%{y:,} tokens<extra></extra>",
            showlegend=False,
        ),
        row=1, col=2,
    )

    n_prompts = len(arms.get("baseline", []))
    fig.update_layout(
        title=dict(
            text=(
                f"<b>Caveman on Rovo Dev: Token Compression Results</b><br>"
                f"<sub>{meta.get('cli', 'Rovo Dev')} · "
                f"n={n_prompts} prompts · 3 arms · "
                f"API-reported token counts · session reset between prompts</sub>"
            ),
            x=0.5,
            xanchor="center",
        ),
        yaxis=dict(
            title="Tokens per response",
            gridcolor="rgba(0,0,0,0.08)",
        ),
        yaxis2=dict(
            title="Total tokens",
            gridcolor="rgba(0,0,0,0.08)",
        ),
        plot_bgcolor="white",
        height=600,
        width=1200,
        margin=dict(l=80, r=80, t=120, b=100),
        showlegend=False,
    )

    # Savings annotations on boxplot (added after update_layout to avoid being wiped)
    baseline_tokens = [e["output_tokens"] for e in arms.get("baseline", [])]
    baseline_avg = statistics.mean(baseline_tokens) if baseline_tokens else 1

    for arm in arm_order:
        if arm == "baseline":
            continue
        tokens = [e["output_tokens"] for e in arms[arm]]
        avg = statistics.mean(tokens)
        saving = (1 - avg / baseline_avg) * 100
        fig.add_annotation(
            x=ARM_LABELS.get(arm, arm),
            y=max(tokens),
            text=f"<b>-{saving:.0f}%</b>",
            showarrow=False,
            yshift=25,
            font=dict(size=16, color=ARM_COLORS.get(arm, "#999")),
            xref="x1", yref="y1",
        )

    # Legend annotation
    fig.add_annotation(
        x=0,
        y=-0.15,
        xref="paper",
        yref="paper",
        xanchor="left",
        showarrow=False,
        font=dict(size=11, color="#555"),
        text=(
            "<b>box</b> = IQR (middle 50%) · "
            "<b>line in box</b> = median · "
            "<b>dashed line</b> = mean · "
            "<b>dots</b> = individual prompts"
        ),
    )

    fig.write_html(HTML_OUT)
    print(f"Wrote {HTML_OUT}")

    try:
        fig.write_image(PNG_OUT, scale=2)
        print(f"Wrote {PNG_OUT}")
    except Exception as e:
        print(f"PNG export failed (install kaleido): {e}")
        print(f"HTML still available at {HTML_OUT}")


if __name__ == "__main__":
    main()
