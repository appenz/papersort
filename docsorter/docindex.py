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


class DocIndex:
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
                summary TEXT
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(path)
        """)
        self.conn.commit()
    
    def insert(self, sha256: str, path: Optional[str], metadata: Dict) -> None:
        """Insert or update a document record."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO documents 
            (sha256, path, title, suggested_path, confidence, year, date, entity, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sha256,
            path,
            metadata.get('title'),
            metadata.get('suggested_path'),
            metadata.get('confidence'),
            metadata.get('year'),
            metadata.get('date'),
            metadata.get('entity'),
            metadata.get('summary')
        ))
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
