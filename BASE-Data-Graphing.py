import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import io

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
        
        # 1. Establish the True Baseline Timeline Start
        for name in GROUPS:
            if name in xls:
                temp_df = xls[name].copy()
                temp_df.columns = temp_df.columns.str.strip()
                raw_dates = pd.to_datetime(temp_df['Date'], errors='coerce').dt.normalize().dropna()
                if not raw_dates.empty:
                    sheet_min = raw_dates.min()
                    if global_start_date is None or sheet_min < global_start_date:
                        global_start_date = sheet_min

        # 2. Extract and Process Clean Observations
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
                
                # Pre-calculate relative experiment timeline day
                temp_df['Day'] = (temp_df['Date'] - global_start_date).dt.days + 1
                all_df.append(temp_df)
                
        return (pd.concat(all_df) if all_df else pd.DataFrame()), global_start_date
    except Exception: 
        return pd.DataFrame(), None

def build_precision_graph(data, y_cols, title, master_data=None):
    if isinstance(y_cols, str): 
        y_cols = [y_cols]
        
    fig = go.Figure()
    label_positions = []

    # Use master dataset if provided, fallback to scoped dataset if not
    timeline_source = master_data if master_data is not None else data

    # --- FIX 1: TIMELINE ANALYSIS ENGINE ---
    # Scans the global timeline to catch all individual group sequence gaps
    missing_verticals = set()
    if not timeline_source.empty:
        for group_name in timeline_source['Group'].unique():
            gdf = timeline_source[timeline_source['Group'] == group_name].sort_values('Day')
            for i in range(len(gdf) - 1):
                d1, d2 = gdf.iloc[i]['Day'], gdf.iloc[i+1]['Day']
                gap = int(d2 - d1)
                if gap > 1:
                    for offset in range(1, gap):
                        missing_verticals.add(int(d1 + offset))
                        
    # Draw standardized dotted interval bounds
    for md in missing_verticals:
        fig.add_vline(x=md, line_dash="dot", line_width=1.5, line_color="#cbd5e1")

    # Calculate global scale boundaries for smart layout metrics
    y_max = data[y_cols].max().max() if isinstance(data[y_cols], pd.DataFrame) else data[y_cols].max()
    y_min = data[y_cols].min().min() if isinstance(data[y_cols], pd.DataFrame) else data[y_cols].min()
    y_range = y_max - y_min if pd.notna(y_max) and pd.notna(y_min) else 1.0

    for group_name in data['Group'].unique():
        gdf = data[data['Group'] == group_name].sort_values('Day')
        if gdf.empty:
            continue
            
        plot_data = gdf.copy()
        ghost_rows = []

        # --- BREAK PATH INTERPOLATION LOGIC ---
        for i in range(len(gdf) - 1):
            d1, d2 = gdf.iloc[i]['Day'], gdf.iloc[i+1]['Day']
            gap_days = int(d2 - d1)
            
            if gap_days > 2:
                ghost_start = {'Day': d1 + 1, 'Group': group_name}
                ghost_break = {'Day': d1 + 1.1, 'Group': group_name}
                ghost_end = {'Day': d2 - 1, 'Group': group_name}
                
                for col in y_cols:
                    slope = (gdf.iloc[i+1][col] - gdf.iloc[i][col]) / gap_days
                    ghost_start[col] = gdf.iloc[i][col] + slope
                    ghost_break[col] = float('nan')  # Generates clean break vector paths
                    ghost_end[col] = gdf.iloc[i+1][col] - slope
                    
                ghost_rows.extend([ghost_start, ghost_break, ghost_end])

        if ghost_rows:
            plot_data = pd.concat([plot_data, pd.DataFrame(ghost_rows)], ignore_index=True)
        
        plot_data = plot_data.sort_values('Day')

        # --- DATA VECTOR RENDERING ---
        for col in y_cols:
            color = COLORS.get(group_name) if len(y_cols) == 1 else COLORS.get(col)
            
            # Group trend lines
            fig.add_trace(go.Scatter(
                x=plot_data['Day'], y=plot_data[col], mode='lines',
                line=dict(color=color, width=4),
                connectgaps=False, hoverinfo='skip'
            ))

            # Sample collection indicators
            fig.add_trace(go.Scatter(
                x=gdf['Day'], y=gdf[col], mode='markers',
                marker=dict(color=color, size=10, line=dict(width=2, color="white")),
                name=f"{group_name} {col}"
            ))

            # Metric analysis tracking bounds
            valid = gdf.dropna(subset=[col])
            if not valid.empty:
                val_start, val_end = valid.iloc[0][col], valid.iloc[-1][col]
                pct = ((val_end - val_start) / val_start * 100) if val_start != 0 else 0
                label_positions.append({
                    'x': valid.iloc[-1]['Day'], 'y': val_end, 'color': color,
                    'text': f"<b>{group_name if len(y_cols)==1 else col}</b><br>{pct:+.0f}% change"
                })

    # --- FIX 2: BI-DIRECTIONAL FORCE LABELS ---
    if label_positions:
        label_positions.sort(key=lambda x: x['y'])
        min_distance = max(0.12, y_range * 0.08) 
        
        # Iteratively distribute labels away from tight clusters
        for _ in range(15): 
            for i in range(len(label_positions) - 1):
                diff = label_positions[i+1]['y'] - label_positions[i]['y']
                if diff < min_distance:
                    overlap = min_distance - diff
                    label_positions[i]['y'] -= overlap / 2
                    label_positions[i+1]['y'] += overlap / 2

        for lp in label_positions:
            fig.add_annotation(
                x=lp['x'], y=lp['y'], text=f" {lp['text']}",
                font=dict(color=lp['color'], size=13),
                showarrow=False, xanchor="left", xshift=15, align="left"
            )

    fig.update_layout(
        title=dict(text=f"<b>{title}</b>", font=dict(size=26, color="#1e293b")),
        template="plotly_white", showlegend=False, height=600,
        margin=dict(r=220, l=60, t=100, b=60),
        xaxis=dict(showgrid=False, linecolor="#94a3b8", tickprefix="Day ", dtick=1),
        yaxis=dict(gridcolor="#f1f5f9", title="Absorbance Units")
    )
    return fig

# --- STREAMLIT UI LAYOUT ---
df_master, global_start = get_clean_data()

if not df_master.empty and global_start:
    st.title("Algae Lab Growth Analysis")
    
    tab1, tab2 = st.tabs(["Consolidated Overview", "Deep-Dive Segmentations"])
    
    with tab1:
        # Pass df_master as normal
        st.plotly_chart(build_precision_graph(df_master, 'Real 450nm', "Comparison: Chlorophyll (450nm)"), use_container_width=True)
        st.plotly_chart(build_precision_graph(df_master, 'Real 750nm', "Comparison: Cell Density (750nm)"), use_container_width=True)
        
    with tab2:
        for group in GROUPS:
            gdf_group = df_master[df_master['Group'] == group]
            if not gdf_group.empty:
                # FIX: We explicitly pass df_master here so deep dives know where all global missing days are!
                st.plotly_chart(build_precision_graph(gdf_group, ['Real 450nm', 'Real 750nm'], f"Deep Dive: {group}", master_data=df_master), use_container_width=True)
                
    with st.sidebar:
        st.markdown("### Controls")
        if st.button("Sync Live Data", use_container_width=True):
            st.cache_data.clear()
            st.sidebar.success("Cache Cleared!")
            st.rerun()
else:
    st.error("No valid datasets returned. Verify permissions or network access to the Google Sheet URL.")
