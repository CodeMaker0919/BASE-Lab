import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import io
import re

# --- CONFIG (UPDATED & FIXED) ---
# Paste the browser URL here; the cleaning function below will automatically format it for export
RAW_BROWSER_URL = "https://docs.google.com/spreadsheets/d/1X7n-R2W4QBOnAJf_QSJ0xWCJqUhrvqFpsy__LDBiQ7k/edit?gid=1065140438#gid=1065140438"

# Photoperiod tab names matching your friend's sheet tabs
GROUPS = ["12H", "16H", "24H"]

COLORS = {
    "12H": "#2563eb",   # Blue
    "16H": "#d97706",   # Amber
    "24H": "#dc2626",   # Red
    "Real 450nm": "#2563eb", 
    "Real 750nm": "#64748b"
}

st.set_page_config(page_title="Algae Lab Report", layout="wide")

def get_clean_data():
    try:
        # Extract the unique Spreadsheet ID using a regular expression
        match = re.search(r"/d/([a-zA-Z0-9-_]+)", RAW_BROWSER_URL)
        if not match:
            return pd.DataFrame(), None
        
        sheet_id = match.group(1)
        # Convert browser URL into a direct openpyxl-compatible XLSX download link
        download_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
        
        res = requests.get(download_url)
        xls = pd.read_excel(io.BytesIO(res.content), sheet_name=None, engine='openpyxl')
        all_df = []
        global_start_date = None
        
        # Pass 1: Find the absolute minimum starting date across all photoperiod timelines
        for name in GROUPS:
            if name in xls:
                temp_df = xls[name].copy()
                temp_df.columns = temp_df.columns.str.strip()
                raw_dates = pd.to_datetime(temp_df['Date'], errors='coerce').dt.normalize().dropna()
                if not raw_dates.empty:
                    sheet_min = raw_dates.min()
                    if global_start_date is None or sheet_min < global_start_date:
                        global_start_date = sheet_min

        # Pass 2: Clean, align headers, and parse data matrix arrays
        for name in GROUPS:
            if name in xls:
                temp_df = xls[name].copy()
                
                temp_df.columns = temp_df.columns.str.strip()
                # Normalize column variations to match processing expectations ('Real 450 nm' -> 'Real 450nm')
                temp_df.columns = temp_df.columns.str.replace('450 nm', '450nm').str.replace('750 nm', '750nm')
                
                # Filter out rows containing 'Muck' or manual baseline modifications
                if 'Notes' in temp_df.columns:
                    temp_df = temp_df[~temp_df['Notes'].astype(str).str.contains('Muck', na=False, case=False)]
                
                temp_df['Date'] = pd.to_datetime(temp_df['Date'], errors='coerce').dt.normalize()
                temp_df['Real 450nm'] = pd.to_numeric(temp_df['Real 450nm'], errors='coerce')
                temp_df['Real 750nm'] = pd.to_numeric(temp_df['Real 750nm'], errors='coerce')
                
                # Drop rows with critical structural empty sets
                temp_df = temp_df.dropna(subset=['Date', 'Real 450nm']).query('`Real 450nm` > 0')
                temp_df = temp_df.groupby('Date', as_index=False)[['Real 450nm', 'Real 750nm']].mean()
                temp_df['Group'] = name
                
                # Calculate elapsed days relative to the globally synced starting point
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
    timeline_source = master_data if master_data is not None else data

    # Boundary detection to dynamically introduce missing-day markers
    all_recorded_days = sorted(list(set(timeline_source['Day'].dropna().unique())))
    border_days = set()

    for i in range(len(all_recorded_days) - 1):
        d1 = all_recorded_days[i]
        d2 = all_recorded_days[i+1]
        if d2 - d1 > 1:
            border_days.add(d1)  
            border_days.add(d2)  

    for line_x in sorted(border_days):
        fig.add_vline(x=line_x, line_dash="dot", line_width=1.5, line_color="#cbd5e1")

    y_max = data[y_cols].max().max() if isinstance(data[y_cols], pd.DataFrame) else data[y_cols].max()
    y_min = data[y_cols].min().min() if isinstance(data[y_cols], pd.DataFrame) else data[y_cols].min()
    y_range = y_max - y_min if pd.notna(y_max) and pd.notna(y_min) else 1.0

    for group_name in data['Group'].unique():
        gdf = data[data['Group'] == group_name].sort_values('Day')
        if gdf.empty:
            continue
            
        min_day = int(timeline_source['Day'].min())
        max_day = int(timeline_source['Day'].max())
        full_day_range = pd.DataFrame({'Day': range(min_day, max_day + 1)})
        
        plot_data = pd.merge(full_day_range, gdf, on='Day', how='left')
        plot_data['Group'] = group_name

        for col in y_cols:
            color = COLORS.get(group_name) if len(y_cols) == 1 else COLORS.get(col)
            
            # Continuous trend tracker with structural breaks for missing intervals
            fig.add_trace(go.Scatter(
                x=plot_data['Day'], y=plot_data[col], mode='lines',
                line=dict(color=color, width=4),
                connectgaps=False, hoverinfo='skip'
            ))

            # Isolated data points visualization
            fig.add_trace(go.Scatter(
                x=gdf['Day'], y=gdf[col], mode='markers',
                marker=dict(color=color, size=10, line=dict(width=2, color="white")),
                name=f"{group_name} {col}"
            ))

            valid = gdf.dropna(subset=[col])
            if not valid.empty:
                val_start, val_end = valid.iloc[0][col], valid.iloc[-1][col]
                pct = ((val_end - val_start) / val_start * 100) if val_start != 0 else 0
                label_positions.append({
                    'x': valid.iloc[-1]['Day'], 'y': val_end, 'color': color,
                    'text': f"<b>{group_name if len(y_cols)==1 else col}</b><br>{pct:+.0f}% change"
                })

    # Non-overlapping annotation engine alignment
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
        margin=dict(r=220, l=60, t=100, b=80), 
        xaxis=dict(
            title=dict(text="<b>Timeline (Days)</b>", font=dict(size=14, color="#475569")),
            showgrid=False,   
            zeroline=False, 
            showline=True, 
            linecolor="#94a3b8", 
            tickprefix="Day ", 
            dtick=1
        ),
        yaxis=dict(gridcolor="#f1f5f9", title="Absorbance Units")
    )
    return fig

# --- AUTONOMOUS REFRESH ENGINE ---
@st.fragment(run_every=30)
def render_dashboard_content(df_master):
    tab1, tab2 = st.tabs(["Consolidated Overview", "Deep-Dive Segmentations"])
    
    with tab1:
        st.plotly_chart(build_precision_graph(df_master, 'Real 450nm', "Comparison: Chlorophyll (450nm)"), use_container_width=True)
        st.plotly_chart(build_precision_graph(df_master, 'Real 750nm', "Comparison: Cell Density (750nm)"), use_container_width=True)
        
    with tab2:
        for group in GROUPS:
            gdf_group = df_master[df_master['Group'] == group]
            if not gdf_group.empty:
                st.plotly_chart(build_precision_graph(gdf_group, ['Real 450nm', 'Real 750nm'], f"Deep Dive: {group}", master_data=df_master), use_container_width=True)


# --- MAIN PIPELINE OUTSIDE FRAGMENT OVERRIDE ---
st.title("Algae Lab Growth Analysis")

df_master, global_start = get_clean_data()

if not df_master.empty and global_start:
    with st.sidebar:
        st.markdown("### Graph Snapshot Panel")
        
        options_list = [
            "Chlorophyll Growth (450nm)",
            "Cell Density Growth (750nm)"
        ] + [f"Deep Dive: {g}" for g in GROUPS]
        
        selected_target = st.selectbox("Select graph to snapshot:", options_list)
        
        try:
            if selected_target == "Chlorophyll Growth (450nm)":
                target_fig = build_precision_graph(df_master, 'Real 450nm', "Comparison: Chlorophyll (450nm)")
            elif selected_target == "Cell Density Growth (750nm)":
                target_fig = build_precision_graph(df_master, 'Real 750nm', "Comparison: Cell Density (750nm)")
            else:
                group_name = selected_target.replace("Deep Dive: ", "")
                target_fig = build_precision_graph(df_master[df_master['Group'] == group_name], ['Real 450nm', 'Real 750nm'], f"Deep Dive: {group_name}", master_data=df_master)
            
            img_bytes = target_fig.to_image(format="png", width=1200, height=650, scale=2)
            clean_filename = f"{selected_target.lower().replace(' ', '_').replace(':', '')}_snapshot.png"
            
            st.download_button(
                label="Download Screenshot",
                data=img_bytes,
                file_name=clean_filename,
                mime="image/png",
                use_container_width=True
            )
        except Exception:
            st.error("Snapshot engine ready. Ensure 'kaleido' is installed in your runtime environment.")

    render_dashboard_content(df_master)
else:
    st.error("No valid datasets returned. Verify permissions, sheet names, or link share visibility settings.")
