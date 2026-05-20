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

    # Use master dataset to figure out the true global missing days
    timeline_source = master_data if master_data is not None else data

    if timeline_source.empty:
        return fig

    # --- NEW GLOBAL TIMELINE ANALYSIS ---
    min_day = int(timeline_source['Day'].min())
    max_day = int(timeline_source['Day'].max())
    all_possible_days = set(range(min_day, max_day + 1))
    
    # A day is only considered "collected" if ANY group successfully has a data point on it
    collected_days = set(timeline_source['Day'].dropna().unique())
    missing_days = all_possible_days - collected_days

    # Draw the global dotted vertical lines for completely missed lab days
    for md in sorted(missing_days):
        fig.add_vline(x=md, line_dash="dot", line_width=1.5, line_color="#cbd5e1")

    # Calculate global scale boundaries for label adjustments
    y_max = data[y_cols].max().max() if isinstance(data[y_cols], pd.DataFrame) else data[y_cols].max()
    y_min = data[y_cols].min().min() if isinstance(data[y_cols], pd.DataFrame) else data[y_cols].min()
    y_range = y_max - y_min if pd.notna(y_max) and pd.notna(y_min) else 1.0

    for group_name in data['Group'].unique():
        gdf = data[data['Group'] == group_name].sort_values('Day')
        if gdf.empty:
            continue
        
        # --- AUTOMATIC LINE BREAKING VIA REINDEXING ---
        # Reindexing introduces standard NaNs on missing days, forcing Plotly to break the trends cleanly
        full_day_range = range(int(gdf['Day'].min()), int(gdf['Day'].max()) + 1)
        plot_data = gdf.set_index('Day').reindex(full_day_range).reset_index()
        plot_data['Group'] = group_name

        # --- DATA VECTOR RENDERING ---
        for col in y_cols:
            color = COLORS.get(group_name) if len(y_cols) == 1 else COLORS.get(col)
            
            # Continuous line segments (breaks dynamically over missing global days due to Reindexed NaNs)
            fig.add_trace(go.Scatter(
                x=plot_data['Day'], y=plot_data[col], mode='lines',
                line=dict(color=color, width=4),
                connectgaps=False, hoverinfo='skip'
            ))

            # Sample dots (drawn only on the clean real rows to prevent blank hover shapes)
            fig.add_trace(go.Scatter(
                x=gdf['Day'], y=gdf[col], mode='markers',
                marker=dict(color=color, size=10, line=dict(width=2, color="white")),
                name=f"{group_name} {col}"
            ))

            # End Annotations Calculation
            valid = gdf.dropna(subset=[col])
            if not valid.empty:
                val_start, val_end = valid.iloc[0][col], valid.iloc[-1][col]
                pct = ((val_end - val_start) / val_start * 100) if val_start != 0 else 0
                label_positions.append({
                    'x': valid.iloc[-1]['Day'], 'y': val_end, 'color': color,
                    'text': f"<b>{group_name if len(y_cols)==1 else col}</b><br>{pct:+.0f}% change"
                })

    # --- BI-DIRECTIONAL FORCE LABELS ---
    if label_positions:
        label_positions.sort(key=lambda x: x['y'])
        min_distance = max(0.12, y_range * 0.08) 
        
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
        st.plotly_chart(build_precision_graph(df_master, 'Real 450nm', "Comparison: Chlorophyll (450nm)"), use_container_width=True)
        st.plotly_chart(build_precision_graph(df_master, 'Real 750nm', "Comparison: Cell Density (750nm)"), use_container_width=True)
        
    with tab2:
        for group in GROUPS:
            gdf_group = df_master[df_master['Group'] == group]
            if not gdf_group.empty:
                st.plotly_chart(build_precision_graph(gdf_group, ['Real 450nm', 'Real 750nm'], f"Deep Dive: {group}", master_data=df_master), use_container_width=True)
                
    with st.sidebar:
        st.markdown("### Controls")
        if st.button("Sync Live Data", use_container_width=True):
            st.cache_data.clear()
            st.sidebar.success("Cache Cleared!")
            st.rerun()
else:
    st.error("No valid datasets returned. Verify permissions or network access to the Google Sheet URL.")
