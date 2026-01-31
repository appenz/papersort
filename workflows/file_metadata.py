"""FileMetadata dataclass for document metadata throughout the filing workflow."""

import dataclasses
from dataclasses import dataclass
from typing import Optional, Callable


@dataclass
class FileMetadata:
    """Metadata for a document in the filing workflow."""
    
    # Identity
    sha256: str                              # Primary key (content hash)
    
    # Source file info
    original_filename: Optional[str] = None  # "document.pdf" (no path)
    file_size: Optional[int] = None          # Bytes (for LLM limit check)
    src_uri: Optional[str] = None            # "gdrive:folder_id:path/file.pdf"
    src_uri_display: Optional[str] = None    # "My Inbox/path/file.pdf"
    
    # LLM analysis results
    title: Optional[str] = None              # Short title for filename
    entity: Optional[str] = None             # Company/organization
    summary: Optional[str] = None            # Brief description
    confidence: Optional[int] = None         # 1-10 scale
    reporting_year: Optional[int] = None     # Year doc is ABOUT (not created)
    document_date: Optional[str] = None      # "YYYY-MM" date ON the document
    suggested_path: Optional[str] = None     # LLM-suggested folder (no filename)
    
    # Destination (after filing)
    dst_uri: Optional[str] = None            # "gdrive:store_id:Financial/file.pdf"
    dst_uri_display: Optional[str] = None    # "Archive/Financial/file.pdf"
    copied: bool = False                     # True after successful copy
    
    def merge(self, newer: "FileMetadata") -> "FileMetadata":
        """Create new FileMetadata by merging self with newer data.
        
        For each field: use newer's value if not None, else keep self's.
        copied=True is sticky (once copied, stays copied).
        """
        assert self.sha256 == newer.sha256, "Cannot merge different files"
        
        def pick(old, new):
            return new if new is not None else old
        
        return FileMetadata(
            sha256=self.sha256,
            original_filename=pick(self.original_filename, newer.original_filename),
            file_size=pick(self.file_size, newer.file_size),
            src_uri=pick(self.src_uri, newer.src_uri),
            src_uri_display=pick(self.src_uri_display, newer.src_uri_display),
            title=pick(self.title, newer.title),
            entity=pick(self.entity, newer.entity),
            summary=pick(self.summary, newer.summary),
            confidence=pick(self.confidence, newer.confidence),
            reporting_year=pick(self.reporting_year, newer.reporting_year),
            document_date=pick(self.document_date, newer.document_date),
            suggested_path=pick(self.suggested_path, newer.suggested_path),
            dst_uri=pick(self.dst_uri, newer.dst_uri),
            dst_uri_display=pick(self.dst_uri_display, newer.dst_uri_display),
            copied=self.copied or newer.copied,
        )
    
    def display(self, output_fn: Callable[[str], None] = print) -> None:
        """Display metadata in UI format."""
        output_fn(f"File: {self.original_filename or 'unknown'}")
        
        if self.title:
            year_str = f" {self.reporting_year}" if self.reporting_year else ""
            output_fn(f"Title: {self.title}{year_str}")
        
        if self.entity:
            output_fn(f"Entity: {self.entity}")
        
        if self.suggested_path:
            conf_pct = (self.confidence or 0) * 10
            output_fn(f"Path ({conf_pct}%): {self.suggested_path}")
        
        if self.summary:
            preview = self.summary[:100] + ("..." if len(self.summary) > 100 else "")
            output_fn(f"Summary: {preview}")
    
    def display_cached(self, output_fn: Callable[[str], None] = print) -> None:
        """Display as cached entry (yellow, shows current location)."""
        output_fn(f"[yellow]Cached: {self.original_filename}[/yellow]")
        if self.dst_uri_display:
            output_fn(f"Current location: {self.dst_uri_display}")
        self.display(output_fn)
    
    def to_cache_dict(self) -> dict:
        """Convert to dict for database storage."""
        return {
            "sha256": self.sha256,
            "original_filename": self.original_filename,
            "file_size": self.file_size,
            "src_uri": self.src_uri,
            "src_uri_display": self.src_uri_display,
            "title": self.title,
            "entity": self.entity,
            "summary": self.summary,
            "confidence": self.confidence,
            "reporting_year": self.reporting_year,
            "document_date": self.document_date,
            "suggested_path": self.suggested_path,
            "dst_uri": self.dst_uri,
            "dst_uri_display": self.dst_uri_display,
            "copied": 1 if self.copied else 0,
        }
    
    @classmethod
    def from_cache_row(cls, row: dict) -> "FileMetadata":
        """Create from database row dict."""
        return cls(
            sha256=row["sha256"],
            original_filename=row.get("original_filename"),
            file_size=row.get("file_size"),
            src_uri=row.get("src_uri"),
            src_uri_display=row.get("src_uri_display"),
            title=row.get("title"),
            entity=row.get("entity"),
            summary=row.get("summary"),
            confidence=row.get("confidence"),
            reporting_year=row.get("reporting_year"),
            document_date=row.get("document_date"),
            suggested_path=row.get("suggested_path"),
            dst_uri=row.get("dst_uri"),
            dst_uri_display=row.get("dst_uri_display"),
            copied=bool(row.get("copied")),
        )
    
    def get_filename(self) -> Optional[str]:
        """Extract filename from src_uri."""
        if self.src_uri:
            # URI format: type:id:path/to/file.pdf
            parts = self.src_uri.split(":", 2)
            if len(parts) == 3:
                path = parts[2]
                return path.split("/")[-1] if "/" in path else path
        return self.original_filename
    
    def get_src_path(self) -> Optional[str]:
        """Extract path portion from src_uri."""
        if self.src_uri:
            parts = self.src_uri.split(":", 2)
            if len(parts) == 3:
                return parts[2]
        return None
    
    def get_dst_folder(self) -> Optional[str]:
        """Extract folder from dst_uri (path without filename)."""
        if self.dst_uri:
            parts = self.dst_uri.split(":", 2)
            if len(parts) == 3:
                path = parts[2]
                if "/" in path:
                    return "/".join(path.split("/")[:-1])
        return None
