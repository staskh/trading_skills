# ABOUTME: Trading analysis library for market data, options, and portfolio management.
# ABOUTME: Provides unified API for Yahoo Finance and Interactive Brokers data.

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("trading-skills")
except PackageNotFoundError:
    __version__ = "unknown"
