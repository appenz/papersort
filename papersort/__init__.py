"""PaperSort - Application state and configuration."""

import os
import re
from typing import Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from storage import StorageDriver
    from workflows import MetadataCache

__version__ = "0.1.0"


def _strip_rich_markup(text: str) -> str:
    """Remove Rich markup tags like [red], [/red], [bold], etc."""
    return re.sub(r'\[/?[a-zA-Z_]+\]', '', text)


class PaperSort:
    """Central configuration and state for PaperSort."""
    
    # CLI config options
    update: bool = False
    copy: bool = False
    verify: bool = False
    log: bool = False
    
    # Global resources
    docstore_driver: Optional["StorageDriver"] = None
    llm_provider_name: str = "mistral"
    db: Optional["MetadataCache"] = None
    
    # UI app reference (None = CLI mode)
    _app: Optional[Any] = None
    
    # Progress tracking
    _total_files: int = 0
    _current_file: int = 0
    
    @classmethod
    def configure(cls, args: "argparse.Namespace", 
                  docstore_driver: Optional["StorageDriver"] = None) -> None:
        """Initialize configuration from parsed CLI args."""
        cls.update = getattr(args, 'update', False)
        cls.copy = getattr(args, 'copy', False)
        cls.verify = getattr(args, 'verify', False)
        cls.log = getattr(args, 'log', False)
        cls.llm_provider_name = os.environ.get('LLM_PROVIDER', 'mistral')
        cls.docstore_driver = docstore_driver
    
    @classmethod
    def init_db(cls) -> None:
        """Initialize the metadata cache database."""
        from workflows import MetadataCache
        cls.db = MetadataCache()
    
    @classmethod
    def close(cls) -> None:
        """Cleanup resources."""
        if cls.db:
            cls.db.close()
            cls.db = None
    
    @classmethod
    def set_app(cls, app: Any) -> None:
        """Set the Textual app reference for UI updates."""
        cls._app = app
    
    @classmethod
    def print_left(cls, line1: str, line2: str) -> None:
        """Add entry to filing log (left panel in TUI, stdout in CLI)."""
        if cls._app is not None:
            cls._app.call_from_thread(cls._app.add_filing, line1, line2)
        else:
            # Strip Rich markup for CLI output
            print(_strip_rich_markup(line1))
            print(_strip_rich_markup(line2))
    
    @classmethod
    def print_right(cls, message: str) -> None:
        """Add line to debug log (right panel in TUI, stdout in CLI)."""
        if cls._app is not None:
            cls._app.call_from_thread(cls._app.add_debug, message)
        else:
            # Strip Rich markup for CLI output
            print(_strip_rich_markup(message))
    
    @classmethod
    def set_progress(cls, current: int, total: int) -> None:
        """Update progress bar and label."""
        cls._current_file = current
        cls._total_files = total
        if cls._app is not None:
            cls._app.call_from_thread(cls._app.set_progress, current, total)
    
    @classmethod
    def set_total_files(cls, total: int) -> None:
        """Set total file count for progress tracking."""
        cls._total_files = total
        cls._current_file = 0
        if cls._app is not None:
            cls._app.call_from_thread(cls._app.set_progress, 0, total)
