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
        global_start_date = None
        
        for name in GROUPS:
            if name in xls:
                temp_df = xls[name].copy()
                temp_df.columns = temp_df.columns.str.strip()
                
                # --- Find Global Start Date (Before filtering 'Muck') ---
                raw_dates = pd.to_datetime(temp_df['Date'], errors='coerce').dt.normalize().dropna()
                if not raw_dates.empty:
                    sheet_min = raw_dates.min()
                    if global_start_date is None or sheet_min < global_start_date:
                        global_start_date = sheet_min

                # --- Filter and Clean ---
                if 'Notes' in temp_df.columns:
                    temp_df = temp_df[~temp_df['Notes'].astype(str).str.contains('Muck', na=False, case=False)]
                
                temp_df['Date'] = pd.to_datetime(temp_df['Date'], errors='coerce').dt.normalize()
                temp_df['Real 450nm'] = pd.to_numeric(temp_df['Real 450nm'], errors='coerce')
                temp_df['Real 750nm'] = pd.to_numeric(temp_df['Real 750nm'], errors='coerce')
                temp_df = temp_df.dropna(subset=['Date', 'Real 450nm']).query('`Real 450nm` > 0')
                temp_df = temp_df.groupby('Date', as_index=False)[['Real 450nm', 'Real 750nm']].mean()
                temp_df['Group'] = name
                all_df.append(temp_df)
                
        return (pd.concat(all_df) if all_df else pd.DataFrame()), global_start_date
    except Exception: return pd.DataFrame(), None

def build_precision_graph(data, y_cols, title, start_date):
    if isinstance(y_cols, str): y_cols = [y_cols]
    fig = go.Figure()
    label_positions = []

    # --- Convert absolute Dates to relative Days (e.g. May 7 = Day 1) ---
    plot_data_master = data.copy()
    plot_data_master['Day'] = (plot_data_master['Date'] - start_date).dt.days + 1

    for group_name in plot_data_master['Group'].unique():
        gdf = plot_data_master[plot_data_master['Group'] == group_name].sort_values('Day')
        plot_data = gdf.copy()

        # --- GAP & DEAD ZONE LOGIC ---
        for i in range(len(gdf) - 1):
            d1, d2 = gdf.iloc[i]['Day'], gdf.iloc[i+1]['Day']
            gap_days = int(d2 - d1)
            
            if gap_days > 1:
                # 1. Draw vertical dotted lines for every missing day
                for day_offset in range(1, gap_days):
                    missing_day = d1 + day_offset
                    fig.add_vline(x=missing_day, line_dash="dot", line_width=1.5, line_color="#cbd5e1")
                
                # 2. If the gap is wide enough to have space BETWEEN dotted lines
                if gap_days > 2:
                    ghost_rows = []
                    for col in y_cols:
                        slope = (gdf.iloc[i+1][col] - gdf.iloc[i][col]) / gap_days
                        
                        # Point A: Stop at the first dotted line
                        ghost_start = {'Day': d1 + 1, 'Group': group_name}
                        ghost_start[col] = gdf.iloc[i][col] + slope
                        
                        # Point B: Break the line so it disappears in the "Dead Zone"
                        break_row = {'Day': d1 + 1.1, 'Group': group_name}
                        break_row[col] = None
                        
                        # Point C: Resume at the last dotted line
                        ghost_end = {'Day': d2 - 1, 'Group': group_name}
                        ghost_end[col] = gdf.iloc[i+1][col] - slope
                        
                        ghost_rows.extend([ghost_start, break_row, ghost_end])
                    
                    plot_data = pd.concat([plot_data, pd.DataFrame(ghost_rows)], ignore_index=True)

        plot_data = plot_data.sort_values('Day')

        for col in y_cols:
            color = COLORS.get(group_name) if len(y_cols) == 1 else COLORS.get(col)
            
            # Trace 1: The continuous lines (includes breaks and slopes from plot_data)
            fig.add_trace(go.Scatter(
                x=plot_data['Day'], y=plot_data[col], mode='lines',
                line=dict(color=color, width=4),
                connectgaps=False, hoverinfo='skip'
            ))

            # Trace 2: The dots ONLY on real recorded data days (using gdf)
            fig.add_trace(go.Scatter(
                x=gdf['Day'], y=gdf[col], mode='markers',
                marker=dict(color=color, size=10, line=dict(width=2, color="white")),
                name=f"{group_name} {col}"
            ))

            # Store label info for de-cluttering later
            valid = gdf.dropna(subset=[col])
            if not valid.empty:
                val_start, val_end = valid.iloc[0][col], valid.iloc[-1][col]
                pct = ((val_end - val_start) / val_start * 100) if val_start != 0 else 0
                label_positions.append({
                    'x': valid.iloc[-1]['Day'], 'y': val_end, 'color': color,
                    'text': f"<b>{group_name if len(y_cols)==1 else col}</b><br>{pct:+.0f}% change"
                })

    # --- DE-CLUTTERING LOGIC (Collision Detection) ---
    if label_positions:
        label_positions.sort(key=lambda x: x['y'])
        min_distance = 0.08  
        
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
        xaxis=dict(showgrid=False, linecolor="#94a3b8", tickprefix="Day ", dtick=1),
        yaxis=dict(gridcolor="#f1f5f9", title="Absorbance Units")
    )
    return fig

# --- RENDER ---
df_master, global_start = get_clean_data()
if not df_master.empty and global_start:
    st.title("Algae Lab Growth Analysis")
    st.plotly_chart(build_precision_graph(df_master, 'Real 450nm', "Comparison: Chlorophyll (450nm)", global_start), use_container_width=True)
    st.plotly_chart(build_precision_graph(df_master, 'Real 750nm', "Comparison: Cell Density (750nm)", global_start), use_container_width=True)
    st.divider()
    for group in GROUPS:
        gdf_group = df_master[df_master['Group'] == group]
        if not gdf_group.empty:
            st.plotly_chart(build_precision_graph(gdf_group, ['Real 450nm', 'Real 750nm'], f"Deep Dive: {group}", global_start), use_container_width=True)
    if st.sidebar.button("Sync Live Data"):
        st.cache_data.clear()
        st.rerun()
else:
    st.error("No data found. Check permissions.")
