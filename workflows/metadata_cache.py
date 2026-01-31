"""Metadata cache for document analysis results.

Stores document metadata in SQLite to avoid re-processing documents.
"""

import os
import sqlite3
import hashlib
from typing import Optional

from .file_metadata import FileMetadata

# macOS Application Support directory
DB_DIR = os.path.expanduser("~/Library/Application Support/papersort")
DB_PATH = os.path.join(DB_DIR, "metadata.db")


def compute_sha256(file_path: str) -> str:
    """Compute SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


class MetadataCache:
    """SQLite cache for document metadata.
    
    Stores analysis results keyed by file hash to avoid re-processing.
    """
    
    def __init__(self, db_path: str = DB_PATH) -> None:
        # Ensure directory exists
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
        
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()
    
    def _init_db(self) -> None:
        """Create table and indexes if they don't exist."""
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                sha256 TEXT PRIMARY KEY,
                original_filename TEXT,
                file_size INTEGER,
                src_uri TEXT,
                src_uri_display TEXT,
                title TEXT,
                entity TEXT,
                summary TEXT,
                confidence INTEGER,
                reporting_year INTEGER,
                document_date TEXT,
                suggested_path TEXT,
                dst_uri TEXT,
                dst_uri_display TEXT,
                copied INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_src_uri ON documents(src_uri)
        """)
        self.conn.commit()
    
    def save(self, metadata: FileMetadata) -> None:
        """Insert or update a document record."""
        cursor = self.conn.cursor()
        data = metadata.to_cache_dict()
        
        cursor.execute("""
            INSERT OR REPLACE INTO documents 
            (sha256, original_filename, file_size, src_uri, src_uri_display,
             title, entity, summary, confidence, reporting_year, document_date,
             suggested_path, dst_uri, dst_uri_display, copied)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["sha256"],
            data["original_filename"],
            data["file_size"],
            data["src_uri"],
            data["src_uri_display"],
            data["title"],
            data["entity"],
            data["summary"],
            data["confidence"],
            data["reporting_year"],
            data["document_date"],
            data["suggested_path"],
            data["dst_uri"],
            data["dst_uri_display"],
            data["copied"],
        ))
        self.conn.commit()
    
    def update_copied(self, sha256: str, dst_uri: str, dst_uri_display: str) -> None:
        """Mark a document as copied and store its destination."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE documents 
            SET copied = 1, dst_uri = ?, dst_uri_display = ? 
            WHERE sha256 = ?
        """, (dst_uri, dst_uri_display, sha256))
        self.conn.commit()
    
    def get_by_hash(self, sha256: str) -> Optional[FileMetadata]:
        """Look up a document by its SHA256 hash."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE sha256 = ?", (sha256,))
        row = cursor.fetchone()
        return FileMetadata.from_cache_row(dict(row)) if row else None
    
    def exists(self, sha256: str) -> bool:
        """Check if a document with given hash exists."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM documents WHERE sha256 = ?", (sha256,))
        return cursor.fetchone() is not None
    
    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()


# Backwards compatibility alias
DocIndex = MetadataCache
