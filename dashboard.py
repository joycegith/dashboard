# app.py
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
import plotly.graph_objects as go


# ----------------------------
# Helpers
# ----------------------------
DEFAULT_HEX_PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf",
]


def parse_hex_palette(text: str) -> List[str]:
    """
    Accepts comma/newline/space-separated HEX colors.
    Returns a sanitized list like ['#RRGGBB', ...].
    """
    if not text:
        return []
    tokens = re.split(r"[\s,;]+", text.strip())
    out = []
    for t in tokens:
        if not t:
            continue
        t = t.strip()
        if not t.startswith("#"):
            t = "#" + t
        if re.fullmatch(r"#[0-9a-fA-F]{6}", t):
            out.append(t.upper())
    return out


def find_header_row(raw: pd.DataFrame) -> Optional[int]:
    """
    Detect the row that contains year columns (mostly numeric years),
    e.g. ['$M', 2022, 2023, ...].
    Returns row index or None.
    """
    for i in range(len(raw)):
        row = raw.iloc[i].tolist()
        if len(row) < 3:
            continue

        candidates = row[1:]  # years should be from col 1 onwards
        years = []
        for v in candidates:
            if pd.isna(v):
                continue
            try:
                y = int(float(v))
                if 1900 <= y <= 2100:
                    years.append(y)
            except Exception:
                pass

        # header row heuristic: at least 2 valid years and more than half of non-nan are valid years
        non_nan = [v for v in candidates if not pd.isna(v)]
        if len(years) >= 2 and (len(non_nan) > 0) and (len(years) / len(non_nan) >= 0.6):
            return i
    return None


def load_revenue_xlsx(path_or_file) -> Tuple[pd.DataFrame, str]:
    """
    Loads the Excel sheet into a clean wide format:
      Product | 2022 | 2023 | ...
    Returns (df_wide, unit_label).
    """
    raw = pd.read_excel(path_or_file, header=None)
    hdr = find_header_row(raw)
    if hdr is None:
        raise ValueError("Could not detect the header row containing years in the Excel file.")

    header_row = raw.iloc[hdr].tolist()

    unit_label = str(header_row[0]) if (header_row and not pd.isna(header_row[0])) else ""
    years = []
    for v in header_row[1:]:
        if pd.isna(v):
            years.append(None)
        else:
            try:
                years.append(str(int(float(v))))
            except Exception:
                years.append(str(v))

    columns = ["Product"] + years

    df = raw.iloc[hdr + 1 :].copy()
    df = df.iloc[:, : len(columns)]
    df.columns = columns

    # Drop fully empty rows
    df = df.dropna(how="all")

    # Ensure product names are strings and non-empty
    df["Product"] = df["Product"].astype(str).str.strip()
    df = df[df["Product"].ne("") & df["Product"].ne("nan")]

    # Convert year columns to numeric
    year_cols = [c for c in df.columns if c != "Product" and c is not None and str(c).strip() != "" and c != "None"]
    for c in year_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Keep only rows with at least one numeric revenue
    df = df[df[year_cols].notna().any(axis=1)]

    return df, unit_label


def wide_to_long(df_wide: pd.DataFrame) -> pd.DataFrame:
    year_cols = [c for c in df_wide.columns if c != "Product"]
    long = df_wide.melt(id_vars="Product", value_vars=year_cols, var_name="Year", value_name="Revenue")
    long = long.dropna(subset=["Revenue"])
    long["Year"] = pd.to_numeric(long["Year"], errors="coerce").astype("Int64")
    long = long.dropna(subset=["Year"])
    long["Year"] = long["Year"].astype(int)
    long = long.sort_values(["Product", "Year"])
    return long


def compute_product_stats(long_df: pd.DataFrame, product: str) -> Dict[str, float]:
    d = long_df[long_df["Product"] == product].sort_values("Year")
    years = d["Year"].to_list()
    vals = d["Revenue"].to_list()
    if not years or not vals:
        return {}

    first_year, last_year = years[0], years[-1]
    first_val, last_val = float(vals[0]), float(vals[-1])
    n_years = max(1, last_year - first_year)

    # CAGR
    cagr = None
    if first_val > 0 and n_years > 0:
        cagr = (last_val / first_val) ** (1 / n_years) - 1

    return {
        "first_year": first_year,
        "last_year": last_year,
        "first_val": first_val,
        "last_val": last_val,
        "abs_change": last_val - first_val,
        "pct_change": (last_val / first_val - 1) if first_val != 0 else float("nan"),
        "cagr": cagr if cagr is not None else float("nan"),
        "min_val": float(min(vals)),
        "max_val": float(max(vals)),
    }


def build_color_map(products: List[str], palette: List[str], overrides: Dict[str, str]) -> Dict[str, str]:
    pal = palette[:] if palette else DEFAULT_HEX_PALETTE[:]
    out = {}
    for i, p in enumerate(products):
        out[p] = overrides.get(p) or pal[i % len(pal)]
    return out


# ----------------------------
# Streamlit UI
# ----------------------------
st.set_page_config(page_title="Revenue Trends", layout="wide")
st.title("Interactive Revenue Trends")

with st.sidebar:
    st.header("Data source")
    uploaded = st.file_uploader("Upload XLSX", type=["xlsx"])
    default_path = "C:/Users/u0003989/Downloads/AP.xlsx"
    use_default = st.checkbox(f"Use default file ({default_path})", value=(uploaded is None))

    st.divider()
    st.header("Chart controls")


try:
    if uploaded is not None:
        df_wide, unit_label = load_revenue_xlsx(uploaded)
    elif use_default:
        df_wide, unit_label = load_revenue_xlsx(default_path)
    else:
        st.info("Upload an XLSX or select the default file in the sidebar.")
        st.stop()
except Exception as e:
    st.error(f"Failed to load Excel: {e}")
    st.stop()

df_long = wide_to_long(df_wide)
all_products = sorted(df_long["Product"].unique().tolist())
all_years = sorted(df_long["Year"].unique().tolist())

with st.sidebar:
    selected_products = st.multiselect(
        "Select products to display",
        options=all_products,
        default=all_products,
    )

    y_label = f"Revenue ({unit_label})" if unit_label else "Revenue"
    show_markers = st.checkbox("Show markers (recommended for lasso/click)", value=True)

    st.subheader("Colors")
    color_mode = st.radio(
        "Color input mode",
        ["Per-product pickers", "HEX palette text"],
        index=0,
    )

    overrides: Dict[str, str] = {}
    palette_list: List[str] = DEFAULT_HEX_PALETTE[:]

    if color_mode == "HEX palette text":
        palette_text = st.text_area(
            "HEX palette (comma/newline-separated, e.g. #1F77B4, #FF7F0E, ...)",
            value=", ".join(DEFAULT_HEX_PALETTE[:8]),
            height=120,
        )
        parsed = parse_hex_palette(palette_text)
        palette_list = parsed if parsed else DEFAULT_HEX_PALETTE[:]
    else:
        # pickers for selected products
        palette_list = DEFAULT_HEX_PALETTE[:]
        if selected_products:
            st.caption("Pick a color for each selected product.")
            for idx, p in enumerate(selected_products):
                default_c = DEFAULT_HEX_PALETTE[idx % len(DEFAULT_HEX_PALETTE)]
                overrides[p] = st.color_picker(p, value=default_c)

if not selected_products:
    st.warning("Select at least one product to plot.")
    st.stop()

color_map = build_color_map(selected_products, palette_list, overrides)

# ----------------------------
# Plotly figure
# ----------------------------
fig = go.Figure()

mode = "lines+markers" if show_markers else "lines"

for p in selected_products:
    d = df_long[df_long["Product"] == p].sort_values("Year")
    fig.add_trace(
        go.Scatter(
            x=d["Year"],
            y=d["Revenue"],
            mode=mode,
            name=p,
            line=dict(color=color_map[p]),
            marker=dict(color=color_map[p]),
            customdata=[p] * len(d),
            hovertemplate=(
                "<b>%{customdata}</b><br>"
                "Year: %{x}<br>"
                f"{y_label}: %{{y:,.0f}}<extra></extra>"
            ),
        )
    )

fig.update_layout(
    height=560,
    hovermode="x unified",
    legend_title_text="Products",
    margin=dict(l=20, r=20, t=40, b=20),
)
fig.update_xaxes(title_text="Year", tickmode="linear")
fig.update_yaxes(title_text=y_label, tickformat=",")

# ----------------------------
# Click/Lasso events (optional)
# ----------------------------
selected_product_from_event = None

try:
    from streamlit_plotly_events import plotly_events  # pip install streamlit-plotly-events

    events = plotly_events(
        fig,
        click_event=True,
        select_event=True,   # enables lasso/box select
        hover_event=False,
        override_height=560,
        key="revenue_plot",
    )
    if events:
        # events is a list of points; use the first point's customdata (product name)
        selected_product_from_event = events[0].get("customdata")
except Exception:
    # Fallback: no event capture
    st.plotly_chart(fig, use_container_width=True)

# If event-capture is available, we still need to render the chart (plotly_events already does).
# In that case, do nothing here.

# Persist selection
if "selected_product" not in st.session_state:
    st.session_state["selected_product"] = None
if selected_product_from_event:
    st.session_state["selected_product"] = selected_product_from_event

st.divider()

# ----------------------------
# Product card
# ----------------------------
card_product = st.session_state.get("selected_product")
if card_product and card_product in all_products:
    stats = compute_product_stats(df_long, card_product)
    if stats:
        st.subheader(f"Product card: {card_product}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"Latest ({stats['last_year']})", f"{stats['last_val']:,.0f}")
        c2.metric("Change", f"{stats['abs_change']:,.0f}", f"{stats['pct_change']*100:,.1f}%")
        c3.metric("Min", f"{stats['min_val']:,.0f}")
        c4.metric("Max", f"{stats['max_val']:,.0f}")

        st.caption(
            f"Period: {stats['first_year']}–{stats['last_year']} | "
            f"CAGR: {stats['cagr']*100:,.2f}% (if defined)"
        )
    else:
        st.info("No statistics available for the selected product.")
else:
    st.info("Click a line/marker or use lasso select to display a product card (requires the optional component).")

st.caption("Tip: You can also toggle traces directly in the Plotly legend.")
