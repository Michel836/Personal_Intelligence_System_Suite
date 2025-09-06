"""Setup PostgreSQL database for 36TB Intelligence."""

import os
import sys
import psycopg2
from psycopg2 import sql
from pathlib import Path
import logging
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


def check_postgres_connection():
    """Check if PostgreSQL is accessible."""
    try:
        # Try to connect to default postgres database
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            port=os.getenv('POSTGRES_PORT', '5432'),
            user=os.getenv('POSTGRES_USER', 'postgres'),
            password=os.getenv('POSTGRES_PASSWORD', 'postgres'),
            database='postgres'
        )
        conn.close()
        logger.info("✅ PostgreSQL server is accessible")
        return True
    except Exception as e:
        logger.error(f"❌ Cannot connect to PostgreSQL: {e}")
        logger.info("Please ensure PostgreSQL is installed and running")
        logger.info("Installation guide: https://www.postgresql.org/download/")
        return False


def create_database():
    """Create the tb36_index database if it doesn't exist."""
    try:
        # Connect to postgres database to create new database
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            port=os.getenv('POSTGRES_PORT', '5432'),
            user=os.getenv('POSTGRES_USER', 'postgres'),
            password=os.getenv('POSTGRES_PASSWORD', 'postgres'),
            database='postgres'
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        db_name = os.getenv('POSTGRES_DB', 'tb36_index')
        db_user = os.getenv('POSTGRES_USER', 'tb36_user')
        db_password = os.getenv('POSTGRES_PASSWORD', 'your_secure_password')
        
        # Check if database exists
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        exists = cursor.fetchone()
        
        if not exists:
            # Create database
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
            logger.info(f"✅ Database '{db_name}' created successfully")
        else:
            logger.info(f"ℹ️ Database '{db_name}' already exists")
        
        # Create user if not exists
        cursor.execute("SELECT 1 FROM pg_user WHERE usename = %s", (db_user,))
        user_exists = cursor.fetchone()
        
        if not user_exists and db_user != 'postgres':
            cursor.execute(sql.SQL("CREATE USER {} WITH PASSWORD %s").format(
                sql.Identifier(db_user)
            ), (db_password,))
            logger.info(f"✅ User '{db_user}' created successfully")
        
        # Grant privileges
        if db_user != 'postgres':
            cursor.execute(sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
                sql.Identifier(db_name),
                sql.Identifier(db_user)
            ))
            logger.info(f"✅ Privileges granted to user '{db_user}'")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ Error creating database: {e}")
        return False


def install_extensions():
    """Install required PostgreSQL extensions."""
    try:
        # Connect to the tb36_index database
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            port=os.getenv('POSTGRES_PORT', '5432'),
            user=os.getenv('POSTGRES_USER', 'postgres'),
            password=os.getenv('POSTGRES_PASSWORD', 'postgres'),
            database=os.getenv('POSTGRES_DB', 'tb36_index')
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        extensions = [
            'vector',  # pgvector for embeddings
            'pg_trgm',  # Trigram for fuzzy text search
            'btree_gin',  # For composite indexes
            'uuid-ossp',  # UUID generation
        ]
        
        for ext in extensions:
            try:
                cursor.execute(f"CREATE EXTENSION IF NOT EXISTS \"{ext}\"")
                logger.info(f"✅ Extension '{ext}' installed")
            except Exception as e:
                if 'could not open extension control file' in str(e):
                    if ext == 'vector':
                        logger.warning(f"⚠️ pgvector extension not found. Please install it:")
                        logger.info("   Windows: Download from https://github.com/pgvector/pgvector")
                        logger.info("   Linux: sudo apt-get install postgresql-15-pgvector")
                        logger.info("   Mac: brew install pgvector")
                    else:
                        logger.warning(f"⚠️ Extension '{ext}' not available: {e}")
                else:
                    logger.error(f"❌ Error installing extension '{ext}': {e}")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ Error installing extensions: {e}")
        return False


def create_env_file():
    """Create or update .env file with database settings."""
    env_path = Path('.env')
    
    if env_path.exists():
        logger.info("ℹ️ .env file already exists, skipping creation")
        return
    
    env_content = """# Database Configuration
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=tb36_index
POSTGRES_USER=tb36_user
POSTGRES_PASSWORD=your_secure_password

# Storage paths
SCAN_PATHS=C:\\,D:\\,E:\\,F:\\,G:\\,H:\\
DATA_DIR=./data
CACHE_DIR=./data/cache

# Ollama (AI Models)
OLLAMA_BASE_URL=http://localhost:11434
EMBEDDING_MODEL=nomic-embed-text
LLM_MODEL=mixtral:8x7b

# Performance
BATCH_SIZE=100
MAX_WORKERS=8
GPU_ENABLED=true

# Redis (optional, for caching)
REDIS_HOST=localhost
REDIS_PORT=6379

# MinIO (optional, for object storage)
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=tb36-docs
"""
    
    with open(env_path, 'w') as f:
        f.write(env_content)
    
    logger.info("✅ Created .env file with default settings")
    logger.warning("⚠️ Please update the POSTGRES_PASSWORD in .env file!")


def test_connection():
    """Test the database connection with created credentials."""
    try:
        from src.core.postgres_database import PostgresDatabase
        
        db = PostgresDatabase()
        stats = db.get_statistics()
        
        logger.info("✅ Database connection successful!")
        logger.info(f"   Total documents: {stats['total_documents']}")
        logger.info(f"   Database is ready for use")
        
        db.close()
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to connect to database: {e}")
        return False


def main():
    """Main setup function."""
    logger.info("=== PostgreSQL Setup for 36TB Intelligence ===\n")
    
    # Step 1: Check PostgreSQL connection
    if not check_postgres_connection():
        logger.error("\n❌ Setup failed: PostgreSQL is not accessible")
        sys.exit(1)
    
    # Step 2: Create database
    if not create_database():
        logger.error("\n❌ Setup failed: Could not create database")
        sys.exit(1)
    
    # Step 3: Install extensions
    if not install_extensions():
        logger.warning("\n⚠️ Some extensions could not be installed")
        logger.info("The application may work with limited functionality")
    
    # Step 4: Create .env file
    create_env_file()
    
    # Step 5: Test connection
    logger.info("\n📊 Testing database connection...")
    if test_connection():
        logger.info("\n✅ PostgreSQL setup completed successfully!")
        logger.info("\nNext steps:")
        logger.info("1. Update the POSTGRES_PASSWORD in .env file")
        logger.info("2. Run migrations: alembic upgrade head")
        logger.info("3. Start the application: streamlit run src/ui/app.py")
    else:
        logger.warning("\n⚠️ Setup completed but connection test failed")
        logger.info("Please check your .env file settings")


if __name__ == "__main__":
    main()