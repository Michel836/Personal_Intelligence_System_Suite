"""Disk utilities for drive detection and selection."""

import os
import shutil
from pathlib import Path
from typing import List, Dict, Any
import platform

def get_available_drives() -> List[Dict[str, Any]]:
    """Get list of available drives with details."""
    drives = []
    
    if platform.system() == "Windows":
        # Windows: Check all drive letters
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive_path = f"{letter}:\\"
            if os.path.exists(drive_path):
                try:
                    # Get drive info
                    total, used, free = shutil.disk_usage(drive_path)
                    
                    # Determine drive type
                    drive_type = _get_drive_type_windows(letter)
                    
                    drives.append({
                        'letter': letter,
                        'path': drive_path,
                        'label': _get_drive_label_windows(letter),
                        'type': drive_type,
                        'total_space': total,
                        'used_space': used,
                        'free_space': free,
                        'usage_percent': (used / total) * 100 if total > 0 else 0,
                        'display_name': f"{letter}: ({_format_size(total)}) - {_get_drive_label_windows(letter) or 'Local Disk'}"
                    })
                except:
                    # Drive not accessible
                    continue
    
    else:
        # Linux/Mac: Check mount points
        drives = _get_unix_drives()
    
    return sorted(drives, key=lambda x: x['letter'] if 'letter' in x else x['path'])

def _get_drive_type_windows(letter: str) -> str:
    """Get Windows drive type."""
    import ctypes
    from ctypes import wintypes
    
    try:
        drive_path = f"{letter}:\\"
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
        
        type_map = {
            0: "unknown",
            1: "invalid",
            2: "removable",  # Floppy, USB, etc.
            3: "fixed",      # Hard disk
            4: "remote",     # Network drive
            5: "cdrom",      # CD/DVD
            6: "ramdisk"     # RAM disk
        }
        
        return type_map.get(drive_type, "unknown")
    except:
        return "unknown"

def _get_drive_label_windows(letter: str) -> str:
    """Get Windows drive label."""
    try:
        import ctypes
        from ctypes import wintypes
        
        drive_path = f"{letter}:\\"
        volume_name_buffer = ctypes.create_unicode_buffer(1024)
        file_system_name_buffer = ctypes.create_unicode_buffer(1024)
        
        result = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive_path),
            volume_name_buffer, ctypes.sizeof(volume_name_buffer),
            None, None, None,
            file_system_name_buffer, ctypes.sizeof(file_system_name_buffer)
        )
        
        if result:
            return volume_name_buffer.value or ""
        return ""
    except:
        return ""

def _get_unix_drives() -> List[Dict[str, Any]]:
    """Get Unix/Linux/Mac mount points."""
    drives = []
    
    try:
        with open('/proc/mounts', 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    device, mount_point = parts[0], parts[1]
                    
                    # Skip system mounts
                    if mount_point.startswith(('/proc', '/sys', '/dev', '/run')):
                        continue
                    
                    # Skip temporary mounts
                    if 'tmpfs' in device or 'devpts' in device:
                        continue
                    
                    try:
                        total, used, free = shutil.disk_usage(mount_point)
                        
                        drives.append({
                            'device': device,
                            'path': mount_point,
                            'label': os.path.basename(mount_point) or device,
                            'type': 'fixed',
                            'total_space': total,
                            'used_space': used,
                            'free_space': free,
                            'usage_percent': (used / total) * 100 if total > 0 else 0,
                            'display_name': f"{mount_point} ({_format_size(total)}) - {device}"
                        })
                    except:
                        continue
    except:
        # Fallback to root
        try:
            total, used, free = shutil.disk_usage('/')
            drives.append({
                'device': '/',
                'path': '/',
                'label': 'Root',
                'type': 'fixed',
                'total_space': total,
                'used_space': used,
                'free_space': free,
                'usage_percent': (used / total) * 100 if total > 0 else 0,
                'display_name': f"/ ({_format_size(total)}) - Root"
            })
        except:
            pass
    
    return drives

def _format_size(size_bytes: int) -> str:
    """Format file size in human readable format."""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024.0 and i < len(size_names) - 1:
        size /= 1024.0
        i += 1
    
    return f"{size:.1f} {size_names[i]}"

def get_recommended_drives() -> List[str]:
    """Get recommended drives to scan (exclude system/temporary drives)."""
    drives = get_available_drives()
    recommended = []
    
    for drive in drives:
        # Skip system drives with low free space
        if drive['usage_percent'] > 95:
            continue
            
        # Skip very small drives (< 1GB)
        if drive['total_space'] < 1024 * 1024 * 1024:
            continue
            
        # Skip CD/DVD drives
        if drive.get('type') == 'cdrom':
            continue
            
        # Skip RAM disks
        if drive.get('type') == 'ramdisk':
            continue
        
        recommended.append(drive['path'])
    
    return recommended

def validate_scan_path(path: str) -> Dict[str, Any]:
    """Validate if a path is suitable for scanning."""
    result = {
        'valid': False,
        'accessible': False,
        'writable': False,
        'estimated_files': 0,
        'warnings': [],
        'errors': []
    }
    
    try:
        path_obj = Path(path)
        
        # Check if path exists
        if not path_obj.exists():
            result['errors'].append(f"Path does not exist: {path}")
            return result
        
        result['accessible'] = True
        
        # Check if readable
        if not os.access(path, os.R_OK):
            result['errors'].append(f"Path not readable: {path}")
            return result
        
        # Check if writable (for database operations)
        result['writable'] = os.access(path, os.W_OK)
        if not result['writable']:
            result['warnings'].append("Path is read-only - some features may be limited")
        
        # Estimate file count (quick sample)
        try:
            file_count = 0
            dir_count = 0
            sample_size = 0
            
            for root, dirs, files in os.walk(path):
                file_count += len(files)
                dir_count += len(dirs)
                sample_size += 1
                
                # Stop after sampling 10 directories
                if sample_size >= 10:
                    break
            
            # Estimate total files
            if sample_size > 0:
                avg_files_per_dir = file_count / sample_size
                estimated_total = int(avg_files_per_dir * dir_count * 1.5)  # Rough estimate
                result['estimated_files'] = min(estimated_total, 1000000)  # Cap at 1M
            
        except Exception as e:
            result['warnings'].append(f"Could not estimate file count: {e}")
        
        # Check for very large directories
        if result['estimated_files'] > 100000:
            result['warnings'].append(f"Large directory detected (~{result['estimated_files']:,} files) - scanning may take time")
        
        # Success
        result['valid'] = True
        
    except Exception as e:
        result['errors'].append(f"Path validation error: {e}")
    
    return result