"""Revolutionary visualizations for 36TB Intelligence."""

import sqlite3
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import hashlib
import re
from collections import defaultdict, Counter
import math

from loguru import logger

try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    import plotly.figure_factory as ff
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    go = None
    px = None
    logger.warning("plotly not available - advanced visualizations disabled")

try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    NETWORKX_AVAILABLE = False
    nx = None
    logger.warning("networkx not available - network graphs disabled")


class AdvancedVisualizations:
    """Advanced visualization system for document analytics."""
    
    def __init__(self, db_path=None):
        from ..core.database import default_db_path
        self.db_path = db_path or default_db_path()
        self.color_schemes = {
            'primary': ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2'],
            'neon': ['#ff006e', '#8338ec', '#3a86ff', '#06ffa5', '#ffbe0b', '#fb5607'],
            'dark': ['#264653', '#2a9d8f', '#e9c46a', '#f4a261', '#e76f51', '#e63946'],
            'gradient': ['#667eea', '#764ba2', '#f093fb', '#f5576c', '#4facfe', '#00f2fe']
        }
    
    def is_available(self) -> bool:
        """Check if visualization libraries are available."""
        return PLOTLY_AVAILABLE
    
    # Data Fetchers
    def _get_files_data(self) -> pd.DataFrame:
        """Get files data for visualization."""
        try:
            conn = sqlite3.connect(self.db_path)
            
            query = """
                SELECT f.*, 
                       s.summary_text, s.topics, s.sentiment,
                       CASE WHEN fav.file_id IS NOT NULL THEN 1 ELSE 0 END as is_favorite
                FROM files f
                LEFT JOIN summaries s ON f.id = s.file_id
                LEFT JOIN favorites fav ON f.id = fav.file_id
                WHERE f.size_bytes > 0
            """
            
            df = pd.read_sql_query(query, conn)
            conn.close()
            
            # Process data
            if len(df) > 0:
                df['size_mb'] = df['size_bytes'] / (1024 * 1024)
                df['size_category'] = pd.cut(df['size_mb'], 
                                           bins=[0, 1, 10, 100, 1000, float('inf')],
                                           labels=['<1MB', '1-10MB', '10-100MB', '100MB-1GB', '>1GB'])
                
                # Parse modified date
                df['modified_at'] = pd.to_datetime(df['modified_at'], errors='coerce')
                df['year'] = df['modified_at'].dt.year
                df['month'] = df['modified_at'].dt.month
                df['day_of_week'] = df['modified_at'].dt.day_name()
                df['hour'] = df['modified_at'].dt.hour
                
                # Extract file extensions
                df['extension'] = df['filename'].str.extract(r'\.([^.]+)$')[0].fillna('no_ext')
                
                # Add folder depth
                df['folder_depth'] = df['path'].str.count('\\\\') + df['path'].str.count('/')
                
                # Parse topics if available
                if 'topics' in df.columns:
                    df['topic_count'] = df['topics'].apply(lambda x: len(json.loads(x)) if x and x != '' else 0)
            
            return df
            
        except Exception as e:
            logger.error(f"Error getting files data: {e}")
            return pd.DataFrame()
    
    def _get_tags_data(self) -> pd.DataFrame:
        """Get tags data for visualization."""
        try:
            conn = sqlite3.connect(self.db_path)
            
            query = """
                SELECT t.*, COUNT(ft.file_id) as file_count
                FROM tags t
                LEFT JOIN file_tags ft ON t.id = ft.tag_id
                GROUP BY t.id
                ORDER BY t.usage_count DESC
            """
            
            df = pd.read_sql_query(query, conn)
            conn.close()
            
            return df
            
        except Exception as e:
            logger.error(f"Error getting tags data: {e}")
            return pd.DataFrame()
    
    # Revolutionary Visualizations
    def create_file_universe_3d(self, sample_size: int = 1000):
        """Create 3D universe of files with size, type, and time dimensions."""
        if not PLOTLY_AVAILABLE:
            return None
        
        df = self._get_files_data()
        if df.empty:
            return None
        
        # Sample data for performance
        if len(df) > sample_size:
            df = df.sample(n=sample_size, random_state=42)
        
        # Create 3D coordinates
        df = df.dropna(subset=['modified_at'])
        
        # X: Time (days since oldest file)
        min_date = df['modified_at'].min()
        df['x_coord'] = (df['modified_at'] - min_date).dt.days
        
        # Y: File size (log scale)
        df['y_coord'] = np.log10(df['size_bytes'].clip(lower=1))
        
        # Z: Folder depth
        df['z_coord'] = df['folder_depth']
        
        # Color by file type
        type_colors = {
            'document': '#ff6b6b',
            'image': '#4ecdc4', 
            'video': '#45b7d1',
            'audio': '#f9ca24',
            'text': '#6c5ce7',
            'code': '#a29bfe',
            'archive': '#fd79a8',
            'other': '#636e72'
        }
        
        df['color'] = df['file_type'].map(type_colors).fillna('#636e72')
        
        # Create 3D scatter plot
        fig = go.Figure()
        
        for file_type in df['file_type'].unique():
            type_data = df[df['file_type'] == file_type]
            
            fig.add_trace(go.Scatter3d(
                x=type_data['x_coord'],
                y=type_data['y_coord'],
                z=type_data['z_coord'],
                mode='markers',
                marker=dict(
                    size=np.clip(type_data['size_mb'] ** 0.3, 3, 15),
                    color=type_data['color'].iloc[0],
                    opacity=0.8,
                    line=dict(width=0.5, color='white')
                ),
                text=type_data['filename'],
                hovertemplate=(
                    '<b>%{text}</b><br>' +
                    'Type: ' + file_type + '<br>' +
                    'Size: %{customdata[0]:.1f} MB<br>' +
                    'Modified: %{customdata[1]}<br>' +
                    'Depth: %{z}<br>' +
                    '<extra></extra>'
                ),
                customdata=list(zip(type_data['size_mb'], type_data['modified_at'].dt.strftime('%Y-%m-%d'))),
                name=file_type.title(),
                showlegend=True
            ))
        
        fig.update_layout(
            title={
                'text': '🌌 File Universe - 3D Document Galaxy',
                'x': 0.5,
                'font': {'size': 20, 'color': '#2c3e50'}
            },
            scene=dict(
                xaxis_title='Time (Days Since Oldest)',
                yaxis_title='File Size (Log Scale)',
                zaxis_title='Folder Depth',
                bgcolor='rgba(0,0,0,0)',
                camera=dict(eye=dict(x=1.5, y=1.5, z=1.5))
            ),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            height=700,
            showlegend=True,
            legend=dict(x=0, y=1, bgcolor='rgba(255,255,255,0.8)')
        )
        
        return fig
    
    def create_content_heatmap_calendar(self):
        """Create GitHub-style calendar heatmap of file activities."""
        if not PLOTLY_AVAILABLE:
            return None
        
        df = self._get_files_data()
        if df.empty:
            return None
        
        # Get last 365 days of data
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        
        df = df[df['modified_at'] >= start_date]
        
        if df.empty:
            return None
        
        # Create daily activity counts
        df['date'] = df['modified_at'].dt.date
        daily_counts = df.groupby('date').agg({
            'id': 'count',
            'size_bytes': 'sum'
        }).reset_index()
        
        daily_counts.columns = ['date', 'file_count', 'total_size']
        daily_counts['size_mb'] = daily_counts['total_size'] / (1024 * 1024)
        
        # Create calendar grid
        date_range = pd.date_range(start=start_date.date(), end=end_date.date(), freq='D')
        calendar_data = pd.DataFrame({'date': date_range})
        calendar_data = calendar_data.merge(daily_counts, on='date', how='left').fillna(0)
        
        # Calculate week and day positions for calendar layout
        calendar_data['week'] = calendar_data['date'].apply(lambda x: x.isocalendar()[1])
        calendar_data['weekday'] = calendar_data['date'].apply(lambda x: x.weekday())
        
        # Normalize week numbers
        min_week = calendar_data['week'].min()
        calendar_data['week_norm'] = calendar_data['week'] - min_week
        
        # Create heatmap
        z_data = []
        hover_text = []
        
        for week in range(calendar_data['week_norm'].max() + 1):
            week_data = calendar_data[calendar_data['week_norm'] == week]
            week_values = []
            week_hover = []
            
            for day in range(7):
                day_data = week_data[week_data['weekday'] == day]
                if not day_data.empty:
                    value = day_data['file_count'].iloc[0]
                    size = day_data['size_mb'].iloc[0]
                    date_str = day_data['date'].iloc[0].strftime('%Y-%m-%d')
                    week_values.append(value)
                    week_hover.append(f"{date_str}<br>Files: {value}<br>Size: {size:.1f} MB")
                else:
                    week_values.append(0)
                    week_hover.append("")
            
            z_data.append(week_values)
            hover_text.append(week_hover)
        
        # Transpose for proper orientation
        z_data = list(map(list, zip(*z_data)))
        hover_text = list(map(list, zip(*hover_text)))
        
        fig = go.Figure(data=go.Heatmap(
            z=z_data,
            text=hover_text,
            hovertemplate='%{text}<extra></extra>',
            colorscale='Viridis',
            showscale=True,
            colorbar=dict(title="Files Modified")
        ))
        
        # Add day labels
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        
        fig.update_layout(
            title={
                'text': '📅 Content Activity Heatmap - File Modification Calendar',
                'x': 0.5,
                'font': {'size': 18, 'color': '#2c3e50'}
            },
            xaxis=dict(
                title='Week',
                showticklabels=False
            ),
            yaxis=dict(
                title='Day of Week',
                tickvals=list(range(7)),
                ticktext=days,
                tickmode='array'
            ),
            height=300,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)'
        )
        
        return fig
    
    def create_file_type_sunburst(self):
        """Create sunburst chart of file types and extensions."""
        if not PLOTLY_AVAILABLE:
            return None
        
        df = self._get_files_data()
        if df.empty:
            return None
        
        # Create hierarchical data
        hierarchy_data = []
        
        # Level 1: File types
        type_counts = df.groupby('file_type').agg({
            'id': 'count',
            'size_bytes': 'sum'
        }).reset_index()
        
        for _, row in type_counts.iterrows():
            hierarchy_data.append({
                'ids': row['file_type'],
                'labels': row['file_type'].title(),
                'parents': '',
                'values': row['id'],
                'hover': f"{row['file_type'].title()}<br>Files: {row['id']}<br>Size: {row['size_bytes']/1024/1024:.1f} MB"
            })
        
        # Level 2: Extensions within types
        ext_counts = df.groupby(['file_type', 'extension']).agg({
            'id': 'count',
            'size_bytes': 'sum'
        }).reset_index()
        
        for _, row in ext_counts.iterrows():
            if row['id'] >= 5:  # Only show extensions with 5+ files
                hierarchy_data.append({
                    'ids': f"{row['file_type']}_{row['extension']}",
                    'labels': f".{row['extension']}",
                    'parents': row['file_type'],
                    'values': row['id'],
                    'hover': f".{row['extension']}<br>Files: {row['id']}<br>Size: {row['size_bytes']/1024/1024:.1f} MB"
                })
        
        # Convert to DataFrame for Plotly
        hierarchy_df = pd.DataFrame(hierarchy_data)
        
        fig = go.Figure(go.Sunburst(
            ids=hierarchy_df['ids'],
            labels=hierarchy_df['labels'],
            parents=hierarchy_df['parents'],
            values=hierarchy_df['values'],
            hovertext=hierarchy_df['hover'],
            hovertemplate='%{hovertext}<extra></extra>',
            branchvalues="total",
            maxdepth=3,
            insidetextorientation='radial'
        ))
        
        fig.update_layout(
            title={
                'text': '☀️ File Type Universe - Hierarchical Distribution',
                'x': 0.5,
                'font': {'size': 18, 'color': '#2c3e50'}
            },
            font_size=12,
            height=600,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)'
        )
        
        return fig
    
    def create_document_network_graph(self, max_nodes: int = 100):
        """Create network graph showing document relationships."""
        if not PLOTLY_AVAILABLE or not NETWORKX_AVAILABLE:
            return None
        
        try:
            conn = sqlite3.connect(self.db_path)
            
            # Get files with tags for relationship mapping
            query = """
                SELECT f.id, f.filename, f.file_type, f.size_bytes,
                       GROUP_CONCAT(t.name) as tags,
                       s.topics
                FROM files f
                LEFT JOIN file_tags ft ON f.id = ft.file_id
                LEFT JOIN tags t ON ft.tag_id = t.id
                LEFT JOIN summaries s ON f.id = s.file_id
                WHERE f.content_extracted = 1
                GROUP BY f.id
                LIMIT ?
            """
            
            df = pd.read_sql_query(query, conn, params=(max_nodes,))
            conn.close()
            
            if df.empty:
                return None
            
            # Create network graph
            G = nx.Graph()
            
            # Add nodes (files)
            for _, row in df.iterrows():
                G.add_node(row['id'], 
                          filename=row['filename'][:30],
                          file_type=row['file_type'],
                          size=row['size_bytes'])
            
            # Add edges based on shared tags or topics
            for i, row1 in df.iterrows():
                tags1 = set(row1['tags'].split(',')) if row1['tags'] else set()
                topics1 = set(json.loads(row1['topics'])) if row1['topics'] else set()
                combined1 = tags1.union(topics1)
                
                for j, row2 in df.iterrows():
                    if i >= j:
                        continue
                    
                    tags2 = set(row2['tags'].split(',')) if row2['tags'] else set()
                    topics2 = set(json.loads(row2['topics'])) if row2['topics'] else set()
                    combined2 = tags2.union(topics2)
                    
                    # Calculate similarity
                    if combined1 and combined2:
                        overlap = len(combined1.intersection(combined2))
                        if overlap > 0:
                            similarity = overlap / len(combined1.union(combined2))
                            if similarity > 0.1:  # Only connect if >10% similarity
                                G.add_edge(row1['id'], row2['id'], weight=similarity)
            
            # Create layout
            pos = nx.spring_layout(G, k=3, iterations=50)
            
            # Prepare node traces
            node_trace = go.Scatter(
                x=[pos[node][0] for node in G.nodes()],
                y=[pos[node][1] for node in G.nodes()],
                mode='markers+text',
                text=[G.nodes[node]['filename'] for node in G.nodes()],
                textposition="middle center",
                textfont=dict(size=8),
                hovertext=[
                    f"{G.nodes[node]['filename']}<br>"
                    f"Type: {G.nodes[node]['file_type']}<br>"
                    f"Size: {G.nodes[node]['size']/1024:.1f} KB<br>"
                    f"Connections: {len(list(G.neighbors(node)))}"
                    for node in G.nodes()
                ],
                hovertemplate='%{hovertext}<extra></extra>',
                marker=dict(
                    size=[np.log10(G.nodes[node]['size']) * 3 for node in G.nodes()],
                    color=[hash(G.nodes[node]['file_type']) % 7 for node in G.nodes()],
                    colorscale='Viridis',
                    line=dict(width=2, color='white')
                )
            )
            
            # Prepare edge traces
            edge_x = []
            edge_y = []
            
            for edge in G.edges():
                x0, y0 = pos[edge[0]]
                x1, y1 = pos[edge[1]]
                edge_x.extend([x0, x1, None])
                edge_y.extend([y0, y1, None])
            
            edge_trace = go.Scatter(
                x=edge_x, 
                y=edge_y,
                line=dict(width=1, color='rgba(125,125,125,0.5)'),
                hoverinfo='none',
                mode='lines'
            )
            
            fig = go.Figure(data=[edge_trace, node_trace])
            
            fig.update_layout(
                title={
                    'text': '🕸️ Document Relationship Network - Connected by Tags & Topics',
                    'x': 0.5,
                    'font': {'size': 18, 'color': '#2c3e50'}
                },
                showlegend=False,
                hovermode='closest',
                margin=dict(b=20,l=5,r=5,t=40),
                annotations=[ dict(
                    text="Documents connected by shared tags and AI-detected topics",
                    showarrow=False,
                    xref="paper", yref="paper",
                    x=0.005, y=-0.002,
                    xanchor='left', yanchor='bottom',
                    font=dict(color='gray', size=12)
                )],
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                height=600,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)'
            )
            
            return fig
            
        except Exception as e:
            logger.error(f"Error creating network graph: {e}")
            return None
    
    def create_ai_insights_radar(self):
        """Create radar chart of AI insights and document intelligence."""
        if not PLOTLY_AVAILABLE:
            return None
        
        try:
            conn = sqlite3.connect(self.db_path)
            
            # Get AI insights data
            stats = {}
            
            # Summary stats
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM summaries")
            stats['ai_summaries'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM files WHERE content_extracted = 1")
            stats['extracted_files'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tags")
            stats['total_tags'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM favorites")
            stats['favorites'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM qa_history")
            stats['ai_questions'] = cursor.fetchone()[0] if 'qa_history' in [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")] else 0
            
            # Content diversity
            cursor.execute("SELECT COUNT(DISTINCT file_type) FROM files")
            stats['file_types'] = cursor.fetchone()[0]
            
            conn.close()
            
            # Normalize values to 0-100 scale
            max_files = max(stats['extracted_files'], 1000)  # Assume 1000 as good baseline
            
            metrics = {
                'AI Summaries': min(stats['ai_summaries'] / max_files * 100, 100),
                'Content Extraction': min(stats['extracted_files'] / max_files * 100, 100),
                'Organization (Tags)': min(stats['total_tags'] / 50 * 100, 100),  # 50 tags = 100%
                'Favorites': min(stats['favorites'] / max_files * 0.1 * 100, 100),  # 10% favorites = 100%
                'AI Questions': min(stats['ai_questions'] / 100 * 100, 100),  # 100 questions = 100%
                'Content Diversity': min(stats['file_types'] / 8 * 100, 100)  # 8 file types = 100%
            }
            
            categories = list(metrics.keys())
            values = list(metrics.values())
            
            # Close the radar chart
            values += [values[0]]
            categories += [categories[0]]
            
            fig = go.Figure()
            
            fig.add_trace(go.Scatterpolar(
                r=values,
                theta=categories,
                fill='toself',
                fillcolor='rgba(67, 97, 238, 0.3)',
                line=dict(color='rgba(67, 97, 238, 1)', width=3),
                marker=dict(size=8, color='rgba(67, 97, 238, 1)'),
                name='Intelligence Score'
            ))
            
            fig.update_layout(
                title={
                    'text': '🧠 AI Intelligence Radar - System Capabilities Analysis',
                    'x': 0.5,
                    'font': {'size': 18, 'color': '#2c3e50'}
                },
                polar=dict(
                    radialaxis=dict(
                        visible=True,
                        range=[0, 100],
                        tickvals=[20, 40, 60, 80, 100],
                        ticktext=['20%', '40%', '60%', '80%', '100%']
                    )
                ),
                showlegend=True,
                height=500,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)'
            )
            
            return fig
            
        except Exception as e:
            logger.error(f"Error creating AI insights radar: {e}")
            return None
    
    def create_size_distribution_violin(self):
        """Create violin plot of file size distributions by type."""
        if not PLOTLY_AVAILABLE:
            return None
        
        df = self._get_files_data()
        if df.empty:
            return None
        
        # Filter out extreme outliers for better visualization
        df = df[df['size_mb'] < df['size_mb'].quantile(0.95)]
        
        fig = go.Figure()
        
        colors = self.color_schemes['neon']
        
        for i, file_type in enumerate(df['file_type'].unique()):
            type_data = df[df['file_type'] == file_type]
            
            fig.add_trace(go.Violin(
                y=type_data['size_mb'],
                name=file_type.title(),
                box_visible=True,
                meanline_visible=True,
                fillcolor=colors[i % len(colors)],
                opacity=0.7,
                hovertemplate=(
                    f'<b>{file_type.title()}</b><br>' +
                    'Size: %{y:.1f} MB<br>' +
                    '<extra></extra>'
                )
            ))
        
        fig.update_layout(
            title={
                'text': '🎻 File Size Symphony - Distribution by Type',
                'x': 0.5,
                'font': {'size': 18, 'color': '#2c3e50'}
            },
            yaxis_title="File Size (MB)",
            xaxis_title="File Type",
            height=500,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            showlegend=False
        )
        
        return fig
    
    def create_temporal_flow_chart(self):
        """Create temporal flow chart showing file creation patterns."""
        if not PLOTLY_AVAILABLE:
            return None
        
        df = self._get_files_data()
        if df.empty:
            return None
        
        # Group by month and file type
        df['month_year'] = df['modified_at'].dt.to_period('M')
        
        temporal_data = df.groupby(['month_year', 'file_type']).size().reset_index(name='count')
        temporal_data['date'] = temporal_data['month_year'].dt.to_timestamp()
        
        fig = go.Figure()
        
        colors = self.color_schemes['gradient']
        
        for i, file_type in enumerate(temporal_data['file_type'].unique()):
            type_data = temporal_data[temporal_data['file_type'] == file_type]
            
            fig.add_trace(go.Scatter(
                x=type_data['date'],
                y=type_data['count'],
                mode='lines+markers',
                name=file_type.title(),
                line=dict(
                    color=colors[i % len(colors)],
                    width=3
                ),
                marker=dict(
                    size=8,
                    color=colors[i % len(colors)]
                ),
                fill='tonexty' if i > 0 else 'tozeroy',
                fillcolor=f'rgba{tuple(list(int(colors[i % len(colors)][j:j+2], 16) for j in (1, 3, 5)) + [0.3])}'
            ))
        
        fig.update_layout(
            title={
                'text': '🌊 Temporal Document Flow - File Creation Over Time',
                'x': 0.5,
                'font': {'size': 18, 'color': '#2c3e50'}
            },
            xaxis_title="Time",
            yaxis_title="Files Created",
            height=400,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            hovermode='x unified'
        )
        
        return fig
    
    def create_folder_treemap(self):
        """Create treemap of folder structure and sizes."""
        if not PLOTLY_AVAILABLE:
            return None
        
        df = self._get_files_data()
        if df.empty:
            return None
        
        # Extract folder structure
        df['folder'] = df['path'].apply(lambda x: str(Path(x).parent))
        
        # Group by folders
        folder_data = df.groupby('folder').agg({
            'id': 'count',
            'size_bytes': 'sum',
            'file_type': lambda x: x.mode().iloc[0] if not x.empty else 'mixed'
        }).reset_index()
        
        folder_data['size_mb'] = folder_data['size_bytes'] / (1024 * 1024)
        
        # Limit to top folders for readability
        folder_data = folder_data.nlargest(20, 'size_mb')
        
        # Backslash kept in a variable: f-string expressions cannot contain
        # backslashes on Python 3.11 (the declared/CI interpreter).
        win_sep = '\\'
        fig = go.Figure(go.Treemap(
            labels=folder_data['folder'].apply(lambda x: x.split(win_sep)[-1] or x.split('/')[-1] or 'Root'),
            parents=["" for _ in range(len(folder_data))],
            values=folder_data['size_mb'],
            text=[f"{row['folder'].split(win_sep)[-1] or 'Root'}<br>{row['id']} files<br>{row['size_mb']:.1f} MB"
                  for _, row in folder_data.iterrows()],
            textinfo="label+text",
            hovertemplate='<b>%{label}</b><br>Size: %{value:.1f} MB<br><extra></extra>',
            maxdepth=3,
            textfont_size=10
        ))
        
        fig.update_layout(
            title={
                'text': '🗂️ Folder Territory Map - Storage Distribution',
                'x': 0.5,
                'font': {'size': 18, 'color': '#2c3e50'}
            },
            height=500,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)'
        )
        
        return fig
    
    def get_system_stats(self) -> Dict[str, Any]:
        """Get comprehensive system statistics."""
        try:
            df = self._get_files_data()
            
            if df.empty:
                return {}
            
            stats = {
                'total_files': len(df),
                'total_size_gb': df['size_bytes'].sum() / (1024**3),
                'file_types': df['file_type'].nunique(),
                'avg_file_size_mb': df['size_mb'].mean(),
                'largest_file_mb': df['size_mb'].max(),
                'oldest_file': df['modified_at'].min().strftime('%Y-%m-%d') if not df['modified_at'].isnull().all() else 'Unknown',
                'newest_file': df['modified_at'].max().strftime('%Y-%m-%d') if not df['modified_at'].isnull().all() else 'Unknown',
                'extensions_count': df['extension'].nunique(),
                'favorites_count': df['is_favorite'].sum(),
                'with_summaries': len(df[df['summary_text'].notna()]),
                'folder_depth_avg': df['folder_depth'].mean(),
                'content_extracted': len(df[df['topic_count'] > 0]) if 'topic_count' in df.columns else 0
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting system stats: {e}")
            return {}