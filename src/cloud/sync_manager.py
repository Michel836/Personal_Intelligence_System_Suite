"""Cloud synchronization system for 36TB Intelligence."""

import os
import json
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import zipfile
import tempfile
import threading
import time

from loguru import logger

try:
    import dropbox
    DROPBOX_AVAILABLE = True
except ImportError:
    DROPBOX_AVAILABLE = False
    logger.warning("dropbox not available - cloud sync disabled")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class CloudSyncManager:
    """Manage cloud synchronization for database and settings."""
    
    def __init__(self, db_path: str = "data/indexes/files.db", config_path: str = "data/cloud_config.json"):
        self.db_path = db_path
        self.config_path = config_path
        self.config = self._load_config()
        self.sync_running = False
        self.last_sync = None
        self._init_sync_tables()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load cloud sync configuration."""
        default_config = {
            "enabled": False,
            "provider": "dropbox",  # dropbox, onedrive, gdrive
            "access_token": "",
            "sync_interval_hours": 6,
            "backup_count": 5,
            "auto_sync": False,
            "sync_summaries": True,
            "sync_tags": True,
            "sync_favorites": True,
            "sync_settings": True,
            "last_sync": None,
            "device_id": self._generate_device_id(),
            "device_name": os.environ.get('COMPUTERNAME', 'Unknown-Device')
        }
        
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    saved_config = json.load(f)
                    default_config.update(saved_config)
            else:
                # Create config directory
                os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        except Exception as e:
            logger.error(f"Error loading cloud config: {e}")
        
        return default_config
    
    def _save_config(self):
        """Save cloud sync configuration."""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving cloud config: {e}")
    
    def _generate_device_id(self) -> str:
        """Generate unique device ID."""
        try:
            import uuid
            mac = uuid.getnode()
            hostname = os.environ.get('COMPUTERNAME', 'unknown')
            device_info = f"{mac}-{hostname}"
            return hashlib.md5(device_info.encode()).hexdigest()[:12]
        except:
            return hashlib.md5(str(time.time()).encode()).hexdigest()[:12]
    
    def _init_sync_tables(self):
        """Initialize sync tracking tables."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Sync history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sync_type TEXT NOT NULL, -- 'backup', 'restore', 'full_sync'
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL, -- 'success', 'failed', 'partial'
                    files_synced INTEGER DEFAULT 0,
                    data_size INTEGER DEFAULT 0,
                    duration_seconds REAL DEFAULT 0,
                    error_message TEXT DEFAULT '',
                    device_id TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Sync conflicts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_conflicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    table_name TEXT NOT NULL,
                    record_id INTEGER NOT NULL,
                    conflict_type TEXT NOT NULL, -- 'update', 'delete', 'insert'
                    local_data TEXT, -- JSON
                    remote_data TEXT, -- JSON
                    resolved BOOLEAN DEFAULT FALSE,
                    resolution TEXT DEFAULT '', -- 'local', 'remote', 'merge'
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error initializing sync tables: {e}")
    
    # Configuration Management
    def configure_dropbox(self, access_token: str) -> bool:
        """Configure Dropbox synchronization."""
        if not DROPBOX_AVAILABLE:
            return False
        
        try:
            # Test connection
            dbx = dropbox.Dropbox(access_token)
            account_info = dbx.users_get_current_account()
            
            self.config.update({
                "enabled": True,
                "provider": "dropbox",
                "access_token": access_token,
                "account_name": account_info.name.display_name,
                "account_email": account_info.email
            })
            
            self._save_config()
            logger.info(f"Dropbox configured for account: {account_info.email}")
            return True
            
        except Exception as e:
            logger.error(f"Error configuring Dropbox: {e}")
            return False
    
    def is_configured(self) -> bool:
        """Check if cloud sync is properly configured."""
        return (
            self.config.get("enabled", False) and
            self.config.get("access_token", "") != "" and
            self.config.get("provider", "") in ["dropbox"]
        )
    
    def get_status(self) -> Dict[str, Any]:
        """Get current sync status."""
        return {
            "configured": self.is_configured(),
            "enabled": self.config.get("enabled", False),
            "provider": self.config.get("provider", ""),
            "device_name": self.config.get("device_name", ""),
            "device_id": self.config.get("device_id", ""),
            "last_sync": self.config.get("last_sync"),
            "auto_sync": self.config.get("auto_sync", False),
            "sync_running": self.sync_running,
            "account_name": self.config.get("account_name", ""),
            "account_email": self.config.get("account_email", "")
        }
    
    # Data Export/Import
    def export_data(self, include_content: bool = False) -> Optional[str]:
        """Export database to JSON format."""
        try:
            export_data = {
                "export_info": {
                    "version": "1.0",
                    "exported_at": datetime.now().isoformat(),
                    "device_id": self.config.get("device_id"),
                    "device_name": self.config.get("device_name"),
                    "include_content": include_content
                },
                "tables": {}
            }
            
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Export files metadata (excluding content if not requested)
            if include_content:
                cursor.execute("SELECT * FROM files")
            else:
                cursor.execute("""
                    SELECT id, path, filename, file_type, size_bytes, 
                           modified_at, indexed_at, content_extracted
                    FROM files
                """)
            
            export_data["tables"]["files"] = [dict(row) for row in cursor.fetchall()]
            
            # Export summaries if enabled
            if self.config.get("sync_summaries", True):
                cursor.execute("SELECT * FROM summaries")
                export_data["tables"]["summaries"] = [dict(row) for row in cursor.fetchall()]
            
            # Export tags if enabled
            if self.config.get("sync_tags", True):
                cursor.execute("SELECT * FROM tags")
                export_data["tables"]["tags"] = [dict(row) for row in cursor.fetchall()]
                
                cursor.execute("SELECT * FROM file_tags")
                export_data["tables"]["file_tags"] = [dict(row) for row in cursor.fetchall()]
            
            # Export favorites if enabled
            if self.config.get("sync_favorites", True):
                cursor.execute("SELECT * FROM favorites")
                export_data["tables"]["favorites"] = [dict(row) for row in cursor.fetchall()]
            
            conn.close()
            
            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
            json.dump(export_data, temp_file, indent=2, ensure_ascii=False)
            temp_file.close()
            
            logger.info(f"Data exported to: {temp_file.name}")
            return temp_file.name
            
        except Exception as e:
            logger.error(f"Error exporting data: {e}")
            return None
    
    def create_backup_archive(self) -> Optional[str]:
        """Create compressed backup archive."""
        try:
            # Export data
            json_file = self.export_data(include_content=False)
            if not json_file:
                return None
            
            # Create archive
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            device_id = self.config.get("device_id", "unknown")
            archive_name = f"36tb_backup_{device_id}_{timestamp}.zip"
            
            temp_archive = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
            temp_archive.close()
            
            with zipfile.ZipFile(temp_archive.name, 'w', zipfile.ZIP_DEFLATED) as zf:
                # Add main data
                zf.write(json_file, "database_export.json")
                
                # Add config
                if os.path.exists(self.config_path):
                    zf.write(self.config_path, "cloud_config.json")
                
                # Add metadata
                metadata = {
                    "created_at": datetime.now().isoformat(),
                    "device_id": device_id,
                    "device_name": self.config.get("device_name", ""),
                    "backup_type": "database_metadata",
                    "version": "1.0"
                }
                
                metadata_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
                json.dump(metadata, metadata_file, indent=2)
                metadata_file.close()
                
                zf.write(metadata_file.name, "backup_metadata.json")
                
                # Cleanup
                os.unlink(metadata_file.name)
            
            # Cleanup
            os.unlink(json_file)
            
            logger.info(f"Backup archive created: {temp_archive.name}")
            return temp_archive.name
            
        except Exception as e:
            logger.error(f"Error creating backup archive: {e}")
            return None
    
    # Cloud Operations
    def sync_to_cloud(self) -> Dict[str, Any]:
        """Upload backup to cloud storage."""
        if not self.is_configured():
            return {"success": False, "error": "Cloud sync not configured"}
        
        if self.sync_running:
            return {"success": False, "error": "Sync already in progress"}
        
        self.sync_running = True
        start_time = time.time()
        
        try:
            # Create backup
            backup_file = self.create_backup_archive()
            if not backup_file:
                return {"success": False, "error": "Failed to create backup"}
            
            backup_size = os.path.getsize(backup_file)
            
            # Upload based on provider
            if self.config["provider"] == "dropbox":
                success = self._upload_to_dropbox(backup_file)
            else:
                success = False
            
            duration = time.time() - start_time
            
            if success:
                # Update config
                self.config["last_sync"] = datetime.now().isoformat()
                self._save_config()
                
                # Log sync history
                self._log_sync_history("backup", "success", 1, backup_size, duration)
                
                result = {
                    "success": True,
                    "message": "Backup uploaded successfully",
                    "size": backup_size,
                    "duration": duration
                }
            else:
                self._log_sync_history("backup", "failed", 0, backup_size, duration, "Upload failed")
                result = {"success": False, "error": "Upload to cloud failed"}
            
            # Cleanup
            os.unlink(backup_file)
            
            return result
            
        except Exception as e:
            self._log_sync_history("backup", "failed", 0, 0, time.time() - start_time, str(e))
            return {"success": False, "error": str(e)}
        
        finally:
            self.sync_running = False
    
    def _upload_to_dropbox(self, file_path: str) -> bool:
        """Upload file to Dropbox."""
        if not DROPBOX_AVAILABLE:
            return False
        
        try:
            dbx = dropbox.Dropbox(self.config["access_token"])
            
            # Create app folder structure
            app_folder = "/36TB_Intelligence_Backups"
            
            with open(file_path, 'rb') as f:
                file_size = os.path.getsize(file_path)
                filename = os.path.basename(file_path)
                
                if file_size <= 150 * 1024 * 1024:  # 150MB limit for single upload
                    dbx.files_upload(
                        f.read(),
                        f"{app_folder}/{filename}",
                        mode=dropbox.files.WriteMode.overwrite,
                        autorename=True
                    )
                else:
                    # Use upload session for large files
                    session_start_result = dbx.files_upload_session_start(f.read(8 * 1024 * 1024))
                    cursor = dropbox.files.UploadSessionCursor(
                        session_id=session_start_result.session_id,
                        offset=f.tell()
                    )
                    
                    while f.tell() < file_size:
                        if (file_size - f.tell()) <= 8 * 1024 * 1024:
                            # Final chunk
                            dbx.files_upload_session_finish(
                                f.read(),
                                cursor,
                                dropbox.files.CommitInfo(path=f"{app_folder}/{filename}")
                            )
                        else:
                            dbx.files_upload_session_append_v2(f.read(8 * 1024 * 1024), cursor)
                            cursor.offset = f.tell()
            
            # Cleanup old backups
            self._cleanup_old_backups_dropbox(dbx, app_folder)
            
            logger.info(f"Successfully uploaded to Dropbox: {filename}")
            return True
            
        except Exception as e:
            logger.error(f"Error uploading to Dropbox: {e}")
            return False
    
    def _cleanup_old_backups_dropbox(self, dbx, app_folder: str):
        """Remove old backup files from Dropbox."""
        try:
            backup_count = self.config.get("backup_count", 5)
            
            # List files
            result = dbx.files_list_folder(app_folder)
            files = []
            
            for entry in result.entries:
                if isinstance(entry, dropbox.files.FileMetadata) and entry.name.startswith("36tb_backup_"):
                    files.append((entry.name, entry.client_modified))
            
            # Sort by modification time (newest first)
            files.sort(key=lambda x: x[1], reverse=True)
            
            # Delete old files
            if len(files) > backup_count:
                for filename, _ in files[backup_count:]:
                    dbx.files_delete_v2(f"{app_folder}/{filename}")
                    logger.info(f"Deleted old backup: {filename}")
                    
        except Exception as e:
            logger.error(f"Error cleaning up old backups: {e}")
    
    def list_cloud_backups(self) -> List[Dict[str, Any]]:
        """List available backups in cloud storage."""
        if not self.is_configured() or self.config["provider"] != "dropbox":
            return []
        
        try:
            dbx = dropbox.Dropbox(self.config["access_token"])
            app_folder = "/36TB_Intelligence_Backups"
            
            result = dbx.files_list_folder(app_folder)
            backups = []
            
            for entry in result.entries:
                if isinstance(entry, dropbox.files.FileMetadata) and entry.name.startswith("36tb_backup_"):
                    # Parse filename for metadata
                    parts = entry.name.replace("36tb_backup_", "").replace(".zip", "").split("_")
                    
                    backup_info = {
                        "filename": entry.name,
                        "size": entry.size,
                        "modified": entry.client_modified.isoformat() if entry.client_modified else "",
                        "device_id": parts[0] if len(parts) > 0 else "unknown",
                        "timestamp": "_".join(parts[1:]) if len(parts) > 1 else "unknown"
                    }
                    
                    backups.append(backup_info)
            
            # Sort by modification time (newest first)
            backups.sort(key=lambda x: x["modified"], reverse=True)
            return backups
            
        except Exception as e:
            logger.error(f"Error listing cloud backups: {e}")
            return []
    
    def restore_from_cloud(self, backup_filename: str) -> Dict[str, Any]:
        """Restore from cloud backup."""
        if not self.is_configured():
            return {"success": False, "error": "Cloud sync not configured"}
        
        try:
            # Download backup
            temp_file = self._download_from_dropbox(backup_filename)
            if not temp_file:
                return {"success": False, "error": "Failed to download backup"}
            
            # Extract and restore
            result = self._restore_from_archive(temp_file)
            
            # Cleanup
            os.unlink(temp_file)
            
            return result
            
        except Exception as e:
            logger.error(f"Error restoring from cloud: {e}")
            return {"success": False, "error": str(e)}
    
    def _download_from_dropbox(self, filename: str) -> Optional[str]:
        """Download file from Dropbox."""
        if not DROPBOX_AVAILABLE:
            return None
        
        try:
            dbx = dropbox.Dropbox(self.config["access_token"])
            app_folder = "/36TB_Intelligence_Backups"
            
            temp_file = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
            
            with temp_file as f:
                metadata, response = dbx.files_download(f"{app_folder}/{filename}")
                f.write(response.content)
            
            return temp_file.name
            
        except Exception as e:
            logger.error(f"Error downloading from Dropbox: {e}")
            return None
    
    def _restore_from_archive(self, archive_path: str) -> Dict[str, Any]:
        """Restore database from backup archive."""
        try:
            with zipfile.ZipFile(archive_path, 'r') as zf:
                # Extract to temp directory
                temp_dir = tempfile.mkdtemp()
                zf.extractall(temp_dir)
                
                # Load data
                data_file = os.path.join(temp_dir, "database_export.json")
                if not os.path.exists(data_file):
                    return {"success": False, "error": "Invalid backup format"}
                
                with open(data_file, 'r', encoding='utf-8') as f:
                    import_data = json.load(f)
                
                # Restore to database
                result = self._import_data(import_data)
                
                # Cleanup
                import shutil
                shutil.rmtree(temp_dir)
                
                return result
                
        except Exception as e:
            logger.error(f"Error restoring from archive: {e}")
            return {"success": False, "error": str(e)}
    
    def _import_data(self, import_data: Dict[str, Any]) -> Dict[str, Any]:
        """Import data into database."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            imported_counts = {}
            
            # Import each table
            for table_name, records in import_data.get("tables", {}).items():
                if not records:
                    continue
                
                if table_name == "files":
                    # Handle files carefully - don't overwrite content
                    for record in records:
                        cursor.execute("""
                            INSERT OR IGNORE INTO files 
                            (id, path, filename, file_type, size_bytes, modified_at, indexed_at, content_extracted)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            record.get('id'), record.get('path'), record.get('filename'),
                            record.get('file_type'), record.get('size_bytes'), 
                            record.get('modified_at'), record.get('indexed_at'),
                            record.get('content_extracted', 0)
                        ))
                
                elif table_name == "summaries":
                    for record in records:
                        cursor.execute("""
                            INSERT OR REPLACE INTO summaries 
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, tuple(record.get(col, None) for col in [
                            'id', 'file_id', 'summary_text', 'key_points', 'topics',
                            'sentiment', 'summary_length', 'content_hash', 'created_at',
                            'model_used', 'confidence_score'
                        ]))
                
                elif table_name == "tags":
                    for record in records:
                        cursor.execute("""
                            INSERT OR REPLACE INTO tags VALUES (?, ?, ?, ?, ?, ?)
                        """, tuple(record.get(col, None) for col in [
                            'id', 'name', 'color', 'description', 'created_at', 'usage_count'
                        ]))
                
                elif table_name == "file_tags":
                    for record in records:
                        cursor.execute("""
                            INSERT OR IGNORE INTO file_tags VALUES (?, ?, ?)
                        """, (record.get('file_id'), record.get('tag_id'), record.get('added_at')))
                
                elif table_name == "favorites":
                    for record in records:
                        cursor.execute("""
                            INSERT OR REPLACE INTO favorites VALUES (?, ?, ?)
                        """, (record.get('file_id'), record.get('added_at'), record.get('notes')))
                
                imported_counts[table_name] = len(records)
            
            conn.commit()
            conn.close()
            
            self._log_sync_history("restore", "success", sum(imported_counts.values()), 0, 0)
            
            return {
                "success": True,
                "message": "Data restored successfully",
                "imported": imported_counts
            }
            
        except Exception as e:
            logger.error(f"Error importing data: {e}")
            self._log_sync_history("restore", "failed", 0, 0, 0, str(e))
            return {"success": False, "error": str(e)}
    
    def _log_sync_history(self, sync_type: str, status: str, files_synced: int, 
                         data_size: int, duration: float, error_message: str = ""):
        """Log sync operation to history."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO sync_history 
                (sync_type, provider, status, files_synced, data_size, 
                 duration_seconds, error_message, device_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sync_type, self.config.get("provider", ""), status, files_synced,
                data_size, duration, error_message, self.config.get("device_id", "")
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error logging sync history: {e}")
    
    def get_sync_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get sync operation history."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM sync_history
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            
            history = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return history
            
        except Exception as e:
            logger.error(f"Error getting sync history: {e}")
            return []
    
    def update_settings(self, settings: Dict[str, Any]) -> bool:
        """Update sync settings."""
        try:
            allowed_settings = [
                "auto_sync", "sync_interval_hours", "backup_count",
                "sync_summaries", "sync_tags", "sync_favorites", "sync_settings"
            ]
            
            for key, value in settings.items():
                if key in allowed_settings:
                    self.config[key] = value
            
            self._save_config()
            return True
            
        except Exception as e:
            logger.error(f"Error updating settings: {e}")
            return False
    
    def get_sync_stats(self) -> Dict[str, Any]:
        """Get sync statistics."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            stats = {}
            
            # Total syncs
            cursor.execute("SELECT COUNT(*) FROM sync_history")
            stats['total_syncs'] = cursor.fetchone()[0]
            
            # Successful syncs
            cursor.execute("SELECT COUNT(*) FROM sync_history WHERE status = 'success'")
            stats['successful_syncs'] = cursor.fetchone()[0]
            
            # Last sync info
            cursor.execute("""
                SELECT sync_type, status, created_at 
                FROM sync_history 
                ORDER BY created_at DESC 
                LIMIT 1
            """)
            last_sync = cursor.fetchone()
            if last_sync:
                stats['last_sync'] = {
                    'type': last_sync[0],
                    'status': last_sync[1],
                    'date': last_sync[2]
                }
            
            # Data synced
            cursor.execute("SELECT SUM(files_synced), SUM(data_size) FROM sync_history WHERE status = 'success'")
            totals = cursor.fetchone()
            stats['total_files_synced'] = totals[0] or 0
            stats['total_data_synced'] = totals[1] or 0
            
            conn.close()
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting sync stats: {e}")
            return {}