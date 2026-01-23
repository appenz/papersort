"""PaperSort - Application state and configuration."""

import os
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from storage import StorageDriver
    from workflows import MetadataCache


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
