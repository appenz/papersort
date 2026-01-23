"""Storage driver abstraction for papersort.

Provides a uniform interface for file operations across different backends:
- LocalDriver: Local filesystem
- GDriveDriver: Google Drive
- DropboxDriver: Dropbox (read-only)

Usage:
    from storage import create_storage
    
    driver = create_storage("local:/path/to/folder")
    driver = create_storage("gdrive:folder_id")
    driver = create_storage("dropbox:/path")
"""

from .base import StorageDriver, StorageError, FileInfo, FolderInfo
from .local import LocalDriver
from .gdrive import GDriveDriver
from .dbx import DropboxDriver, authenticate_dropbox


def create_storage(uri: str) -> StorageDriver:
    """Create a storage driver from a URI.
    
    Args:
        uri: Storage URI in one of these formats:
            - local:/path/to/folder
            - gdrive:folder_id
            - dropbox:/path
            
    Returns:
        StorageDriver instance for the specified backend
        
    Raises:
        ValueError: If URI format is invalid
    """
    if uri.startswith("local:"):
        return LocalDriver(uri[6:])
    elif uri.startswith("gdrive:"):
        return GDriveDriver(uri[7:])
    elif uri.startswith("dropbox:"):
        return DropboxDriver(uri[8:])
    else:
        raise ValueError(
            f"Invalid storage URI: {uri}. "
            "Must start with 'local:', 'gdrive:', or 'dropbox:'"
        )


def parse_storage_uri(uri: str) -> tuple:
    """Parse a storage URI into (type, value) tuple.
    
    Args:
        uri: Storage URI (e.g., 'gdrive:abc123', 'local:/path', 'dropbox:/path')
        
    Returns:
        Tuple of (storage_type, value) where storage_type is 'gdrive', 'local', or 'dropbox'
        
    Raises:
        ValueError: If URI format is invalid
    """
    if uri.startswith("gdrive:"):
        return ("gdrive", uri[7:])
    elif uri.startswith("local:"):
        return ("local", uri[6:])
    elif uri.startswith("dropbox:"):
        return ("dropbox", uri[8:])
    else:
        raise ValueError(
            f"Invalid storage URI: {uri}. "
            "Must start with 'gdrive:', 'local:', or 'dropbox:'"
        )


__all__ = [
    'StorageDriver',
    'StorageError', 
    'FileInfo',
    'FolderInfo',
    'LocalDriver',
    'GDriveDriver',
    'DropboxDriver',
    'create_storage',
    'parse_storage_uri',
    'authenticate_dropbox',
]
