"""
Logging helper module for terminal-first logging.
All output goes to stdout with formatted prefixes, and also to a log file.
"""

import sys
from datetime import datetime
from pathlib import Path

# Get project root directory
_project_root = Path(__file__).parent.parent
_log_dir = _project_root / "logs"
_log_dir.mkdir(exist_ok=True)

# Create log file with timestamp
_log_file_path = _log_dir / f"screencal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
_log_file = open(_log_file_path, 'a', encoding='utf-8')


def _log(message: str):
    """Write message to both stdout and log file."""
    print(message)
    _log_file.write(message + '\n')
    _log_file.flush()


class Log:
    """Simple logging class that outputs to stdout and log file with formatted prefixes."""
    
    @staticmethod
    def section(title: str):
        """Print a section header: blank line + '===== TITLE ====='"""
        _log("")
        _log(f"===== {title} =====")
    
    @staticmethod
    def info(message: str):
        """Print an info message: '[INFO] message'"""
        _log(f"[INFO] {message}")
    
    @staticmethod
    def warn(message: str):
        """Print a warning message: '[WARN] message'"""
        _log(f"[WARN] {message}")
    
    @staticmethod
    def error(message: str):
        """Print an error message: '[ERROR] message'"""
        _log(f"[ERROR] {message}")
    
    @staticmethod
    def kv(pairs: dict):
        """
        Print key-value pairs: '[KV] key=value | key2=value2'
        
        Args:
            pairs: Dictionary of key-value pairs to print
        """
        kv_string = " | ".join([f"{k}={v}" for k, v in pairs.items()])
        _log(f"[KV] {kv_string}")
    
    @staticmethod
    def get_log_path() -> str:
        """Get the path to the current log file."""
        return str(_log_file_path)

