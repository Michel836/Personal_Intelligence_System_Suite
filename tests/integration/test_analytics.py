#!/usr/bin/env python3
"""
Test du dashboard analytics pour le système 36TB Intelligence
"""
from pathlib import Path

from src.analytics.dashboard import AnalyticsDashboard

def test_analytics():
    """Test le système d'analytics."""
    print("Dashboard Analytics Test")
    print("=" * 50)
    
    # Initialiser le dashboard
    analytics = AnalyticsDashboard()
    
    print("Loading statistics...")
    
    # Test des stats d'overview
    stats = analytics.get_overview_stats()
    print(f"Total Files: {stats.total_files:,}")
    print(f"Total Size: {analytics.format_size(stats.total_size)}")
    print(f"File Types: {len(stats.by_type)} types found")
    print(f"Size Ranges: {len(stats.by_size_range)} ranges")
    
    # Top 5 types de fichiers
    print("\nTop 5 File Types:")
    for file_type, count in list(stats.by_type.items())[:5]:
        print(f"  - {file_type}: {count:,} files")
    
    # Distribution des tailles
    print("\nSize Distribution:")
    for size_range, count in stats.by_size_range.items():
        print(f"  - {size_range}: {count:,} files")
    
    # Fichiers récents
    print(f"\nRecent Files: {len(stats.recent_files)} found")
    for file_info in stats.recent_files[:3]:
        file_name = Path(file_info['name']).name
        size = analytics.format_size(file_info['size'])
        print(f"  - {file_name} ({size})")
    
    # Plus gros fichiers
    print(f"\nLargest Files: {len(stats.largest_files)} found")
    for file_info in stats.largest_files[:3]:
        file_name = Path(file_info['name']).name
        size = analytics.format_size(file_info['size'])
        print(f"  - {file_name} ({size})")
    
    # Distribution détaillée des types
    print("\nType Distribution with Percentages:")
    type_dist = analytics.get_type_distribution(10)
    for file_type, count, percentage in type_dist[:5]:
        print(f"  - {file_type}: {count:,} ({percentage:.1f}%)")
    
    # Stats des répertoires
    print("\nDirectory Statistics:")
    dir_stats = analytics.get_directory_stats(5)
    for directory, file_count, total_size in dir_stats:
        size_formatted = analytics.format_size(total_size)
        print(f"  - {directory}: {file_count:,} files ({size_formatted})")
    
    # Insights de recherche
    print("\nSearch Insights:")
    search_insights = analytics.get_search_insights()
    print(f"  - Searchable files: {search_insights.get('searchable_files', 0):,}")
    print(f"  - Non-searchable: {search_insights.get('non_searchable_files', 0):,}")
    
    extraction_opps = search_insights.get('extraction_opportunities', {})
    if extraction_opps:
        print("  - Extraction opportunities:")
        for ext, count in extraction_opps.items():
            print(f"    * {ext}: {count:,} files")
    
    # Timeline des 7 derniers jours
    print("\nTimeline (Last 7 days):")
    timeline = analytics.get_timeline_stats(7)
    if timeline:
        for date, count in sorted(timeline.items(), reverse=True):
            print(f"  - {date}: {count:,} files modified")
    else:
        print("  - No recent modifications found")
    
    # Test d'export
    print("\nTesting Export...")
    export_path = analytics.export_stats()
    if export_path:
        print(f"Report exported to: {export_path}")
        
        # Vérifier le fichier
        if Path(export_path).exists():
            file_size = Path(export_path).stat().st_size
            print(f"Export file size: {analytics.format_size(file_size)}")
    
    print("\nAnalytics test completed successfully!")

if __name__ == "__main__":
    test_analytics()