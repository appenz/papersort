"""
Retry utilities with exponential backoff for transient network errors.

This module provides a decorator for retrying functions that may fail due to
temporary issues like network timeouts, rate limiting, or server errors.

WHY RETRY WITH BACKOFF?
-----------------------
Cloud APIs (Google Drive, Dropbox, S3, etc.) can fail temporarily due to:
  - Rate limiting (HTTP 429): You're making too many requests
  - Server errors (HTTP 500/502/503/504): The service is temporarily overloaded
  - Network issues: Connection resets, timeouts, DNS failures

These errors are "transient" - they go away if you wait and try again.
Simply retrying immediately often fails because:
  1. The server is still overloaded
  2. You hit rate limits again immediately
  3. Network issues need time to resolve

EXPONENTIAL BACKOFF:
--------------------
Instead of retrying immediately, we wait progressively longer between attempts:
  - Attempt 1 fails → wait ~1 second
  - Attempt 2 fails → wait ~2 seconds  
  - Attempt 3 fails → wait ~4 seconds
  - Attempt 4 fails → wait ~8 seconds
  - ... and so on, doubling each time (capped at a maximum)

This gives the server/network time to recover without hammering it with requests.

JITTER:
-------
If many clients all retry at exactly the same intervals, they create "thundering
herd" problems - everyone retries at the same moment, overwhelming the server again.

"Jitter" adds randomness to the delay (e.g., instead of exactly 4 seconds, we wait
somewhere between 2-6 seconds). This spreads out the retries and reduces collisions.

USAGE:
------
    from utils.retry import retry_on_transient_error
    
    # Define what errors should trigger a retry for your specific API
    def is_retryable(exc):
        if isinstance(exc, MyAPIError):
            return exc.status_code in {429, 500, 503}
        return isinstance(exc, (ConnectionError, TimeoutError))
    
    @retry_on_transient_error(is_retryable=is_retryable, max_retries=5)
    def call_my_api():
        return api.do_something()
"""

import time
import random
from functools import wraps
from typing import Callable, Optional


def retry_on_transient_error(
    is_retryable: Callable[[Exception], bool],
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    on_retry: Optional[Callable[[Exception, int, float], None]] = None,
):
    """
    Decorator that retries a function on transient errors with exponential backoff.
    
    This decorator wraps a function and automatically retries it when specific
    exceptions occur. It uses exponential backoff (doubling wait times) with
    random jitter to avoid overwhelming the server.
    
    Args:
        is_retryable: A function that takes an exception and returns True if the
                      error is transient and should be retried. This allows each
                      API client to define its own retry conditions.
                      
                      Example for Google APIs:
                          def is_retryable(exc):
                              if isinstance(exc, HttpError):
                                  return exc.resp.status in {429, 500, 502, 503}
                              return isinstance(exc, ConnectionError)
        
        max_retries: Maximum number of retry attempts after the initial try.
                     Default is 5, meaning up to 6 total attempts.
                     
        base_delay: Initial delay in seconds before the first retry.
                    This gets doubled (exponentially increased) for each
                    subsequent retry. Default is 1.0 second.
                    
        max_delay: Maximum delay cap in seconds. Even with exponential growth,
                   the delay will never exceed this value. Default is 60 seconds.
                   This prevents absurdly long waits after many retries.
                   
        on_retry: Optional callback function called before each retry. Receives:
                  - exc: The exception that triggered the retry
                  - attempt: Which attempt number failed (1-indexed)
                  - delay: How long we'll wait before retrying
                  Useful for logging or monitoring retry behavior.
    
    Returns:
        A decorator that wraps functions with retry logic.
        
    Raises:
        The last exception encountered if all retries are exhausted, or
        immediately if the exception is not retryable.
    
    Example:
        >>> @retry_on_transient_error(
        ...     is_retryable=lambda e: isinstance(e, ConnectionError),
        ...     max_retries=3
        ... )
        ... def fetch_data():
        ...     return requests.get("https://api.example.com/data")
    """
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)  # Preserves the original function's name and docstring
        def wrapper(*args, **kwargs):
            last_exception = None
            
            # We try once initially, then up to max_retries additional times
            # So total attempts = max_retries + 1
            for attempt in range(max_retries + 1):
                try:
                    # Try to execute the function
                    return func(*args, **kwargs)
                    
                except Exception as exc:
                    # Check if this is a retryable error using the provided function
                    if not is_retryable(exc):
                        # Non-retryable error (e.g., HTTP 404 Not Found, HTTP 401 Unauthorized)
                        # These won't be fixed by retrying, so fail immediately
                        raise
                    
                    # Save the exception in case we exhaust all retries
                    last_exception = exc
                    
                    # Check if we have retries remaining
                    if attempt < max_retries:
                        # Calculate delay using exponential backoff:
                        # attempt 0 → base_delay * 2^0 = base_delay * 1
                        # attempt 1 → base_delay * 2^1 = base_delay * 2
                        # attempt 2 → base_delay * 2^2 = base_delay * 4
                        # ... and so on, but capped at max_delay
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        
                        # Add jitter: multiply by random factor between 0.5 and 1.5
                        # This spreads out retries from multiple clients to avoid
                        # "thundering herd" problems where everyone retries at once
                        jitter_factor = 0.5 + random.random()  # random() returns [0.0, 1.0)
                        delay *= jitter_factor
                        
                        # Call the optional retry callback (useful for logging)
                        if on_retry:
                            on_retry(exc, attempt + 1, delay)
                        
                        # Wait before retrying
                        time.sleep(delay)
                    
                    # If attempt == max_retries, we've exhausted all retries
                    # The loop will exit and we'll raise last_exception below
            
            # All retries exhausted - raise the last exception we encountered
            raise last_exception
            
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Common retry condition helpers
# ---------------------------------------------------------------------------
# These helper functions can be used directly or combined for common use cases.

# Standard HTTP status codes that indicate transient server issues
TRANSIENT_HTTP_STATUS_CODES = {
    429,  # Too Many Requests (rate limited)
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504,  # Gateway Timeout
}

# Standard network exception types that are typically transient
TRANSIENT_NETWORK_EXCEPTIONS = (
    ConnectionError,      # Connection refused, reset, etc.
    TimeoutError,         # Operation timed out
    OSError,              # Low-level I/O errors (includes socket errors)
)


def is_transient_network_error(exc: Exception) -> bool:
    """
    Check if an exception is a transient network error.
    
    This is a helper for the common case of retrying on network issues.
    Use this in combination with API-specific checks.
    
    Args:
        exc: The exception to check
        
    Returns:
        True if this looks like a transient network error
        
    Example:
        def is_retryable(exc):
            if is_transient_network_error(exc):
                return True
            # Add API-specific checks here
            return False
    """
    return isinstance(exc, TRANSIENT_NETWORK_EXCEPTIONS)
