"""Metadata cache for document analysis results.

Stores LLM-extracted metadata in SQLite to avoid re-processing documents.
"""

import os
import sqlite3
import hashlib
from typing import Dict, Optional

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
    Also tracks filing state (source, copied, dest_path).
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
                path TEXT,
                title TEXT,
                suggested_path TEXT,
                confidence INTEGER,
                year INTEGER,
                date TEXT,
                entity TEXT,
                summary TEXT,
                source TEXT,
                copied INTEGER DEFAULT 0,
                dest_path TEXT
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(path)
        """)
        self.conn.commit()
        
        # Migration: add new columns if they don't exist (for existing databases)
        # Must run before creating indexes on new columns
        self._migrate_add_columns()
        
        # Create index on source column (after migration ensures column exists)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source)
        """)
        self.conn.commit()
    
    def _migrate_add_columns(self) -> None:
        """Add new columns to existing databases if they don't exist."""
        cursor = self.conn.cursor()
        
        # Get existing columns
        cursor.execute("PRAGMA table_info(documents)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        
        # Add missing columns
        migrations = [
            ("source", "TEXT"),
            ("copied", "INTEGER DEFAULT 0"),
            ("dest_path", "TEXT"),
        ]
        
        for col_name, col_type in migrations:
            if col_name not in existing_columns:
                cursor.execute(f"ALTER TABLE documents ADD COLUMN {col_name} {col_type}")
        
        self.conn.commit()
    
    def insert(self, sha256: str, path: Optional[str], metadata: Dict, 
               source: Optional[str] = None, copied: bool = False, 
               dest_path: Optional[str] = None) -> None:
        """Insert or update a document record.
        
        Preserves existing copied/dest_path values unless explicitly provided.
        """
        cursor = self.conn.cursor()
        
        # Preserve existing copied/dest_path if not explicitly provided
        if not copied and dest_path is None:
            cursor.execute("SELECT copied, dest_path FROM documents WHERE sha256 = ?", (sha256,))
            row = cursor.fetchone()
            if row:
                copied = bool(row[0])
                dest_path = row[1]
        
        cursor.execute("""
            INSERT OR REPLACE INTO documents 
            (sha256, path, title, suggested_path, confidence, year, date, entity, summary,
             source, copied, dest_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sha256,
            path,
            metadata.get('title'),
            metadata.get('suggested_path'),
            metadata.get('confidence'),
            metadata.get('year'),
            metadata.get('date'),
            metadata.get('entity'),
            metadata.get('summary'),
            source,
            1 if copied else 0,
            dest_path
        ))
        self.conn.commit()
    
    def update_copied(self, sha256: str, dest_path: str) -> None:
        """Mark a document as copied and store its destination path."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE documents SET copied = 1, dest_path = ? WHERE sha256 = ?
        """, (dest_path, sha256))
        self.conn.commit()
    
    def get_by_hash(self, sha256: str) -> Optional[Dict]:
        """Look up a document by its SHA256 hash."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE sha256 = ?", (sha256,))
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_by_path(self, path: str) -> Optional[Dict]:
        """Look up a document by its path."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM documents WHERE path = ?", (path,))
        row = cursor.fetchone()
        return dict(row) if row else None
    
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
