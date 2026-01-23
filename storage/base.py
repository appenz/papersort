"""Base classes for storage drivers.

This module defines the abstract interface that all storage backends must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


class StorageError(Exception):
    """Base exception for storage operations."""
    pass


@dataclass
class FileInfo:
    """Information about a file in storage.
    
    Attributes:
        path: Relative path within the storage root
        name: Filename only (no directory)
        size: File size in bytes (optional)
        id: Backend-specific identifier (e.g., Google Drive file ID)
    """
    path: str
    name: str
    size: Optional[int] = None
    id: Optional[str] = None


@dataclass
class FolderInfo:
    """Information about a folder in storage.
    
    Attributes:
        path: Relative path within the storage root
        name: Folder name only (no parent path)
        id: Backend-specific identifier (e.g., Google Drive folder ID)
    """
    path: str
    name: str
    id: Optional[str] = None


class StorageDriver(ABC):
    """Abstract base class for storage backends.
    
    All storage drivers (local filesystem, Google Drive, Dropbox) implement
    this interface. Read operations are required; write operations may raise
    NotImplementedError for read-only backends.
    """
    
    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name for this storage (e.g., 'My Docs (Google Drive)')."""
        pass
    
    # =========================================================================
    # Read Operations (required for all drivers)
    # =========================================================================
    
    @abstractmethod
    def list_files(self, path: str = "", recursive: bool = False,
                   extension: Optional[str] = None) -> List[FileInfo]:
        """List files at the given path.
        
        Args:
            path: Relative path within storage (empty string for root)
            recursive: If True, include files in subdirectories
            extension: Filter by file extension (e.g., ".pdf"), case-insensitive
            
        Returns:
            List of FileInfo objects
            
        Raises:
            StorageError: If path doesn't exist or can't be accessed
        """
        pass
    
    @abstractmethod
    def list_folders(self, path: str = "") -> List[FolderInfo]:
        """List immediate subfolders at the given path.
        
        Args:
            path: Relative path within storage (empty string for root)
            
        Returns:
            List of FolderInfo objects
            
        Raises:
            StorageError: If path doesn't exist or can't be accessed
        """
        pass
    
    @abstractmethod
    def file_exists(self, path: str) -> bool:
        """Check if a file exists at the given path.
        
        Args:
            path: Relative path to the file
            
        Returns:
            True if file exists, False otherwise
        """
        pass
    
    @abstractmethod
    def read_text(self, path: str) -> str:
        """Read a text file and return its contents.
        
        Args:
            path: Relative path to the text file
            
        Returns:
            File contents as a string (UTF-8 decoded)
            
        Raises:
            StorageError: If file doesn't exist or can't be read
        """
        pass
    
    @abstractmethod
    def download_to_temp(self, path: str) -> str:
        """Download a file to a local temporary location.
        
        For local storage, this may return the original path without copying.
        For remote storage, this downloads to a temp file.
        
        Args:
            path: Relative path to the file
            
        Returns:
            Local filesystem path to the file. Caller is responsible for
            cleanup (deleting temp file) for remote storage.
            
        Raises:
            StorageError: If file doesn't exist or download fails
        """
        pass
    
    # =========================================================================
    # Write Operations (optional - raise NotImplementedError if read-only)
    # =========================================================================
    
    def upload(self, local_path: str, dest_path: str) -> None:
        """Upload a local file to storage.
        
        Creates parent directories as needed.
        
        Args:
            local_path: Path to local file to upload
            dest_path: Destination path within storage
            
        Raises:
            StorageError: If upload fails
            NotImplementedError: If storage is read-only
        """
        raise NotImplementedError(f"{self.display_name} does not support write operations")
    
    def move(self, src_path: str, dest_folder: str) -> None:
        """Move a file to a different folder within storage.
        
        Args:
            src_path: Current path to the file
            dest_folder: Destination folder path (file keeps its name)
            
        Raises:
            StorageError: If move fails
            NotImplementedError: If storage is read-only
        """
        raise NotImplementedError(f"{self.display_name} does not support write operations")
    
    def delete(self, path: str) -> None:
        """Delete a file or folder.
        
        For safety, some backends may move to trash instead of permanent delete.
        
        Args:
            path: Path to file or folder to delete
            
        Raises:
            StorageError: If delete fails
            NotImplementedError: If storage is read-only
        """
        raise NotImplementedError(f"{self.display_name} does not support write operations")
    
    # =========================================================================
    # Filename Handling
    # =========================================================================
    
    @abstractmethod
    def sanitize_filename(self, name: str) -> str:
        """Sanitize a filename for this storage backend.
        
        Different backends have different restrictions on allowed characters.
        For example, local filesystems are more restrictive than Google Drive.
        
        Args:
            name: Proposed filename (without path)
            
        Returns:
            Sanitized filename safe for this storage backend
        """
        pass
