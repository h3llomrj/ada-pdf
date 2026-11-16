"""
College Website Accessibility Crawler
A tool for crawling college websites and testing WCAG 2.1 accessibility compliance
"""

from .crawler import AsyncWebCrawler, CrawledPage
from .accessibility import WCAGChecker, AccessibilityReport, AccessibilityIssue, Severity, WCAGLevel

__version__ = "1.0.0"
__author__ = "College Accessibility Team"
