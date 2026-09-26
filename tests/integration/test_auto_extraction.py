#!/usr/bin/env python3
"""
Test du système d'auto-extraction pour 36TB Intelligence
"""
from src.extractors.auto_extractor import AutoExtractor

def test_auto_extraction():
    """Test le système d'auto-extraction."""
    print("Auto-Extraction Test")
    print("=" * 50)
    
    # Initialize auto extractor
    auto_extractor = AutoExtractor()
    
    print("Getting extraction candidates...")
    
    # Get candidates
    candidates = auto_extractor.get_extraction_candidates(limit=20)
    print(f"Found {len(candidates)} files ready for extraction")
    
    if not candidates:
        print("No files need extraction - all done!")
        return
    
    # Show some examples
    print("\nExample files to extract:")
    for i, candidate in enumerate(candidates[:5], 1):
        file_type = candidate.get('file_type', 'unknown')
        size_mb = candidate.get('size_bytes', 0) / (1024 * 1024)
        print(f"  {i}. {candidate['filename']} ({file_type}, {size_mb:.1f} MB)")
    
    # Get estimation
    estimation = auto_extractor.estimate_extraction_time(len(candidates))
    print(f"\nEstimated time: {estimation['estimated_minutes']:.1f} minutes for {len(candidates)} files")
    
    # Test extraction on a small batch
    print("\nTesting extraction on 3 files...")
    
    test_candidates = candidates[:3]
    
    try:
        # Simple progress callback
        def progress_callback(processed, total, results):
            print(f"Progress: {processed}/{total} ({results['successful']} successful)")
        
        # Extract priority batch (small test)
        results = auto_extractor.extract_priority_batch(3, progress_callback)
        
        print(f"\nTest Results:")
        print(f"  Processed: {results['processed']}")
        print(f"  Successful: {results['successful']}")
        print(f"  Failed: {results['failed']}")
        
        if results.get('details'):
            print("\nDetailed results:")
            for detail in results['details'][:3]:
                status = "SUCCESS" if detail['success'] else "FAILED"
                content_len = detail['content_length']
                time_taken = detail['extraction_time']
                print(f"  - {detail['filename']}: {status} ({content_len} chars, {time_taken:.2f}s)")
        
        # Get stats
        stats = auto_extractor.get_extraction_stats()
        print(f"\nExtraction Statistics:")
        print(f"  Total processed: {stats['processed']}")
        print(f"  Successful: {stats['successful']}")
        print(f"  Failed: {stats['failed']}")
        
        manager_stats = stats.get('extraction_manager', {})
        if manager_stats:
            print(f"  Success rate: {manager_stats.get('success_rate', 0):.1f}%")
            print(f"  Avg time/file: {manager_stats.get('avg_extraction_time', 0):.2f}s")
        
        print("\nAuto-extraction test completed successfully!")
    
    except Exception as e:
        print(f"Error during extraction test: {e}")

if __name__ == "__main__":
    test_auto_extraction()