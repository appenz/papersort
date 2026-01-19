import os
from pathlib import Path
from typing import Dict, Optional, List, Union
from datetime import date
from .docllm import sort as docllm_sort

class DocSorter:
    _layout_tree: Optional[Dict[str, Union[Dict[str, Dict], Dict[str, str]]]] = None
    _layout_path: str = os.path.join('docstore', 'layout.txt')
    
    prompt = "Please echo back the following text: ERROR, the prompt was not set correctly."

    static_prompt = """"
You are a helpful assistant analyzing a document. Your output should have exactly the following format:

---
TITLE: <a short title>
SUGGESTED_PATH: <where the document should be filed>
CONFIDENCE: <confidence in the suggested path on a scale of 1 (lowest) to 10 (highest)>
YEAR: <the year the document is about>
DATE: <the date the document was created or sent>
ENTITY: <the entity the document is about>
SUMMARY: <a short summary of the document, not more than 100 words>
---

Some specific guidelines:
- Title is a short title of the document, not more than 10 words.
- The year is the year the document is about, which may be different from the year in the date. For a tax document, it is the tax year.
- Entity is often the name of the company or organization the document is from or to. For a bank statement, it is the bank's name.
- Summary is a short summary of the document, not more than 100 words.
- Suggested path is the most important part of the output. It is where the document should be filed.

The layout description for the document store follow after this line.
--- 
"""

    @classmethod
    def set_layout_path(cls, path: str) -> None:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Layout file not found: {path}")
        cls._layout_path = path
        cls._layout_tree = None
    
    def __init__(self, file_path: str) -> None:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Input file not found: {file_path}")
        
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in ['.pdf']:
            raise ValueError(f"Unsupported file type: {file_ext}. Must be PDF.")
        
        self.previous_path = file_path
        self.file_name = os.path.basename(file_path)
        self.file_ext = file_ext
        
        self.title: Optional[str] = None
        self.year: Optional[int] = None
        self.entity: Optional[str] = None
        self.suggested_path: Optional[str] = None
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
        """Parses layout.txt into a tree structure."""
        if not os.path.exists(cls._layout_path):
            raise FileNotFoundError(f"layout.txt not found at: {cls._layout_path}")
        
        # Store the layout
        with open(cls._layout_path, 'r', encoding='utf-8') as f:
            cls.layout = f.read()
        
        # Now read the file again for tree construction
        tree: Dict[str, Union[Dict[str, Dict], Dict[str, str]]] = {}
        current_path: List[str] = []
        last_level = -1
        
        with open(cls._layout_path, 'r', encoding='utf-8') as f:
            layout_started = False
            for line in f:
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
        """Checks if a path exists in the layout, treating it like a filesystem.
        Special handling for:
        - "By year" folders - any 4-digit year number is valid
        - "By company" folders - any name is valid"""
        if not path:
            return False
            
        parts = [p for p in path.split('/') if p]
        current = cls._get_layout()
        
        for part in parts:
            if part not in current:
                # Check if current folder has special subfolders
                if any(key.lower() == "by year" for key in current.keys()):
                    # Any year number is valid
                    if part.isdigit() and len(part) == 4:  # Basic year validation
                        current = {"_description": ""}  # Continue traversal
                        continue
                elif any(key.lower() == "by company" for key in current.keys()):
                    # Any name is valid for company folders
                    current = {"_description": ""}  # Continue traversal
                    continue
                print(f"Path component '{part}' not found in {current}")
                return False
            current = current[part]
            
        return True

    def print_layout(self, tree: Optional[Dict] = None, level: int = 0) -> None:
        """Prints the layout tree with proper indentation."""
        if tree is None:
            tree = self._layout_tree
            
        indent = "  " * level
        for folder, content in sorted(tree.items()):
            if folder == "_description":
                continue
                
            description = content.get("_description", "")
            desc_str = f" ({description})" if description else ""
            print(f"{indent}- {folder}{desc_str}")
            
            # Recurse if the dictionary has more keys than just _description
            if isinstance(content, dict) and len(content) > 1:
                self.print_layout(content, level + 1)

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

    def sort(self) -> None:
        """Analyzes document and populates metadata fields"""
        docllm_sort(self) 

    def get_static_prompt(self) -> str:
       return DocSorter.static_prompt 
    
    def get_layout(self) -> str:
        return DocSorter.layout