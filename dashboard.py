"""
RBI Gross Bank Credit Dashboard
================================
Run: streamlit run dashboard.py
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
from parser import read_parsed_csv

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="RBI Bank Credit", layout="wide", page_icon="🏦")

# ── Named colours for well-known series ───────────────────────────────────────
NAMED_COLORS = {
    "Bank Credit":     "#1f77b4",
    "Food Credit":     "#aec7e8",
    "Non-food Credit": "#17becf",
    "Agriculture":     "#2ca02c",
    "Industry":        "#d62728",
    "Services":        "#9467bd",
    "Personal Loans":  "#ff7f0e",
}
QUAL = px.colors.qualitative.Plotly + px.colors.qualitative.D3


def assign_colors(codes: list, labels: dict) -> dict:
    cmap, qi = {}, 0
    for code in codes:
        name = labels.get(code, code)
        if name in NAMED_COLORS:
            cmap[code] = NAMED_COLORS[name]
        else:
            cmap[code] = QUAL[qi % len(QUAL)]
            qi += 1
    return cmap


# ── Data loading ──────────────────────────────────────────────────────────────
@st.cache_data
def load_data() -> pd.DataFrame:
    path = Path(__file__).parent / "consolidated" / "consolidated_long.csv"
    df = read_parsed_csv(str(path))
    df["date"] = pd.to_datetime(df["date"])
    df["outstanding_cr"] = pd.to_numeric(df["outstanding_cr"], errors="coerce")
    return df


@st.cache_data
def compute_growth(data_df: pd.DataFrame, method: str) -> pd.DataFrame:
    """Return growth_pct per (statement, code, date).

    Note: data_df is hashed for caching — keep slices small.
    method: 'yoy' | 'fy'
    """
    dates = sorted(data_df["date"].unique())
    pairs = []
    for d in dates:
        if method == "yoy":
            target = d - pd.DateOffset(years=1)
            cands = [x for x in dates if x != d]
            if not cands:
                continue
            best = min(cands, key=lambda x: abs((x - target).days))
            if abs((best - target).days) <= 30:
                pairs.append((d, best))
        else:  # fy
            mend = [x for x in dates if x.month == 3 and x < d]
            if mend:
                pairs.append((d, max(mend)))

    rows = []
    for curr, prev in pairs:
        cv = data_df[data_df["date"] == curr].set_index(["statement", "code"])["outstanding_cr"]
        pv = data_df[data_df["date"] == prev].set_index(["statement", "code"])["outstanding_cr"]
        pct = ((cv - pv) / pv * 100).reset_index()
        pct.columns = ["statement", "code", "growth_pct"]
        pct["date"] = curr
        rows.append(pct)

    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


# ── Helpers ───────────────────────────────────────────────────────────────────
def fmt_cr(v: float) -> str:
    return f"₹{v / 1e5:.2f} L Cr"


def date_label(ts) -> str:
    return pd.Timestamp(ts).strftime("%b %Y")


def sort_codes_numeric(codes: list) -> list:
    """Sort dotted numeric codes correctly (3.10 > 3.9)."""
    def key(c):
        try:
            return tuple(int(p) for p in str(c).split("."))
        except ValueError:
            return (float("inf"),)
    return sorted(codes, key=key)


def children_of(source_df: pd.DataFrame, parent_code: str,
                parent_stmt: str = "Statement 1",
                memo: bool = False) -> tuple:
    """Return (data, codes, labels) for direct children of parent_code."""
    mask = (
        (source_df["parent_code"] == parent_code) &
        (source_df["parent_statement"] == parent_stmt)
    )
    if not memo:
        mask &= ~source_df["is_priority_sector_memo"]
    data = source_df[mask].copy()
    cl = (
        data[["code", "sector"]].drop_duplicates()
        .set_index("code")["sector"].to_dict()
    )
    codes = sort_codes_numeric(list(cl.keys()))
    return data, codes, cl


# ── Core section renderer ─────────────────────────────────────────────────────
def render_section(sec_idx: int, data: pd.DataFrame, codes: list,
                   labels: dict, pct_label: str = "% Share",
                   dist_codes: list = None) -> None:
    """Render Trend + Distribution sub-tabs for one section.

    dist_codes: if provided, use this subset for the Distribution tab only.
                Useful when the trend has an aggregate total line (e.g. Bank
                Credit = Food + Non-food) that must not be double-counted in
                the stacked bar.
    """
    if not codes or data.empty:
        st.info("No data available for this section.")
        return

    # Distribution may use a different (sub)set of codes than Trend
    _dist_codes = dist_codes if dist_codes is not None else codes

    cmap = assign_colors(codes, labels)
    t_trend, t_dist = st.tabs(["📈  Trend", "📊  Distribution"])

    # ── Trend ─────────────────────────────────────────────────────────────────
    with t_trend:
        c1, c2, _ = st.columns([2, 2, 4])
        with c1:
            view = st.radio(
                "View", ["Absolute", "Growth Rate"],
                horizontal=True, label_visibility="collapsed",
                key=f"view_{sec_idx}",
            )
        with c2:
            gm = None
            if view == "Growth Rate":
                gm = st.radio(
                    "Growth", ["YoY", "FY"],
                    horizontal=True, label_visibility="collapsed",
                    key=f"gm_{sec_idx}",
                )

        fig = go.Figure()

        if view == "Absolute":
            for code in codes:
                seg = data[data["code"] == code].sort_values("date")
                if seg.empty:
                    continue
                name = labels.get(code, code)
                fig.add_trace(go.Scatter(
                    x=seg["date"], y=seg["outstanding_cr"],
                    mode="lines+markers", name=name,
                    line=dict(color=cmap.get(code), width=2),
                    hovertemplate=(
                        f"<b>{name}</b><br>%{{x|%b %Y}}<br>"
                        "₹%{y:,.0f} Cr<extra></extra>"
                    ),
                ))
            fig.update_layout(yaxis_title="₹ Crore")

        else:  # Growth Rate
            gdf = compute_growth(data, "yoy" if gm == "YoY" else "fy")
            if gdf.empty:
                st.warning("Not enough data to compute growth rates.")
            else:
                for code in codes:
                    seg = gdf[gdf["code"] == code].sort_values("date")
                    if seg.empty:
                        continue
                    name = labels.get(code, code)
                    fig.add_trace(go.Scatter(
                        x=seg["date"], y=seg["growth_pct"],
                        mode="lines+markers", name=name,
                        line=dict(color=cmap.get(code), width=2),
                        hovertemplate=(
                            f"<b>{name}</b><br>%{{x|%b %Y}}<br>"
                            "%{y:.1f}%<extra></extra>"
                        ),
                    ))
                fig.add_hline(y=0, line_dash="dash", line_color="grey", line_width=1)
                fig.update_layout(yaxis_title=f"{gm} Growth (%)")

        fig.update_layout(
            height=420,
            margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            hovermode="x unified",
            xaxis=dict(tickformat="%b %Y"),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Distribution ──────────────────────────────────────────────────────────
    with t_dist:
        c1, _ = st.columns([3, 5])
        with c1:
            dist_mode = st.radio(
                "Show as", ["₹ Crore", pct_label],
                horizontal=True, label_visibility="collapsed",
                key=f"dist_{sec_idx}",
            )

        # Build per-date, per-code values (use _dist_codes, not codes)
        rows = []
        for d in all_dates:
            sl = data[data["date"] == d]
            for code in _dist_codes:
                v = sl[sl["code"] == code]["outstanding_cr"].values
                rows.append({
                    "date": d,
                    "code": code,
                    "sector": labels.get(code, code),
                    "value": float(v[0]) if len(v) else 0.0,
                })
        ddf = pd.DataFrame(rows)

        if dist_mode != "₹ Crore":
            totals = ddf.groupby("date")["value"].transform("sum")
            ddf["plot_val"] = ddf["value"] / totals.replace(0, float("nan")) * 100
            y_label = pct_label
            hover_fmt = "%{y:.1f}%"
            yax = dict(title=y_label, range=[0, 100])
        else:
            ddf["plot_val"] = ddf["value"]
            y_label = "₹ Crore"
            hover_fmt = "₹%{y:,.0f} Cr"
            yax = dict(title=y_label)

        fig2 = go.Figure()
        for code in _dist_codes:
            seg = ddf[ddf["code"] == code].sort_values("date")
            name = labels.get(code, code)
            fig2.add_trace(go.Bar(
                x=seg["date"].apply(date_label),
                y=seg["plot_val"],
                name=name,
                marker_color=cmap.get(code),
                hovertemplate=f"<b>{name}</b><br>%{{x}}<br>{hover_fmt}<extra></extra>",
            ))

        fig2.update_layout(
            barmode="stack",
            height=420,
            margin=dict(l=0, r=0, t=10, b=0),
            yaxis=yax,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            hovermode="x unified",
        )
        st.plotly_chart(fig2, use_container_width=True)

        # Summary table at latest date
        st.caption(f"Breakdown at **{date_label(latest_date)}**")
        tbl = ddf[ddf["date"] == latest_date].copy()
        total = tbl["value"].sum()
        tbl["Share (%)"] = (
            (tbl["value"] / total * 100).round(1) if total else 0.0
        )
        tbl["₹ Crore"] = tbl["value"].apply(lambda v: f"{v:,.0f}")
        st.dataframe(
            tbl[["sector", "₹ Crore", "Share (%)"]].rename(columns={"sector": "Sector"}),
            hide_index=True,
            use_container_width=True,
        )


# ── Load & global slices ──────────────────────────────────────────────────────
df = load_data()
s1 = df[df["statement"] == "Statement 1"]
s2 = df[df["statement"] == "Statement 2"]
all_dates = sorted(df["date"].unique())
latest_date = all_dates[-1]

# ── Page header ───────────────────────────────────────────────────────────────
st.title("RBI Gross Bank Credit")
st.caption(
    f"Source: RBI Sector/Industry-wise Bank Credit (SIBC) Return  |  "
    f"Values in ₹ Crore  |  Latest data: **{date_label(latest_date)}**"
)
latest_bc = s1[(s1["code"] == "I") & (s1["date"] == latest_date)]["outstanding_cr"].values[0]
st.metric("Total Bank Credit", fmt_cr(latest_bc))
st.divider()

# ── 7 top-level tabs ──────────────────────────────────────────────────────────
tabs = st.tabs([
    "🏦 Bank Credit",
    "📊 Main Sectors",
    "🏭 Industry by Size",
    "🛎 Services",
    "💳 Personal Loans",
    "⭐ Priority Sector",
    "🔩 Industry by Type",
])

# ── 1. Bank Credit — Food vs Non-food ────────────────────────────────────────
with tabs[0]:
    codes1  = ["I", "II", "III"]
    labels1 = {"I": "Bank Credit", "II": "Food Credit", "III": "Non-food Credit"}
    data1   = s1[s1["code"].isin(codes1) & ~s1["is_priority_sector_memo"]].copy()
    # Trend shows all 3 lines; Distribution only stacks Food + Non-food
    # (Bank Credit = Food + Non-food, so including I would double-count)
    render_section(0, data1, codes1, labels1, pct_label="% of Bank Credit",
                   dist_codes=["II", "III"])

# ── 2. Main Sectors ───────────────────────────────────────────────────────────
with tabs[1]:
    codes2  = ["1", "2", "3", "4"]
    labels2 = {"1": "Agriculture", "2": "Industry", "3": "Services", "4": "Personal Loans"}
    data2   = s1[s1["code"].isin(codes2) & ~s1["is_priority_sector_memo"]].copy()
    render_section(1, data2, codes2, labels2, pct_label="% Share")

# ── 3. Industry by Size ───────────────────────────────────────────────────────
with tabs[2]:
    data3, codes3, labels3 = children_of(s1, "2")
    render_section(2, data3, codes3, labels3, pct_label="% of Industry")

# ── 4. Services constituents ──────────────────────────────────────────────────
with tabs[3]:
    data4, codes4, labels4 = children_of(s1, "3")
    render_section(3, data4, codes4, labels4, pct_label="% of Services")

# ── 5. Personal Loans constituents ───────────────────────────────────────────
with tabs[4]:
    data5, codes5, labels5 = children_of(s1, "4")
    render_section(4, data5, codes5, labels5, pct_label="% of Personal Loans")

# ── 6. Priority Sector ────────────────────────────────────────────────────────
with tabs[5]:
    data6 = s1[s1["is_priority_sector_memo"].astype(bool)].copy()
    cl6   = (
        data6[["code", "sector"]].drop_duplicates()
        .set_index("code")["sector"].to_dict()
    )
    # Sort priority sector codes in roman numeral order
    roman_order = ["i","ii","iii","iv","v","vi","vii","viii","ix","x",
                   "xi","xii","xiii","xiv","xv"]
    codes6 = sorted(cl6.keys(), key=lambda c: roman_order.index(c) if c in roman_order else 99)
    render_section(5, data6, codes6, cl6, pct_label="% of Priority Sector")

# ── 7. Industry by Type (Statement 2) ────────────────────────────────────────
with tabs[6]:
    data7, codes7, labels7 = children_of(s2, "2", parent_stmt="Statement 1")

    # ── Filter controls ───────────────────────────────────────────────────────
    # Compute each industry's % share at latest date (used for both filter modes)
    latest_slice = data7[data7["date"] == latest_date]
    total7 = latest_slice["outstanding_cr"].sum()
    shares7 = {
        code: (
            latest_slice[latest_slice["code"] == code]["outstanding_cr"].values[0] / total7 * 100
            if len(latest_slice[latest_slice["code"] == code]) and total7 else 0.0
        )
        for code in codes7
    }

    # Industries ranked largest-to-smallest (used by both filter modes)
    codes7_by_size = sorted(codes7, key=lambda c: shares7[c], reverse=True)

    c1, c2, c3 = st.columns([2, 1, 5])
    with c1:
        filter_mode = st.radio(
            "Display", ["Top N", "≥ X% coverage", "All"],
            horizontal=True, label_visibility="collapsed",
            key="ind_type_filter",
        )
    with c2:
        if filter_mode == "Top N":
            n_val = st.number_input(
                "N", min_value=1, max_value=len(codes7), value=min(10, len(codes7)),
                step=1, key="ind_type_n", label_visibility="collapsed",
            )
            filtered_codes7 = sort_codes_numeric(codes7_by_size[:int(n_val)])

        elif filter_mode == "≥ X% coverage":
            x_val = st.number_input(
                "Coverage %", min_value=10.0, max_value=100.0, value=80.0,
                step=5.0, format="%.0f", key="ind_type_x", label_visibility="collapsed",
            )
            # Add industries largest-first until cumulative share reaches x_val
            cumulative, selected = 0.0, []
            for code in codes7_by_size:
                selected.append(code)
                cumulative += shares7[code]
                if cumulative >= x_val:
                    break
            filtered_codes7 = sort_codes_numeric(selected)

        else:
            filtered_codes7 = codes7

    # Caption: coverage of shown set + what's hidden
    with c3:
        shown_pct  = sum(shares7[c] for c in filtered_codes7)
        hidden     = len(codes7) - len(filtered_codes7)
        hidden_pct = 100.0 - shown_pct
        if hidden:
            st.caption(
                f"Showing **{len(filtered_codes7)}** of {len(codes7)} types "
                f"covering **{shown_pct:.1f}%** of Industry "
                f"— {hidden} others account for the remaining **{hidden_pct:.1f}%**."
            )
        else:
            st.caption(f"Showing all **{len(codes7)}** industry types.")

    filtered_data7   = data7[data7["code"].isin(filtered_codes7)]
    filtered_labels7 = {c: labels7[c] for c in filtered_codes7}
    render_section(6, filtered_data7, filtered_codes7, filtered_labels7, pct_label="% of Industry")
