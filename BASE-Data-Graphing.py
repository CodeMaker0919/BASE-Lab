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
                temp_df['Date'] = pd.to_datetime(temp_df['Date'], errors='coerce').dt.normalize()
                
                # 1. Find the true start date (Row 1) BEFORE filtering out the muck
                if not temp_df['Date'].dropna().empty:
                    true_start_date = temp_df['Date'].dropna().min()
                else:
                    continue
                
                # 2. Filter out the muck notes now
                if 'Notes' in temp_df.columns:
                    temp_df = temp_df[~temp_df['Notes'].astype(str).str.contains('Muck', na=False, case=False)]
                
                temp_df['Real 450nm'] = pd.to_numeric(temp_df['Real 450nm'], errors='coerce')
                temp_df['Real 750nm'] = pd.to_numeric(temp_df['Real 750nm'], errors='coerce')
                temp_df = temp_df.dropna(subset=['Date', 'Real 450nm']).query('`Real 450nm` > 0')
                temp_df = temp_df.groupby('Date', as_index=False)[['Real 450nm', 'Real 750nm']].mean()
                
                # 3. Swap the X-axis column from Date to relative Day integers (Day 1, Day 2, etc.)
                temp_df['Date'] = (temp_df['Date'] - true_start_date).dt.days + 1
                
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
        
        # 1. ADD FLAG: Mark all actual data points as Real
        gdf['IsReal'] = True 
        plot_data = gdf.copy()

        # --- GHOST POINT INTERPOLATION ---
        for i in range(len(gdf) - 1):
            d1, d2 = gdf.iloc[i]['Date'], gdf.iloc[i+1]['Date']
            
            if (d2 - d1) > 1: 
                gap_start, gap_end = d1 + 1, d2
                fig.add_vline(x=gap_start, line_dash="dot", line_width=1.5, line_color="#cbd5e1")
                fig.add_vline(x=gap_end, line_dash="dot", line_width=1.5, line_color="#cbd5e1")
                
                # 2. ADD FLAG: Mark interpolated boundary points as NOT Real
                ghost_row = {'Date': gap_start, 'Group': group_name, 'IsReal': False}
                break_row = {'Date': gap_start + 0.001, 'Group': group_name, 'IsReal': False} 
                
                for col in y_cols:
                    slope = (gdf.iloc[i+1][col] - gdf.iloc[i][col]) / (d2 - d1)
                    ghost_row[col] = gdf.iloc[i][col] + slope
                    break_row[col] = None
                
                plot_data = pd.concat([plot_data, pd.DataFrame([ghost_row, break_row])], ignore_index=True)
        plot_data = plot_data.sort_values('Date')

        for col in y_cols:
            color = COLORS.get(group_name) if len(y_cols) == 1 else COLORS.get(col)
            
            # 3. DYNAMIC STYLING: Size 10 for real points, size 0 for ghost points
            m_sizes = [10 if is_real else 0 for is_real in plot_data['IsReal']]
            m_lines = [2 if is_real else 0 for is_real in plot_data['IsReal']]

            fig.add_trace(go.Scatter(
                x=plot_data['Date'], y=plot_data[col], mode='lines+markers',
                line=dict(color=color, width=4),
                # 4. APPLY STYLES: Pass the arrays to the marker dictionary
                marker=dict(size=m_sizes, line=dict(width=m_lines, color="white")),
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
        title=dict(text=f"<b>{title}</b>", font=dict(size=26, color="white")), # Make title white
        template="plotly_dark", # Change from plotly_white to plotly_dark
        paper_bgcolor="#000000", # A rich, solid dark slate color
        plot_bgcolor="#000000",  # A rich, solid dark slate color
        showlegend=False, height=750,
        margin=dict(r=220, l=60, t=100, b=60),
        xaxis=dict(
            showgrid=False, 
            linecolor="#64748b",
            tickprefix="Day ",  
            dtick=1             
        ),
        yaxis=dict(gridcolor="#FFFFFF", title="Absorbance Units")
    )
    return fig

# --- RENDER ---
df_master = get_clean_data()
if not df_master.empty:
    st.title("Algae Lab Growth Analysis")
    
    # ADD theme=None TO ALL CHART CALLS
    st.plotly_chart(build_precision_graph(df_master, 'Real 450nm', "Comparison: Chlorophyll (450nm)"), use_container_width=True, theme=None)
    st.plotly_chart(build_precision_graph(df_master, 'Real 750nm', "Comparison: Cell Density (750nm)"), use_container_width=True, theme=None)
    
    st.divider()
    for group in GROUPS:
        gdf_group = df_master[df_master['Group'] == group]
        if not gdf_group.empty:
            st.plotly_chart(build_precision_graph(gdf_group, ['Real 450nm', 'Real 750nm'], f"Deep Dive: {group}"), use_container_width=True, theme=None)
            
    if st.sidebar.button("Sync Live Data"):
        st.cache_data.clear()
        st.rerun()
else:
    st.error("No data found. Check permissions.")

