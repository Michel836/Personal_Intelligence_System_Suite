"""Installation verification script for 36TB Intelligence."""

import sys
import subprocess
import importlib
from pathlib import Path
from loguru import logger

# Required packages
REQUIRED_PACKAGES = [
    "fastapi",
    "streamlit", 
    "psycopg",
    "redis",
    "sentence_transformers",
    "torch",
    "spacy",
    "tesseract",
    "PIL",
    "pandas",
    "numpy",
]

def check_python_version():
    """Check Python version."""
    logger.info("Checking Python version...")
    version = sys.version_info
    
    if version.major == 3 and version.minor >= 11:
        logger.success(f"✅ Python {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        logger.error(f"❌ Python {version.major}.{version.minor}.{version.micro} - Need 3.11+")
        return False

def check_packages():
    """Check required Python packages."""
    logger.info("Checking required packages...")
    missing = []
    
    for package in REQUIRED_PACKAGES:
        try:
            importlib.import_module(package)
            logger.success(f"✅ {package}")
        except ImportError:
            logger.error(f"❌ {package} - Missing")
            missing.append(package)
    
    return len(missing) == 0

def check_gpu():
    """Check GPU availability."""
    logger.info("Checking GPU support...")
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            logger.success(f"✅ GPU: {gpu_name} ({gpu_memory:.1f}GB)")
            return True
        else:
            logger.warning("⚠️  No CUDA GPU detected - CPU only mode")
            return False
    except ImportError:
        logger.error("❌ PyTorch not installed")
        return False

def check_ollama():
    """Check Ollama installation."""
    logger.info("Checking Ollama...")
    try:
        result = subprocess.run(
            ["ollama", "version"], 
            capture_output=True, 
            text=True, 
            timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            logger.success(f"✅ Ollama {version}")
            return True
        else:
            logger.error("❌ Ollama not responding")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.error("❌ Ollama not installed")
        return False

def check_database():
    """Check PostgreSQL availability."""
    logger.info("Checking PostgreSQL...")
    try:
        import psycopg
        from src.core.config import settings
        
        conn_str = settings.database_url
        with psycopg.connect(conn_str, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                version = cur.fetchone()[0]
                logger.success(f"✅ PostgreSQL: {version[:50]}...")
                
                # Check pgvector extension
                cur.execute("SELECT * FROM pg_extension WHERE extname = 'vector';")
                if cur.fetchone():
                    logger.success("✅ pgvector extension installed")
                else:
                    logger.warning("⚠️  pgvector extension not installed")
                
        return True
    except Exception as e:
        logger.error(f"❌ PostgreSQL: {e}")
        return False

def check_directories():
    """Check project structure."""
    logger.info("Checking project structure...")
    
    required_dirs = [
        "src/core",
        "src/scanner", 
        "src/extractors",
        "src/intelligence",
        "src/search",
        "src/viz",
        "src/api",
        "src/ui",
        "data",
        "docs",
        "scripts",
        "tests",
    ]
    
    missing = []
    for dir_path in required_dirs:
        if Path(dir_path).exists():
            logger.success(f"✅ {dir_path}/")
        else:
            logger.error(f"❌ {dir_path}/ - Missing")
            missing.append(dir_path)
    
    return len(missing) == 0

def main():
    """Run all verification checks."""
    logger.info("🔍 Verifying 36TB Intelligence installation...\n")
    
    checks = [
        ("Python Version", check_python_version),
        ("Required Packages", check_packages),
        ("GPU Support", check_gpu),
        ("Ollama", check_ollama),
        ("PostgreSQL", check_database),
        ("Project Structure", check_directories),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            logger.error(f"❌ {name}: Unexpected error - {e}")
            results.append((name, False))
        
        logger.info("")  # Blank line between checks
    
    # Summary
    logger.info("📊 Verification Summary:")
    logger.info("=" * 40)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{name:<20} {status}")
    
    logger.info(f"\nScore: {passed}/{total} checks passed")
    
    if passed == total:
        logger.success("🎉 Installation verification complete!")
        logger.info("Ready to start scanning your data!")
    else:
        logger.error("❌ Some checks failed - please fix before proceeding")
        sys.exit(1)

if __name__ == "__main__":
    main()