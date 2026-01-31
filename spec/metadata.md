# FileMetadata

Location: `workflows/file_metadata.py`

Dataclass representing document metadata throughout the filing workflow.

## Fields

```python
@dataclass
class FileMetadata:
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
```

## Key Distinctions

- `reporting_year` vs `document_date`: A 2025 tax form dated Jan 2026 → reporting_year=2025, document_date="2026-01"
- `suggested_path` vs `dst_uri`: suggested_path is folder only from LLM; dst_uri is full path including filename after filing
- `src_uri` vs `src_uri_display`: URI is machine-readable for re-fetch; display is human-readable for UI

## Methods

### merge(newer: FileMetadata) -> FileMetadata

Creates new FileMetadata combining self with newer data.

- For each field: use newer's value if not None, else keep self's
- sha256 must match (assertion)
- `copied=True` is sticky (once copied, stays copied)
- Returns NEW object, does not mutate

### display(output_fn) / display_cached(output_fn)

Output metadata to UI in consistent format. Uses `PaperSort.print_right` in practice.

### to_cache_dict() / from_cache_row(row)

Convert to/from database row format.

### Derived value methods

- `get_filename()` → extracts filename from src_uri
- `get_src_path()` → extracts path portion from src_uri  
- `get_dst_folder()` → extracts folder from dst_uri

## URI Format

```
{storage_type}:{storage_id}:{path}

gdrive:1aBcDeF:Taxes/2024/return.pdf
local:/Users/me/inbox:subfolder/doc.pdf
dropbox:/Inbox:subfolder/doc.pdf
```
