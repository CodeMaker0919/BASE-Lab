import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import io
from datetime import timedelta

# --- CONFIG ---
SHEET_ID = "1-rg8dp5_PMRO83Z_sISVTRIbToui0ea1ZnAXsE_KHFA"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
GROUPS = ["Control", "4 Magnets", "6 Magnets", "8 Magnets"]

COLORS = {
    "Control": "#475569", "4 Magnets": "#2563eb", 
    "6 Magnets": "#d97706", "8 Magnets": "#dc2626",
    "Real 450nm": "#2563eb", "Real 750nm": "#64748b"
}

st.set_page_config(page_title="Algae Lab Report", layout="wide")

@st.cache_data(ttl=60)
def get_clean_data():
    try:
        res = requests.get(SHEET_URL)
        xls = pd.read_excel(io.BytesIO(res.content), sheet_name=None, engine='openpyxl')
        all_df = []
        for name in GROUPS:
            if name in xls:
                temp_df = xls[name].copy()
                temp_df.columns = temp_df.columns.str.strip()
                if 'Notes' in temp_df.columns:
                    temp_df = temp_df[~temp_df['Notes'].astype(str).str.contains('Muck', na=False, case=False)]
                temp_df['Date'] = pd.to_datetime(temp_df['Date'], errors='coerce').dt.normalize()
                temp_df['Real 450nm'] = pd.to_numeric(temp_df['Real 450nm'], errors='coerce')
                temp_df['Real 750nm'] = pd.to_numeric(temp_df['Real 750nm'], errors='coerce')
                temp_df = temp_df.dropna(subset=['Date', 'Real 450nm']).query('`Real 450nm` > 0')
                temp_df = temp_df.groupby('Date', as_index=False)[['Real 450nm', 'Real 750nm']].mean()
                temp_df['Group'] = name
                all_df.append(temp_df)
        return pd.concat(all_df) if all_df else pd.DataFrame()
    except Exception: return pd.DataFrame()

def build_precision_graph(data, y_cols, title):
    if isinstance(y_cols, str): y_cols = [y_cols]
    fig = go.Figure()
    label_positions = []

    for group_name in data['Group'].unique():
        gdf = data[data['Group'] == group_name].sort_values('Date')
        plot_data = gdf.copy()

        # --- GHOST POINT INTERPOLATION ---
        for i in range(len(gdf) - 1):
            d1, d2 = gdf.iloc[i]['Date'], gdf.iloc[i+1]['Date']
            if (d2 - d1).days > 1:
                gap_start, gap_end = d1 + timedelta(days=1), d2
                fig.add_vline(x=gap_start, line_dash="dot", line_width=1.5, line_color="#cbd5e1")
                fig.add_vline(x=gap_end, line_dash="dot", line_width=1.5, line_color="#cbd5e1")
                
                ghost_row = {'Date': gap_start, 'Group': group_name}
                break_row = {'Date': gap_start + timedelta(minutes=1), 'Group': group_name}
                for col in y_cols:
                    slope = (gdf.iloc[i+1][col] - gdf.iloc[i][col]) / (d2 - d1).days
                    ghost_row[col] = gdf.iloc[i][col] + slope
                    break_row[col] = None
                plot_data = pd.concat([plot_data, pd.DataFrame([ghost_row, break_row])], ignore_index=True)

        plot_data = plot_data.sort_values('Date')

        for col in y_cols:
            color = COLORS.get(group_name) if len(y_cols) == 1 else COLORS.get(col)
            fig.add_trace(go.Scatter(
                x=plot_data['Date'], y=plot_data[col], mode='lines+markers',
                line=dict(color=color, width=4),
                marker=dict(size=10, line=dict(width=2, color="white")),
                connectgaps=False
            ))

            # Store label info for de-cluttering later
            valid = gdf.dropna(subset=[col])
            if not valid.empty:
                val_start, val_end = valid.iloc[0][col], valid.iloc[-1][col]
                pct = ((val_end - val_start) / val_start * 100) if val_start != 0 else 0
                label_positions.append({
                    'x': valid.iloc[-1]['Date'], 'y': val_end, 'color': color,
                    'text': f"<b>{group_name if len(y_cols)==1 else col}</b><br>{pct:+.0f}% change"
                })

    # --- DE-CLUTTERING LOGIC (Collision Detection) ---
    if label_positions:
        # Sort labels by their Y position
        label_positions.sort(key=lambda x: x['y'])
        min_distance = 0.08  # Minimum absorbance units between labels
        
        for i in range(1, len(label_positions)):
            prev_y = label_positions[i-1]['y']
            curr_y = label_positions[i]['y']
            if curr_y - prev_y < min_distance:
                label_positions[i]['y'] = prev_y + min_distance

        for lp in label_positions:
            fig.add_annotation(
                x=lp['x'], y=lp['y'], text=f" {lp['text']}",
                font=dict(color=lp['color'], size=13),
                showarrow=False, xanchor="left", xshift=15, align="left"
            )

    fig.update_layout(
        title=dict(text=f"<b>{title}</b>", font=dict(size=26, color="#1e293b")),
        template="plotly_white", showlegend=False, height=750,
        margin=dict(r=220, l=60, t=100, b=60),
        xaxis=dict(showgrid=False, linecolor="#94a3b8"),
        yaxis=dict(gridcolor="#f1f5f9", title="Absorbance Units")
    )
    return fig

# --- RENDER ---
df_master = get_clean_data()
if not df_master.empty:
    st.title("Algae Lab Growth Analysis")
    st.plotly_chart(build_precision_graph(df_master, 'Real 450nm', "Comparison: Chlorophyll (450nm)"), use_container_width=True)
    st.plotly_chart(build_precision_graph(df_master, 'Real 750nm', "Comparison: Cell Density (750nm)"), use_container_width=True)
    st.divider()
    for group in GROUPS:
        gdf_group = df_master[df_master['Group'] == group]
        if not gdf_group.empty:
            st.plotly_chart(build_precision_graph(gdf_group, ['Real 450nm', 'Real 750nm'], f"Deep Dive: {group}"), use_container_width=True)
    if st.sidebar.button("Sync Live Data"):
        st.cache_data.clear()
        st.rerun()
else:
    st.error("No data found. Check permissions.")
