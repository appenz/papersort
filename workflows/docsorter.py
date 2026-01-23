"""Document analysis and sorting.

Uses LLM to analyze PDF documents and suggest filing paths based on layout.
"""

import os
from typing import Dict, Optional, List, Union, TYPE_CHECKING

from .metadata_cache import compute_sha256

if TYPE_CHECKING:
    from .metadata_cache import MetadataCache


class DocSorter:
    """Analyzes documents and suggests filing paths.
    
    Uses an LLM to extract metadata from PDFs and match them to
    paths in the layout structure.
    """
    
    _layout_tree: Optional[Dict[str, Union[Dict[str, Dict], Dict[str, str]]]] = None
    _layout_path: str = os.path.join('docstore', 'layout.txt')
    layout: str = ""  # Raw layout content for LLM

    @classmethod
    def set_layout_path(cls, path: str) -> None:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Layout file not found: {path}")
        cls._layout_path = path
        cls._layout_tree = None
    
    @classmethod
    def set_layout_content(cls, content: str) -> None:
        """Set layout directly from content string (e.g., from Google Drive)."""
        cls.layout = content
        cls._layout_tree = cls._parse_layout_content(content)
    
    def __init__(self, file_path: str) -> None:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Input file not found: {file_path}")
        
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in ['.pdf']:
            raise ValueError(f"Unsupported file type: {file_ext}. Must be PDF.")
        
        self.previous_path = file_path
        self.file_name = os.path.basename(file_path)
        self.file_ext = file_ext
        self.sha256 = compute_sha256(file_path)
        
        self.title: Optional[str] = None
        self.year: Optional[int] = None
        self.date: Optional[str] = None
        self.entity: Optional[str] = None
        self.suggested_path: Optional[str] = None
        self.confidence: Optional[int] = None
        self.summary: Optional[str] = None
        
        if DocSorter._layout_tree is None:
            DocSorter._layout_tree = DocSorter._read_layout()
    
    @classmethod
    def _get_layout(cls) -> Dict[str, Union[Dict[str, Dict], Dict[str, str]]]:
        if cls._layout_tree is None:
            cls._layout_tree = cls._read_layout()
        return cls._layout_tree
    
    @classmethod
    def _read_layout(cls) -> Dict[str, Union[Dict[str, Dict], Dict[str, str]]]:
        """Parses layout.txt from file into a tree structure."""
        if not os.path.exists(cls._layout_path):
            raise FileNotFoundError(f"layout.txt not found at: {cls._layout_path}")
        
        # Store the layout
        with open(cls._layout_path, 'r', encoding='utf-8') as f:
            cls.layout = f.read()
        
        return cls._parse_layout_content(cls.layout)
    
    @classmethod
    def _parse_layout_content(cls, content: str) -> Dict[str, Union[Dict[str, Dict], Dict[str, str]]]:
        """Parses layout content string into a tree structure."""
        tree: Dict[str, Union[Dict[str, Dict], Dict[str, str]]] = {}
        current_path: List[str] = []
        last_level = -1
        
        layout_started = False
        for line in content.splitlines():
            # Calculate depth BEFORE any stripping
            depth = len(line) - len(line.lstrip())
            level = depth // 2  # Assuming 2 spaces = 1 level
            
            line = line.strip()
            
            # More robust marker detection
            if 'LAYOUT STARTS HERE' in line:
                layout_started = True
                continue
            if not layout_started:
                continue
            
            # Skip empty lines
            if not line:
                continue
            
            line = line.lstrip('-').strip()
            
            parts = line.split(':', 1)
            if len(parts) == 1:
                parts.append(parts[0])
            if len(parts) > 2:
                print(f"Malformed line in layout.txt: '{line}'")
                continue
            
            folder_name = parts[0].strip()
            description = parts[1].strip()
            
            if len(folder_name) > 30:
                raise ValueError(f"Folder name too long (max 30 chars): {folder_name}")
            if not folder_name or folder_name.startswith('.') or folder_name.startswith('-'):
                raise ValueError(f"Invalid folder name (cannot be empty or start with . or -): {folder_name}")
            if not all(c.isprintable() and c not in '/\\' for c in folder_name):
                raise ValueError(f"Invalid characters in folder name (cannot contain / or \\): {folder_name}")
            
            # Update path based on level difference
            if level > last_level:
                # Going deeper - append to current path
                current_path.append(folder_name)
            elif level == last_level:
                # Same level - replace last component
                current_path[-1] = folder_name
            else:
                # Going up - remove levels and add new folder
                current_path = current_path[:level]
                current_path.append(folder_name)
            
            last_level = level
            
            # Create nested structure
            current_dict = tree
            for path_part in current_path[:-1]:
                if path_part not in current_dict:
                    current_dict[path_part] = {}
                current_dict = current_dict[path_part]
            
            # Add the current folder with its description
            current_dict[current_path[-1]] = {"_description": description}
        
        if not layout_started:
            raise ValueError("Layout marker '---LAYOUT STARTS HERE---' not found in layout.txt")
            
        if not tree:
            raise ValueError("No valid layout entries found after the layout marker")

        return tree

    @classmethod
    def path_exists(cls, path: str) -> bool:
        """Checks if a path is a valid leaf directory in the layout.
        
        A valid path must:
        1. Exist in the layout tree
        2. Be a leaf directory (no child folders, only _description)
        
        Special handling for:
        - "By year" folders - any 4-digit year number is valid as a leaf
        - "By company" folders - any name is valid as a leaf
        """
        if not path:
            return False
            
        parts = [p for p in path.split('/') if p]
        current = cls._get_layout()
        used_dynamic_folder = False
        
        for part in parts:
            if part not in current:
                # Check if current folder has special subfolders
                if any(key.lower() == "by year" for key in current.keys()):
                    # Any year number is valid
                    if part.isdigit() and len(part) == 4:  # Basic year validation
                        used_dynamic_folder = True
                        current = {"_description": ""}  # Continue traversal
                        continue
                elif any(key.lower() == "by company" for key in current.keys()):
                    # Any name is valid for company folders
                    used_dynamic_folder = True
                    current = {"_description": ""}  # Continue traversal
                    continue
                print(f"Path component '{part}' not found in layout")
                return False
            current = current[part]
        
        # If we used a dynamic folder (By year/By company), it's always a leaf
        if used_dynamic_folder:
            return True
        
        # Check that this is a leaf directory (only has _description, no child folders)
        child_folders = [k for k in current.keys() if k != "_description"]
        if child_folders:
            print(f"Path '{path}' is not a leaf directory, has children: {child_folders}")
            return False
        
        # Reject paths that end with placeholder names - these must be replaced with actual values
        last_part = parts[-1].lower() if parts else ""
        if last_part in ("by company", "by year"):
            print(f"Path '{path}' ends with placeholder '{parts[-1]}' - must be replaced with actual value")
            return False
            
        return True

    @classmethod
    def get_by_company_paths(cls) -> List[str]:
        """Find all paths in the layout that have 'By company' subfolders.
        
        Traverses the layout tree and returns the parent path for each location
        where a 'By company' folder marker exists. These are the paths where
        company subfolders are created dynamically.
        
        Returns:
            List of paths (e.g., ["Financial & Banking/Insurance"]) where
            'By company' subfolders exist.
        """
        paths: List[str] = []
        
        def _traverse(node: Dict, current_path: str) -> None:
            for key, value in node.items():
                if key == "_description":
                    continue
                if key.lower() == "by company":
                    # Found a 'By company' marker - record the parent path
                    paths.append(current_path)
                elif isinstance(value, dict):
                    # Recurse deeper into the tree
                    new_path = f"{current_path}/{key}" if current_path else key
                    _traverse(value, new_path)
        
        _traverse(cls._get_layout(), "")
        return paths

    @classmethod
    def print_layout(cls, tree: Optional[Dict] = None, level: int = 0) -> None:
        """Prints the layout tree with proper indentation."""
        if tree is None:
            tree = cls._get_layout()
            
        indent = "  " * level
        for folder, content in sorted(tree.items()):
            if folder == "_description":
                continue
                
            description = content.get("_description", "")
            desc_str = f" ({description})" if description else ""
            print(f"{indent}- {folder}{desc_str}")
            
            # Recurse if the dictionary has more keys than just _description
            if isinstance(content, dict) and len(content) > 1:
                cls.print_layout(content, level + 1)

    def __str__(self) -> str:
        """Returns a string representation of the DocSorter object."""
        parts = []
        parts.append(f"File: {self.file_name}")
        
        if self.title:
            parts.append(f"Title: {self.title} {self.year}")
        if self.entity:
            parts.append(f"Entity: {self.entity}")
        if self.suggested_path:
            parts.append(f"Path [{self.confidence:2}]: {self.suggested_path}")
        if self.summary:
            # Show first 100 characters of summary with ellipsis if longer
            preview = self.summary[:100] + ('...' if len(self.summary) > 100 else '')
            parts.append(f"Summary: {preview}")
            
        return "\n".join(parts)

    def sort(self, llm_provider: str = "mistral") -> bool:
        """Analyzes document and populates metadata fields.
        
        Args:
            llm_provider: The LLM provider to use ("mistral" or "openai").
            
        Returns:
            True if successful, False if failed to get valid path.
        """
        from models import create_llm
        
        llm = create_llm(llm_provider)
        result = llm.analyze_document(
            pdf_path=self.previous_path,
            layout=DocSorter.layout,
            hint=self.previous_path,
            path_validator=DocSorter.path_exists
        )
        
        if result is None:
            return False
        
        # Populate metadata from analysis result
        self.title = result.title
        self.suggested_path = result.suggested_path
        self.confidence = result.confidence
        self.year = result.year
        self.date = result.date
        self.entity = result.entity
        self.summary = result.summary
        
        return True
    
    def save_to_db(self, db: "MetadataCache", path: Optional[str] = None, 
                   source: Optional[str] = None) -> None:
        """Save document metadata to the database."""
        metadata = {
            'title': self.title,
            'suggested_path': self.suggested_path,
            'confidence': self.confidence,
            'year': self.year,
            'date': self.date,
            'entity': self.entity,
            'summary': self.summary
        }
        db.insert(self.sha256, path, metadata, source=source)
