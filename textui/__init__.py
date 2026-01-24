"""TextUI - Textual-based terminal UI for PaperSort."""

import threading
from typing import Callable, Optional

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Static, RichLog, ProgressBar, Label
from textual.binding import Binding

from papersort import PaperSort, __version__


class HeaderInfo(Static):
    """Header widget showing source and destination."""
    
    def __init__(self, source: str = "", destination: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.source = source
        self.destination = destination
    
    def compose(self) -> ComposeResult:
        yield Static(f"Source: {self.source}", id="source-line")
        yield Static(f"Destination: {self.destination}", id="dest-line")
    
    def update_info(self, source: str, destination: str) -> None:
        """Update source and destination display."""
        self.source = source
        self.destination = destination
        self.query_one("#source-line", Static).update(f"Source: {source}")
        self.query_one("#dest-line", Static).update(f"Destination: {destination}")


class PaperSortApp(App):
    """Textual app for PaperSort with dual-pane log view."""
    
    CSS = """
    Screen {
        layout: grid;
        grid-size: 1;
        grid-rows: auto 1fr auto;
    }
    
    #header-info {
        height: auto;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $primary;
    }
    
    #main-content {
        height: 1fr;
    }
    
    #left-panel {
        width: 1fr;
        border-right: solid $primary;
    }
    
    #right-panel {
        width: 1fr;
    }
    
    .panel-title {
        height: 1;
        background: $primary;
        color: $text;
        text-align: center;
        text-style: bold;
    }
    
    .log-panel {
        height: 1fr;
    }
    
    #footer-bar {
        height: 3;
        padding: 0 1;
        background: $surface;
        border-top: solid $primary;
    }
    
    #progress-container {
        height: 1;
        margin-top: 1;
    }
    
    #progress-bar {
        width: 1fr;
    }
    
    #progress-label {
        width: auto;
        min-width: 15;
        text-align: right;
        margin-left: 1;
    }
    """
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
    ]
    
    def __init__(self, source: str = "", destination: str = "", 
                 process_func: Optional[Callable[[], None]] = None) -> None:
        super().__init__()
        self.source = source
        self.destination = destination
        self._process_func = process_func
    
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield HeaderInfo(self.source, self.destination, id="header-info")
        
        with Horizontal(id="main-content"):
            with Vertical(id="left-panel"):
                yield Static("RECENT FILINGS", classes="panel-title")
                yield RichLog(id="filing-log", classes="log-panel", highlight=True, markup=True)
            
            with Vertical(id="right-panel"):
                yield Static("DEBUG LOG", classes="panel-title")
                yield RichLog(id="debug-log", classes="log-panel", highlight=True, markup=True)
        
        with Horizontal(id="footer-bar"):
            with Horizontal(id="progress-container"):
                yield ProgressBar(id="progress-bar", show_eta=True)
                yield Label("0/0 files", id="progress-label")
        
        yield Footer()
    
    def on_mount(self) -> None:
        """Called when app is mounted - wire up PaperSort UI references."""
        self.title = f"PaperSort v{__version__}"
        self.theme = "textual-light"  # Use light theme
        
        # Set the app reference on PaperSort for thread-safe UI updates
        PaperSort.set_app(self)
        
        # Start processing in background thread
        if self._process_func:
            thread = threading.Thread(target=self._process_func, daemon=True)
            thread.start()
    
    def on_unmount(self) -> None:
        """Called when app is unmounted - clear PaperSort UI references."""
        PaperSort.set_app(None)
    
    def add_filing(self, line1: str, line2: str) -> None:
        """Add a filing entry to the left log."""
        log = self.query_one("#filing-log", RichLog)
        log.write(f"{line1}\n{line2}\n")
    
    def add_debug(self, message: str) -> None:
        """Add a debug message to the right log."""
        log = self.query_one("#debug-log", RichLog)
        log.write(message)
    
    def set_progress(self, current: int, total: int) -> None:
        """Update the progress bar."""
        bar = self.query_one("#progress-bar", ProgressBar)
        bar.update(total=total, progress=current)
        self.query_one("#progress-label", Label).update(f"{current}/{total} files")
    
    def update_header(self, source: str, destination: str) -> None:
        """Update the header info."""
        self.query_one("#header-info", HeaderInfo).update_info(source, destination)


def run_app(source: str = "", destination: str = "") -> None:
    """Run the PaperSort TextUI app."""
    app = PaperSortApp(source=source, destination=destination)
    app.run()
