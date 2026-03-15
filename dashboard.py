"""
RBI Gross Bank Credit Dashboard
================================
Single scrollable page. Two top-level tabs: Trend | Distribution.
Run: streamlit run dashboard.py
"""

import math
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent))
from parser import read_parsed_csv

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="RBI Bank Credit", layout="wide", page_icon="🏦")

# ── Theme state (default: light / beige) ──────────────────────────────────────
_dark = st.session_state.get("dark_mode", False)

THEME = (
    dict(                                   # ── dark ──
        bg_page      = "#0e1117",
        bg_card      = "#141728",
        border_card  = "#2a2f4a",
        shadow       = "rgba(0,0,0,0.4)",
        grid         = "#1e2240",
        font         = "#c8cfe8",
        tab_border   = "#2a2f4a",
        hline        = "#555555",
    ) if _dark else
    dict(                                   # ── light / beige ──
        bg_page      = "#faf6ef",
        bg_card      = "#fffcf5",
        border_card  = "#e4d9c8",
        shadow       = "rgba(120,90,40,0.08)",
        grid         = "#e8ddd0",
        font         = "#2c1e0f",
        tab_border   = "#e4d9c8",
        hline        = "#bbbbbb",
    )
)

# Extra overrides needed when forcing dark on top of Streamlit's light base
_dark_extra = f"""
.stApp,
[data-testid="stMain"],
[data-testid="block-container"],
[data-testid="stMainBlockContainer"] {{
    background-color: {THEME['bg_page']} !important;
    color: {THEME['font']} !important;
}}
h1, h2, h3, h4, h5, h6 {{ color: {THEME['font']} !important; }}
p, span,
[data-testid="stMarkdownContainer"] p,
[data-testid="stMetricLabel"] > div,
[data-testid="stMetricValue"] > div,
[data-testid="stMetricDelta"],
[data-testid="stCaptionContainer"] p,
[data-testid="stRadio"] label,
[data-testid="stNumberInput"] label
{{ color: {THEME['font']} !important; }}
hr {{ border-color: {THEME['border_card']} !important; }}
[data-testid="stNumberInput"] input {{
    color: {THEME['font']} !important;
    background-color: #1e2240 !important;
    border-color: #2a2f4a !important;
}}
[data-baseweb="tab"] {{ color: {THEME['font']} !important; }}
[data-testid="stDataFrameResizable"] {{ background-color: #1e2240 !important; }}
""" if _dark else f"""
.stApp {{
    background-color: {THEME['bg_page']} !important;
}}
"""

# ── Inject CSS ────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
{_dark_extra}

/* ── Card containers (only bordered st.container, not plain wrappers/columns) ── */
[data-testid="stVerticalBlockBorderWrapper"]:not(.st-emotion-cache-0) {{
    background-color: {THEME['bg_card']} !important;
    border: 1px solid {THEME['border_card']} !important;
    border-radius: 14px !important;
    box-shadow: 0 4px 18px {THEME['shadow']} !important;
}}

/* ── Tabs bar ── */
[data-baseweb="tab-list"] {{
    gap: 6px;
    border-bottom: 2px solid {THEME['tab_border']} !important;
}}
[data-baseweb="tab"] {{
    border-radius: 8px 8px 0 0 !important;
    padding: 8px 28px !important;
    font-size: 15px !important;
    font-weight: 600 !important;
}}

/* ── Remove default Streamlit top padding inside cards ── */
[data-testid="stVerticalBlockBorderWrapper"] > div {{
    padding-top: 10px !important;
    padding-bottom: 6px !important;
}}

/* ── Gap between cards ── */
.card-gap {{ margin-top: 16px; }}

/* ── Radio controls compact ── */
[data-testid="stRadio"] > div {{ gap: 6px !important; }}

/* ── Theme toggle: fixed top-right on all viewports ── */
[data-testid="stCheckbox"] {{
    position: fixed !important;
    top: 54px !important;
    right: 12px !important;
    width: auto !important;
    z-index: 999 !important;
    background: {THEME['bg_card']} !important;
    border-radius: 8px !important;
    padding: 4px 6px !important;
    box-shadow: 0 2px 8px {THEME['shadow']} !important;
}}

/* ── Mobile legibility boosts ── */
@media (max-width: 640px) {{
    /* Caption/source line */
    [data-testid="stCaptionContainer"] p {{
        font-size: 13px !important;
        line-height: 1.6 !important;
    }}
    /* Metric label */
    [data-testid="stMetricLabel"] p {{
        font-size: 15px !important;
    }}
    /* Radio button text */
    [data-testid="stRadio"] p {{
        font-size: 16px !important;
    }}
}}
</style>
""", unsafe_allow_html=True)

# ── Legend-click JS: wire HTML legend items → Plotly trace toggle ─────────────
# Uses components.html (sandboxed iframe) + parent.window to reach the main
# page DOM.  A MutationObserver re-attaches handlers on every Streamlit re-render.
components.html("""
<script>
// Inject legend-click wiring as a real <script> in the parent page so that
// event listeners run in the main-page JS context (not the sandboxed iframe).
(function () {
  var p = parent.window;
  if (p.__legendClickInjected) return;
  p.__legendClickInjected = true;

  // String.raw avoids all Python/JS double-escape headaches.
  // Note: [id^=hlegend-] works without quotes around the attribute value.
  var code = String.raw`
(function () {
  // ── Plotly extraction ─────────────────────────────────────────────────────
  // webpackChunk_streamlit_app is a plain Array until webpack's runtime
  // installs its custom .push.  We check for that before probing so the
  // execute-function is actually called synchronously.  preload() retries
  // every 250 ms for up to 5 s so Plotly is ready before the first click.
  function getPlotly() {
    if (window.Plotly) return window.Plotly;
    var c = window.webpackChunk_streamlit_app;
    if (!c || c.push === Array.prototype.push) return null;
    var req;
    c.push([[Math.random().toString(36)], {}, function (r) { req = r; }]);
    if (!req) return null;
    var ids = Object.keys(req.m || {});
    for (var i = 0; i < ids.length; i++) {
      try {
        var m = req(ids[i]);
        if (m && typeof m.restyle === 'function' && typeof m.newPlot === 'function') {
          window.Plotly = m; return m;
        }
      } catch (e) {}
    }
    return null;
  }
  function preload(n) {
    if (window.Plotly || n <= 0) return;
    if (!getPlotly()) setTimeout(function () { preload(n - 1); }, 250);
  }
  preload(20);

  // ── Legend click handler ──────────────────────────────────────────────────
  function attachLegend(legend) {
    if (legend._lcb) return;
    legend._lcb = true;
    legend.addEventListener('click', function (e) {
      var item = e.target.closest('[data-trace-idx]');
      if (!item) return;
      var plots = Array.from(document.querySelectorAll('.js-plotly-plot'));
      var plot = null;
      for (var i = 0; i < plots.length; i++) {
        if (legend.compareDocumentPosition(plots[i]) & 4) { plot = plots[i]; break; }
      }
      if (!plot || !plot.data || !plot.data.length) return;
      var P = getPlotly(); if (!P) return;
      var idx = parseInt(item.getAttribute('data-trace-idx'), 10);
      if (isNaN(idx) || idx >= plot.data.length) return;
      var cur = plot.data[idx].visible;
      var hidden = (cur === 'legendonly' || cur === false);
      P.restyle(plot, { visible: hidden ? true : 'legendonly' }, [idx]);
      item.style.opacity = hidden ? '1' : '0.35';
    });
  }

  function scanAll() {
    document.querySelectorAll('[id^=hlegend-]').forEach(attachLegend);
  }

  new MutationObserver(function (mutations) {
    mutations.forEach(function (m) {
      m.addedNodes.forEach(function (n) {
        if (n.nodeType !== 1) return;
        if (n.id && n.id.startsWith('hlegend-')) attachLegend(n);
        if (n.querySelectorAll) n.querySelectorAll('[id^=hlegend-]').forEach(attachLegend);
      });
    });
  }).observe(document.body, { childList: true, subtree: true });

  scanAll();
})();
`;

  var s = p.document.createElement('script');
  s.textContent = code;
  p.document.head.appendChild(s);
})();
</script>
""", height=0)

# ── Plotly config: no toolbar, no zoom/pan gestures (tap/click only) ──────────
PLOTLY_CFG = {"displayModeBar": False, "responsive": True, "scrollZoom": False}

# ── Named colours ─────────────────────────────────────────────────────────────
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

# Accent colour per section (used in card headers)
SEC_COLORS = [
    "#4e8ef7",   # 0 Bank Credit        – blue
    "#2ca02c",   # 1 Main Sectors       – green
    "#e05c5c",   # 2 Industry by Size   – red
    "#a87fdb",   # 3 Services           – purple
    "#f0912a",   # 4 Personal Loans     – orange
    "#e8b94f",   # 5 Priority Sector    – amber
    "#2ec4b6",   # 6 Industry by Type   – teal
]

ROMAN_ORDER = ["i","ii","iii","iv","v","vi","vii","viii","ix","x",
               "xi","xii","xiii","xiv","xv"]


# ── Helpers ───────────────────────────────────────────────────────────────────
def _html_legend(tab: str, sec_idx: int, codes: list, labels: dict, cmap: dict) -> None:
    """Flex-wrap legend rendered as HTML above the chart.
    Takes exactly the space it needs — no Plotly top-margin estimation required.
    Items are clickable: tap/click toggles the corresponding Plotly trace.

    tab      – 't' for trend tab, 'd' for distribution tab (keeps ids unique)
    sec_idx  – section index (0-based) within the tab
    """
    legend_id = f"hlegend-{tab}-{sec_idx}"
    items = "".join(
        f'<span data-trace-idx="{i}" style="display:inline-flex;align-items:flex-start;'
        f'margin:4px 16px 4px 0;max-width:100%;'
        f'cursor:pointer;user-select:none;transition:opacity 0.2s;">'
        f'<span style="width:14px;height:14px;border-radius:3px;flex-shrink:0;'
        f'background:{cmap.get(code, "#888")};margin-right:6px;margin-top:2px;"></span>'
        f'<span style="font-size:14px;color:{THEME["font"]};'
        f'word-break:break-word;min-width:0;">'
        f'{labels.get(code, code)}</span></span>'
        for i, code in enumerate(codes)
    )
    st.markdown(
        f'<div id="{legend_id}" style="display:flex;flex-wrap:wrap;margin-bottom:6px;">'
        f'{items}</div>',
        unsafe_allow_html=True,
    )


def _short_label(text: str, max_len: int = 26) -> str:
    """Truncate long labels for hover tooltips so they don't overflow on mobile.
    The full label is still shown in the HTML flex-wrap legend above the chart."""
    if len(text) <= max_len:
        return text
    # Try to break at a word boundary
    truncated = text[:max_len]
    last_space = truncated.rfind(" ")
    if last_space > max_len // 2:
        return truncated[:last_space] + "…"
    return truncated + "…"


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


def fmt_cr(v: float) -> str:
    return f"₹{v / 1e5:.2f} L Cr"


def _smart_unit(max_val: float):
    """Return (divisor, axis_label, hover_unit, fmt_spec) based on magnitude."""
    if max_val >= 1e5:
        return 1e5, "₹ L Cr", "L Cr", ",.2f"
    if max_val >= 1e3:
        return 1e3, "₹ Th Cr", "Th Cr", ",.1f"
    return 1.0, "₹ Crore", "Cr", ",.0f"


def date_label(ts) -> str:
    return pd.Timestamp(ts).strftime("%b %Y")


def sort_codes_numeric(codes: list) -> list:
    def key(c):
        try:
            return tuple(int(p) for p in str(c).split("."))
        except ValueError:
            return (float("inf"),)
    return sorted(codes, key=key)


def children_of(source_df: pd.DataFrame, parent_code: str,
                parent_stmt: str = "Statement 1",
                memo: bool = False) -> tuple:
    mask = (
        (source_df["parent_code"] == parent_code)
        & (source_df["parent_statement"] == parent_stmt)
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


def card_header(title: str, icon: str, color: str) -> None:
    """Coloured left-border header inside a card."""
    st.markdown(
        f'<div style="'
        f'background:{color}1a;'
        f'border-left:4px solid {color};'
        f'padding:8px 16px;'
        f'border-radius:6px;'
        f'margin-bottom:12px;">'
        f'<span style="font-size:16px;font-weight:700;color:{color};">'
        f'{icon}&nbsp;&nbsp;{title}'
        f'</span></div>',
        unsafe_allow_html=True,
    )


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
        else:
            mend = [x for x in dates if x.month == 3 and x < d]
            if mend:
                pairs.append((d, max(mend)))

    rows = []
    for curr, prev in pairs:
        cv = data_df[data_df["date"] == curr].set_index(["statement","code"])["outstanding_cr"]
        pv = data_df[data_df["date"] == prev].set_index(["statement","code"])["outstanding_cr"]
        pct = ((cv - pv) / pv * 100).reset_index()
        pct.columns = ["statement", "code", "growth_pct"]
        pct["date"] = curr
        rows.append(pct)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


# ── Chart renderers ───────────────────────────────────────────────────────────
def _base_layout(n_legend: int = 0, legend_below: bool = False) -> dict:
    """
    Base Plotly layout with dynamic margins for the legend.

    Trend charts (legend_below=False): legend above plot area, top margin
      sized conservatively at ~4 items/row so it never overflows into controls.

    Distribution charts (legend_below=True): legend below the bars, bottom
      margin sized instead — eliminates the blank gap caused by over-allocating
      top margin when Plotly wraps fewer rows than the worst-case estimate.
    """
    if legend_below and n_legend:
        # Legend below bars: no extra top margin needed.
        # y=-0.25 clears the x-axis tick labels (~20px) before the legend starts.
        leg_rows = max(1, math.ceil(n_legend / 5))  # wider row on full-width charts
        t_margin = 10
        b_margin = 40 + leg_rows * 32   # 32 px per legend row + base gap for tick labels
        chart_height = 370
        legend_cfg = dict(
            orientation="h",
            yanchor="top", y=-0.25,
            xanchor="left", x=0,
            bgcolor="rgba(0,0,0,0)",
        )
    else:
        # Legend above plot: conservative top margin to avoid overflow
        rows = max(1, math.ceil(n_legend / 4)) if n_legend else 0
        t_margin = 10 + rows * 30
        b_margin = 20
        chart_height = 370 + max(0, rows - 1) * 20
        legend_cfg = dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="left", x=0,
            bgcolor="rgba(0,0,0,0)",
        ) if n_legend else None

    layout: dict = dict(
        height=chart_height,
        margin=dict(l=0, r=0, t=t_margin, b=b_margin),
        hovermode="x unified",
        dragmode=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(tickformat="%b %Y", gridcolor=THEME["grid"], zeroline=False, fixedrange=True),
        yaxis=dict(gridcolor=THEME["grid"], zeroline=False, fixedrange=True),
        font=dict(color=THEME["font"], size=13),
    )
    if legend_cfg:
        layout["showlegend"] = True
        layout["legend"] = legend_cfg
    else:
        layout["showlegend"] = False
    return layout


def render_trend(sec_idx: int, data: pd.DataFrame,
                 codes: list, labels: dict) -> None:
    if data.empty or not codes:
        st.info("No data for this section.")
        return

    cmap = assign_colors(codes, labels)

    # ── Controls row (no spacer column — avoids blank gap on mobile) ─────────
    c1, c2 = st.columns([2, 2])
    with c1:
        view = st.radio(
            "View", ["Absolute", "Growth Rate"],
            horizontal=True, label_visibility="collapsed",
            key=f"view_t_{sec_idx}",
        )
    with c2:
        gm = None
        if view == "Growth Rate":
            gm = st.radio(
                "Growth", ["YoY", "FY"],
                horizontal=True, label_visibility="collapsed",
                key=f"gm_t_{sec_idx}",
            )

    # ── Legend above chart (HTML flex-wrap — no Plotly top-margin needed) ──────
    _html_legend("t", sec_idx, codes, labels, cmap)

    # ── Chart ────────────────────────────────────────────────────────────────
    fig = go.Figure()

    if view == "Absolute":
        _max = data[data["code"].isin(codes)]["outstanding_cr"].max() if not data.empty else 1.0
        _div, _unit_label, _hover_unit, _fmt = _smart_unit(float(_max) if _max == _max else 1.0)
        for code in codes:
            seg = data[data["code"] == code].sort_values("date")
            if seg.empty:
                continue
            name = labels.get(code, code)
            short = _short_label(name)
            fig.add_trace(go.Scatter(
                x=seg["date"], y=seg["outstanding_cr"] / _div,
                mode="lines+markers", name=short,
                line=dict(color=cmap.get(code), width=2.5),
                marker=dict(size=6),
                hovertemplate=(
                    f"<b>{short}</b><br>%{{x|%b %Y}}<br>"
                    f"₹%{{y:{_fmt}}} {_hover_unit}<extra></extra>"
                ),
            ))
        fig.update_layout(**_base_layout(), yaxis_title=_unit_label)

    else:
        gdf = compute_growth(data, "yoy" if gm == "YoY" else "fy")
        if gdf.empty:
            st.warning("Not enough data to compute growth rates.")
            return
        for code in codes:
            seg = gdf[gdf["code"] == code].sort_values("date")
            if seg.empty:
                continue
            name = labels.get(code, code)
            short = _short_label(name)
            fig.add_trace(go.Scatter(
                x=seg["date"], y=seg["growth_pct"],
                mode="lines+markers", name=short,
                line=dict(color=cmap.get(code), width=2.5),
                marker=dict(size=6),
                hovertemplate=(
                    f"<b>{short}</b><br>%{{x|%b %Y}}<br>"
                    "%{y:.1f}%<extra></extra>"
                ),
            ))
        fig.add_hline(y=0, line_dash="dash", line_color=THEME["hline"], line_width=1)
        fig.update_layout(**_base_layout(), yaxis_title=f"{gm} Growth (%)")

    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CFG)


def render_dist(sec_idx: int, data: pd.DataFrame,
                codes: list, labels: dict,
                pct_label: str = "% Share",
                dist_codes: list = None) -> None:
    if data.empty or not codes:
        st.info("No data for this section.")
        return

    _dc = dist_codes if dist_codes is not None else codes
    cmap = assign_colors(codes, labels)

    _qmax = data[data["code"].isin(_dc)]["outstanding_cr"].max() if not data.empty else 1.0
    _div, _cr_label, _hover_unit, _fmt = _smart_unit(float(_qmax) if _qmax == _qmax else 1.0)

    # ── Controls row ──────────────────────────────────────────────────────────
    dist_mode = st.radio(
        "Show as", [_cr_label, pct_label],
        horizontal=True, label_visibility="collapsed",
        key=f"dist_d_{sec_idx}",
    )

    # ── Legend above chart (HTML flex-wrap; takes exact space, no blank gap) ──
    _html_legend("d", sec_idx, _dc, labels, cmap)

    rows = []
    for d in all_dates:
        sl = data[data["date"] == d]
        for code in _dc:
            v = sl[sl["code"] == code]["outstanding_cr"].values
            rows.append({
                "date": d, "code": code,
                "sector": labels.get(code, code),
                "value": float(v[0]) if len(v) else 0.0,
            })
    ddf = pd.DataFrame(rows)

    if dist_mode == pct_label:
        totals = ddf.groupby("date")["value"].transform("sum")
        ddf["plot_val"] = ddf["value"] / totals.replace(0, float("nan")) * 100
        yax = dict(title=pct_label, range=[0, 100],
                   gridcolor=THEME["grid"], zeroline=False)
        hover_fmt = "%{y:.1f}%"
    else:
        ddf["plot_val"] = ddf["value"] / _div
        yax = dict(title=_cr_label, gridcolor=THEME["grid"], zeroline=False)
        hover_fmt = f"₹%{{y:{_fmt}}} {_hover_unit}"

    fig2 = go.Figure()
    for code in _dc:
        seg = ddf[ddf["code"] == code].sort_values("date")
        name = labels.get(code, code)
        short = _short_label(name)
        fig2.add_trace(go.Bar(
            x=seg["date"].apply(date_label),
            y=seg["plot_val"],
            name=short,
            marker_color=cmap.get(code),
            hovertemplate=f"<b>{short}</b><br>%{{x}}<br>{hover_fmt}<extra></extra>",
        ))

    layout = _base_layout()   # no Plotly legend — shown as HTML above
    layout["yaxis"] = yax
    layout.pop("yaxis_title", None)
    fig2.update_layout(**layout, barmode="stack")
    st.plotly_chart(fig2, use_container_width=True, config=PLOTLY_CFG)

    # Summary table
    st.caption(f"Breakdown at **{date_label(latest_date)}**")
    tbl = ddf[ddf["date"] == latest_date].copy()
    total = tbl["value"].sum()
    tbl["Share (%)"] = (tbl["value"] / total * 100).round(1) if total else 0.0
    tbl[_cr_label] = tbl["value"].apply(lambda v: f"{v / _div:{_fmt}}")
    st.dataframe(
        tbl[["sector", _cr_label, "Share (%)"]].rename(columns={"sector": "Sector"}),
        hide_index=True, use_container_width=True,
        column_config={
            "Sector":   st.column_config.TextColumn("Sector"),
            _cr_label:  st.column_config.TextColumn(_cr_label, width="small"),
            "Share (%)": st.column_config.NumberColumn("Share %", width="small",
                                                        format="%.1f"),
        },
    )


# ── Industry by Type filter helpers ──────────────────────────────────────────
def _filtered_codes7(mode_key: str, n_key: str, x_key: str) -> list:
    mode = st.session_state.get(mode_key, "Top N")
    if mode == "Top N":
        n = int(st.session_state.get(n_key, min(10, len(codes7))))
        return sort_codes_numeric(codes7_by_size[:n])
    elif mode == "≥ X% coverage":
        x = float(st.session_state.get(x_key, 80.0))
        cumulative, selected = 0.0, []
        for code in codes7_by_size:
            selected.append(code)
            cumulative += shares7[code]
            if cumulative >= x:
                break
        return sort_codes_numeric(selected)
    return codes7  # All


def render_industry_filter(key_suffix: str) -> list:
    """Renders filter controls and returns filtered code list."""
    mk = f"ind_type_filter_{key_suffix}"
    nk = f"ind_type_n_{key_suffix}"
    xk = f"ind_type_x_{key_suffix}"

    c1, c2, c3 = st.columns([2, 1, 5])
    with c1:
        fmode = st.radio(
            "Display", ["Top N", "≥ X% coverage", "All"],
            horizontal=True, label_visibility="collapsed", key=mk,
        )
    with c2:
        if fmode == "Top N":
            st.number_input(
                "N", min_value=1, max_value=len(codes7),
                value=min(10, len(codes7)), step=1,
                key=nk, label_visibility="collapsed",
            )
        elif fmode == "≥ X% coverage":
            st.number_input(
                "Coverage %", min_value=10.0, max_value=100.0,
                value=80.0, step=5.0, format="%.0f",
                key=xk, label_visibility="collapsed",
            )
    with c3:
        filtered = _filtered_codes7(mk, nk, xk)
        shown_pct  = sum(shares7[c] for c in filtered)
        hidden     = len(codes7) - len(filtered)
        hidden_pct = 100.0 - shown_pct
        if hidden:
            st.caption(
                f"Showing **{len(filtered)}** of {len(codes7)} types "
                f"covering **{shown_pct:.1f}%** of Industry — "
                f"{hidden} others account for the remaining **{hidden_pct:.1f}%**."
            )
        else:
            st.caption(f"Showing all **{len(codes7)}** industry types.")

    return filtered


# ── Load data ─────────────────────────────────────────────────────────────────
df          = load_data()
s1          = df[df["statement"] == "Statement 1"]
s2          = df[df["statement"] == "Statement 2"]
all_dates   = sorted(df["date"].unique())
latest_date = all_dates[-1]

# ── Page header + theme toggle ─────────────────────────────────────────────────
# Toggle is rendered first so it's fixed-positioned to top-right on all viewports
st.toggle(
    "🌙" if not _dark else "☀️",
    key="dark_mode",
    help="Switch between light and dark theme",
)
st.title("RBI Gross Bank Credit")
st.caption(
    f"Source: RBI Sector/Industry-wise Bank Credit (SIBC) Return  |  "
    f"Values in ₹ Crore  |  Latest data: **{date_label(latest_date)}**"
)
latest_bc = s1[(s1["code"] == "I") & (s1["date"] == latest_date)]["outstanding_cr"].values[0]
st.metric("Total Bank Credit", fmt_cr(latest_bc))

st.divider()

# ── Pre-compute all section data ──────────────────────────────────────────────

# 1 – Bank Credit
codes1  = ["I", "II", "III"]
labels1 = {"I": "Bank Credit", "II": "Food Credit", "III": "Non-food Credit"}
data1   = s1[s1["code"].isin(codes1) & ~s1["is_priority_sector_memo"]].copy()

# 2 – Main Sectors
codes2  = ["1", "2", "3", "4"]
labels2 = {"1": "Agriculture", "2": "Industry", "3": "Services", "4": "Personal Loans"}
data2   = s1[s1["code"].isin(codes2) & ~s1["is_priority_sector_memo"]].copy()

# 3 – Industry by Size
data3, codes3, labels3 = children_of(s1, "2")

# 4 – Services
data4, codes4, labels4 = children_of(s1, "3")

# 5 – Personal Loans
data5, codes5, labels5 = children_of(s1, "4")

# 6 – Priority Sector
data6 = s1[s1["is_priority_sector_memo"].astype(bool)].copy()
cl6   = (
    data6[["code", "sector"]].drop_duplicates()
    .set_index("code")["sector"].to_dict()
)
codes6 = sorted(cl6.keys(),
                key=lambda c: ROMAN_ORDER.index(c) if c in ROMAN_ORDER else 99)

# 7 – Industry by Type (Statement 2) + filter pre-computation
data7, codes7, labels7 = children_of(s2, "2", parent_stmt="Statement 1")
latest_sl7  = data7[data7["date"] == latest_date]
total7      = latest_sl7["outstanding_cr"].sum()
shares7     = {
    code: (
        latest_sl7[latest_sl7["code"] == code]["outstanding_cr"].values[0] / total7 * 100
        if len(latest_sl7[latest_sl7["code"] == code]) and total7 else 0.0
    )
    for code in codes7
}
codes7_by_size = sorted(codes7, key=lambda c: shares7[c], reverse=True)

# ── Section manifest (for the 6 straightforward sections) ────────────────────
# (title, icon, sec_color_idx, data, codes, labels, pct_label, dist_codes)
SECTIONS = [
    ("Bank Credit",      "🏦", 0, data1, codes1, labels1, "% of Bank Credit",    ["II", "III"]),
    ("Main Sectors",     "📊", 1, data2, codes2, labels2, "% Share",              None),
    ("Industry by Size", "🏭", 2, data3, codes3, labels3, "% of Industry",        None),
    ("Services",         "🛎", 3, data4, codes4, labels4, "% of Services",        None),
    ("Personal Loans",   "💳", 4, data5, codes5, labels5, "% of Personal Loans",  None),
    ("Priority Sector",  "⭐", 5, data6, codes6, cl6,     "% of Priority Sector", None),
]

# ── Two main tabs ─────────────────────────────────────────────────────────────
tab_trend, tab_dist = st.tabs(["📈  Trend", "📊  Distribution"])

# ────────────────── TREND TAB ─────────────────────────────────────────────────
with tab_trend:
    for i, (title, icon, ci, data, codes, labels, pct_label, _) in enumerate(SECTIONS):
        with st.container(border=True):
            card_header(title, icon, SEC_COLORS[ci])
            render_trend(i, data, codes, labels)
        st.markdown('<div class="card-gap"></div>', unsafe_allow_html=True)

    # Section 7 – Industry by Type (has its own filter)
    with st.container(border=True):
        card_header("Industry by Type", "🔩", SEC_COLORS[6])
        filtered7t = render_industry_filter("t")
        render_trend(6, data7[data7["code"].isin(filtered7t)],
                     filtered7t, {c: labels7[c] for c in filtered7t})
    st.markdown('<div class="card-gap"></div>', unsafe_allow_html=True)

# ────────────────── DISTRIBUTION TAB ─────────────────────────────────────────
with tab_dist:
    for i, (title, icon, ci, data, codes, labels, pct_label, dist_codes) in enumerate(SECTIONS):
        with st.container(border=True):
            card_header(title, icon, SEC_COLORS[ci])
            render_dist(i, data, codes, labels, pct_label, dist_codes)
        st.markdown('<div class="card-gap"></div>', unsafe_allow_html=True)

    # Section 7 – Industry by Type
    with st.container(border=True):
        card_header("Industry by Type", "🔩", SEC_COLORS[6])
        filtered7d = render_industry_filter("d")
        render_dist(6, data7[data7["code"].isin(filtered7d)],
                    filtered7d, {c: labels7[c] for c in filtered7d},
                    "% of Industry")
    st.markdown('<div class="card-gap"></div>', unsafe_allow_html=True)
