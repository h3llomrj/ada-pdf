#!/usr/bin/env python3
"""
Async web crawler for college websites
Supports single-site and multi-site crawling with platform organization
"""

import asyncio
import aiohttp
import aiofiles
import logging
from urllib.parse import urljoin, urlparse, parse_qs, urlunparse
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from bs4 import XMLParsedAsHTMLWarning
import warnings
from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
import json
import yaml

# Import database models
try:
    from database import Page
except ImportError:
    Page = None
from pathlib import Path
from tqdm import tqdm
import time
import csv
from accessibility import WCAGChecker, AccessibilityReport

# Suppress XML parsing warning for sitemaps
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

@dataclass
class CrawledPage:
    url: str
    title: str
    status_code: int
    content_type: str
    content_length: int
    links: List[str]
    images: List[Dict[str, str]]
    forms: List[Dict[str, Any]]
    headings: Dict[str, List[str]]
    html_content: str
    timestamp: str
    issues: List[Dict[str, Any]] = None
    accessibility_score: int = 100
    crawl_timestamp: str = None
    platform: str = ""
    site_name: Optional[str] = None
    source_page: Optional[str] = None  # Page where this PDF was discovered
    pdf_analysis: Optional[Dict[str, Any]] = None  # PDF analysis results
    is_archived: bool = False  # Whether the page/PDF has an archive notice

class AsyncWebCrawler:
    def __init__(self, config_path: str = "config/sites.yaml", run_accessibility: bool = False, write_files: bool = False):
        self.config = self._load_config(config_path)
        self.session: Optional[aiohttp.ClientSession] = None
        self.visited_urls: Set[str] = set()
        self.crawled_pages: List[CrawledPage] = []
        self.robots_cache: Dict[str, RobotFileParser] = {}
        self.rate_limiter: Dict[str, float] = {}
        self.max_depth = 3
        self.max_pages = 1000
        self.delay = 1.0
        self.max_concurrent = 10
        self.timeout = 30
        self.user_agent = "M-G CAFE Accessibility Checker 1.0"
        self.respect_robots = True
        self.allowed_domains = set()
        self.run_accessibility = run_accessibility
        self.accessibility_checker = None
        self.accessibility_reports: List[AccessibilityReport] = []
        
        self.write_files = write_files
        self.incremental_save_enabled = write_files
        self.current_crawl_file: Optional[Path] = None
        self.current_latest_file: Optional[Path] = None
        
        # Database integration
        self.db_enabled = True
        self.db_session = None

        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Initialize accessibility checker if enabled
        if self.run_accessibility:
            try:
                # Get disabled rules from config (will be applied per platform during crawling)
                self.accessibility_checker = WCAGChecker()
                self.logger.info("Accessibility checker initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize accessibility checker: {e}")
                self.accessibility_checker = None
                self.run_accessibility = False
        else:
            self.accessibility_checker = None

    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file"""
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            self.logger.warning(f"Config file {config_path} not found, using defaults")
            return self._get_default_config()

    def _get_default_config(self) -> Dict:
        """Default configuration if no config file found"""
        return {
            'crawler_settings': {
                'max_depth': 3,
                'delay_between_requests': 1.0,
                'max_concurrent_requests': 10,
                'timeout': 30,
                'user_agent': 'College Accessibility Checker 1.0',
                'respect_robots_txt': True,
                'allowed_domains': []
            },
            'output': {
                'format': 'json',
                'include_html': False,
                'include_headers': True,
                'include_links': True
            }
        }

    def _check_for_archive_message(self, html_content: str) -> bool:
        """
        Check if the page contains an archive notice message.
        Returns True if archive message is detected.
        """
        if not html_content:
            return False
        
        # Convert to lowercase for case-insensitive matching
        content_lower = html_content.lower()
        
        # Common patterns in archive messages
        archive_indicators = [
            "archived and were created before",
            "document was archived before",
            "materials are archived",
            "provided for reference, research, or recordkeeping purposes",
            "may not meet current accessibility standards",
            "may not reflect current practices, policies, or accessibility requirements"
        ]
        
        # Check if at least 2 indicators are present (to reduce false positives)
        matches = sum(1 for indicator in archive_indicators if indicator in content_lower)
        
        return matches >= 2

    def _normalize_url(self, url: str) -> str:
        """Normalize URLs so equivalent variants (e.g. trailing slash) map to a single canonical form.

        Rules:
        - Lowercase scheme and hostname
        - Ensure root path is '/'
        - Strip trailing slash from non-root paths
        - Drop fragment, preserve query string
        - Upgrade http -> https
        - Normalize ca.uky.edu -> mgcafe.uky.edu for all URLs
        - Remove /sites/sitename.ca.uky.edu/ path prefix if present
        """
        try:
            parsed = urlparse(url)
            if not parsed.scheme and not parsed.netloc:
                return url

            # Always upgrade http -> https
            scheme = "https"
            netloc = parsed.netloc.lower()
            path = parsed.path or "/"

            # Normalize domain: ca.uky.edu -> mgcafe.uky.edu for all URLs
            if '.ca.uky.edu' in netloc:
                netloc = netloc.replace('.ca.uky.edu', '.mgcafe.uky.edu')

            # Remove /sites/sitename.ca.uky.edu/ or /sites/sitename.mgcafe.uky.edu/ from path
            # Pattern: /sites/sitename.domain.uky.edu/files/... -> /files/...
            import re
            path = re.sub(r'/sites/[^/]+\.(ca|mgcafe)\.uky\.edu/', '/', path)

            # Normalize path
            if path != "/" and path.endswith("/"):
                path = path.rstrip("/")

            # Preserve query string, drop params and fragment
            query = parsed.query
            return urlunparse((scheme, netloc, path, "", query, ""))
        except Exception:
            # On any parsing error, fall back to original URL
            return url

    async def _create_session(self):
        """Create aiohttp session with proper headers"""
        import ssl
        headers = {
            'User-Agent': self.config['crawler_settings']['user_agent']
        }
        timeout = aiohttp.ClientTimeout(
            total=self.config['crawler_settings']['timeout']
        )
        # Disable SSL verification to handle sites with certificate issues
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(
            limit=self.config['crawler_settings']['max_concurrent_requests'],
            ssl=ssl_context
        )
        self.session = aiohttp.ClientSession(
            headers=headers,
            timeout=timeout,
            connector=connector
        )

    async def _can_crawl(self, url: str, base_domain: str = None) -> bool:
        """Check if URL can be crawled based on robots.txt and domain restrictions"""
        parsed = urlparse(url)
        domain = parsed.netloc
        
        # If base_domain is provided, ensure URL is within the same root domain
        if base_domain:
            base_domain_parts = base_domain.split('.')
            domain_parts = domain.split('.')
            
            # Check if domains share the same root domain (last 2 parts: uky.edu)
            # This allows events.mgcafe.uky.edu to crawl events.ca.uky.edu URLs
            if not (len(base_domain_parts) >= 2 and len(domain_parts) >= 2 and
                   base_domain_parts[-2:] == domain_parts[-2:]):
                # Also allow exact matches and mgcafe ↔ ca domain mapping
                if not (domain == base_domain or
                        # Handle mgcafe ↔ ca domain mapping for crawling
                        (base_domain.replace('mgcafe.', 'ca.') == domain) or
                        (domain.replace('ca.', 'mgcafe.') == base_domain)):
                    return False
        
        # Check allowed domains from config
        allowed_domains = self.config['crawler_settings'].get('allowed_domains', [])
        if allowed_domains and not any(allowed in domain for allowed in allowed_domains):
            self.logger.warning(f"Domain '{domain}' is not in allowed_domains list. Add it to config/sites.yaml to crawl this site.")
            return False
        
        # Check robots.txt
        if self.config['crawler_settings']['respect_robots_txt']:
            if domain not in self.robots_cache:
                await self._load_robots_txt(domain)
            
            robots_parser = self.robots_cache.get(domain)
            if robots_parser is not None and not robots_parser.can_fetch(
                self.config['crawler_settings']['user_agent'], url
            ):
                return False
        
        return True

    async def _load_robots_txt(self, domain: str):
        """Load and parse robots.txt for a domain"""
        robots_urls = [
            f"https://{domain}/robots.txt",
            f"http://{domain}/robots.txt"
        ]
        for robots_url in robots_urls:
            try:
                async with self.session.get(robots_url) as response:
                    if response.status == 200:
                        content = await response.text()
                        rp = RobotFileParser()
                        rp.set_url(robots_url)
                        rp.parse(content.splitlines())
                        self.robots_cache[domain] = rp
                        return
            except Exception as e:
                self.logger.warning(f"Failed to load robots.txt from {robots_url}: {e}")
        self.robots_cache[domain] = None

    async def _rate_limit(self, domain: str):
        """Simple rate limiting per domain"""
        if domain not in self.rate_limiter:
            self.rate_limiter[domain] = 0
        
        current_time = time.time()
        last_request = self.rate_limiter[domain]
        delay = self.config['crawler_settings']['delay_between_requests']
        
        if current_time - last_request < delay:
            await asyncio.sleep(delay - (current_time - last_request))
        
        self.rate_limiter[domain] = time.time()

    def _get_disabled_rules_for_platform(self, platform_name: str) -> List[str]:
        """Get disabled accessibility rules for a specific platform"""
        platforms = self.config.get('platforms', {})
        for platform_key, platform_config in platforms.items():
            if platform_config.get('name', platform_key) == platform_name:
                return platform_config.get('accessibility', {}).get('disabled_rules', [])
        return []

    def _determine_platform_from_url(self, url: str) -> str:
        """Determine platform based on URL patterns from sites.yaml"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Check platform mappings from config
        platforms = self.config.get('platforms', {})
        for platform_key, platform_config in platforms.items():
            sites = platform_config.get('sites', [])
            platform_name = platform_config.get('name', platform_key)  # Use the name from config
            
            for site_pattern in sites:
                site_domain = urlparse(site_pattern).netloc.lower()
                # Check if the crawled URL domain matches the site pattern domain
                # or if it's a subdomain of the same root domain
                if (domain == site_domain or 
                    domain.endswith('.' + site_domain) or
                    site_domain.endswith('.' + domain) or
                    # Handle mgcafe ↔ ca domain mapping
                    (site_domain.replace('mgcafe.', 'ca.') == domain) or
                    (domain.replace('ca.', 'mgcafe.') == site_domain) or
                    # Handle subdomain variations
                    (site_domain.replace('mgcafe.', 'ca.') in domain) or
                    (domain.replace('ca.', 'mgcafe.') in site_domain) or
                    # Handle personnel.ca.uky.edu -> ces-personnel.mgcafe.uky.edu mapping
                    (domain == 'personnel.ca.uky.edu' and 'personnel' in site_domain) or
                    (domain == 'personnel.mgcafe.uky.edu' and 'personnel' in site_domain) or
                    # Handle events.ca.uky.edu -> events.mgcafe.uky.edu mapping  
                    (domain == 'events.ca.uky.edu' and 'events' in site_domain) or
                    (domain == 'events.mgcafe.uky.edu' and 'events' in site_domain)):
                    return platform_name
        
        return 'unknown'

    async def _fetch_page(self, url: str, base_domain: str = None, platform: str = None, source_page: str = None) -> Optional[CrawledPage]:
        """Fetch and parse a single page"""
        # Always work with a normalized URL to avoid duplicate variants
        url = self._normalize_url(url)

        if not await self._can_crawl(url, base_domain):
            return None
        
        parsed = urlparse(url)
        await self._rate_limit(parsed.netloc)
        
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    self.logger.warning(f"HTTP {response.status} for {url}")
                    # Save non-200 responses so broken links appear in reports
                    content_type = response.headers.get('content-type', '').split(';')[0]
                    is_pdf = 'pdf' in content_type or url.lower().endswith('.pdf')
                    issue = {
                        'type': 'broken_link',
                        'severity': 'critical',
                        'message': f'HTTP {response.status}: Resource not found or unavailable',
                        'context': f'URL returned status {response.status}',
                    }
                    return CrawledPage(
                        url=url,
                        title=f"{'PDF' if is_pdf else 'Page'}: {url.split('/')[-1]} [{response.status}]",
                        status_code=response.status,
                        content_type=content_type or ('application/pdf' if is_pdf else 'text/html'),
                        content_length=0,
                        links=[],
                        images=[],
                        forms=[],
                        headings=[],
                        html_content='',
                        timestamp=datetime.now().isoformat(),
                        site_name=parsed.netloc,
                        platform=platform,
                        source_page=source_page,
                        issues=[issue],
                        accessibility_score=0,
                        pdf_analysis={},
                        is_archived=False,
                    )

                content_type = response.headers.get('content-type', '').split(';')[0]
                
                # Handle different content types
                if content_type == 'application/pdf':
                    # For PDFs, analyze accessibility using pypdf
                    content_bytes = await response.read()
                    
                    # Analyze PDF accessibility using new pypdf-based checker
                    try:
                        from pdf_accessibility_pypdf import PDFAccessibilityChecker
                        pdf_checker = PDFAccessibilityChecker()
                        analysis_result = pdf_checker.analyze_pdf_accessibility(content_bytes, url)
                        
                        # Convert analysis result to issues format
                        accessibility_issues = []
                        if analysis_result.get('issues'):
                            for issue in analysis_result['issues']:
                                accessibility_issues.append({
                                    'rule_id': issue.get('rule', ''),
                                    'rule_title': issue.get('rule', ''),
                                    'description': issue.get('description', ''),
                                    'wcag_level': issue.get('wcag_level', 'PDF/UA'),
                                    'severity': issue.get('severity', ''),
                                    'element': issue.get('element', 'PDF'),
                                    'element_type': issue.get('element_type', 'PDF'),
                                    'line_number': None,
                                    'recommendation': issue.get('recommendation', '')
                                })
                        
                        self.logger.info(f"Analyzed PDF: {url} - {analysis_result.get('issue_count', 0)} issues found")
                        
                    except Exception as pdf_analysis_error:
                        self.logger.warning(f"Failed to analyze PDF {url}: {pdf_analysis_error}")
                        accessibility_issues = []
                        analysis_result = {
                            'issue_count': 0,
                            'accessibility_score': 100,
                            'wcag_compliant': None,
                            'issues': [],
                            'analysis_method': 'None'
                        }
                    
                    # Check if source page is archived to propagate to PDF
                    is_archived = False
                    if source_page and self.db_enabled and self.db_session:
                        from database import Page as DbPage
                        source_page_record = self.db_session.query(DbPage).filter_by(url=source_page).first()
                        if source_page_record:
                            is_archived = source_page_record.is_archived
                            if is_archived:
                                self.logger.info(f"PDF {url} marked as archived (source page is archived)")
                    
                    page = CrawledPage(
                        url=url,
                        title=f"PDF Document: {url.split('/')[-1]}",
                        status_code=response.status,
                        content_type=content_type,
                        content_length=len(content_bytes),
                        links=[],
                        images=[],
                        forms=[],
                        headings=[],
                        html_content=content_bytes.decode('utf-8', errors='ignore'),
                        timestamp=datetime.now().isoformat(),
                        site_name=parsed.netloc,
                        platform=platform,
                        source_page=source_page,
                        issues=accessibility_issues,
                        accessibility_score=analysis_result.get('score', 100),
                        pdf_analysis=analysis_result,
                        is_archived=is_archived
                    )
                    self.logger.info(f"Found and analyzed PDF: {url} ({len(content_bytes)} bytes)")
                    return page
                
                elif not content_type.startswith('text/html'):
                    # For other non-HTML content, skip but log
                    self.logger.debug(f"Skipping non-HTML content: {url} ({content_type})")
                    return None
                
                # Handle HTML content
                content = await response.text()
                soup = BeautifulSoup(content, 'lxml')
                
                # Extract page information
                title = soup.title.string.strip() if soup.title else ''
                
                # Check if page has archive message
                is_archived = self._check_for_archive_message(content)
                if is_archived:
                    self.logger.info(f"Archive message detected on page: {url}")
                
                page = CrawledPage(
                    url=url,
                    title=title,
                    status_code=response.status,
                    content_type=content_type,
                    content_length=len(content),
                    links=self._extract_links(soup, url),
                    images=self._extract_images(soup, url),
                    forms=self._extract_forms(soup),
                    headings=self._extract_headings(soup),
                    html_content=content,
                    timestamp=datetime.now().isoformat(),
                    site_name=parsed.netloc,
                    platform=platform,
                    source_page=source_page,
                    is_archived=is_archived
                )
                
                return page
                
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {e}")
            return None

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Extract all links from a page, filtering to same domain only"""
        links = []
        base_domain = urlparse(base_url).netloc
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(base_url, href)
            
            # Skip anchor links (same-page links with #)
            if '#' in full_url:
                # Only skip if it's the same URL with just an anchor
                base_without_anchor = full_url.split('#')[0]
                if base_without_anchor == base_url:
                    continue
            
            # Only include HTTP/HTTPS links from same domain or allowed UK domains
            if full_url.startswith(('http://', 'https://')):
                link_domain = urlparse(full_url).netloc
                # Allow exact domain match, subdomains, or specific mgcafe↔ca domain mapping for the same site
                # This keeps crawling within the specific site being crawled
                if (link_domain == base_domain or 
                    link_domain.endswith('.' + base_domain) or
                    base_domain.endswith('.' + link_domain) or
                    # Handle mgcafe ↔ ca domain mapping for the same site (e.g., abt.mgcafe.uky.edu ↔ abt.ca.uky.edu)
                    (base_domain.replace('mgcafe.uky.edu', 'ca.uky.edu') == link_domain) or
                    (link_domain.replace('mgcafe.uky.edu', 'ca.uky.edu') == base_domain)):
                    links.append(full_url)
            # Include relative URLs that become absolute URLs with the same domain after urljoin
            elif not href.startswith(('http://', 'https://', '#', 'mailto:', 'tel:', 'javascript:')):
                # This handles relative URLs like /files/document.pdf that get converted to absolute URLs
                link_domain = urlparse(full_url).netloc
                if link_domain == base_domain:
                    links.append(full_url)
        
        return list(set(links))

    def _extract_pdf_links(self, links: List[str], base_domain: str) -> List[str]:
        """Extract PDF links from a list of URLs, filtering to same domain or allowed UK domains"""
        pdf_links = []
        
        for link in links:
            # Check if URL ends with .pdf (case insensitive)
            if link.lower().endswith('.pdf'):
                # Include PDFs from same domain, subdomains, or specific mgcafe↔ca domain mapping for the same site
                link_domain = urlparse(link).netloc
                if (link_domain == base_domain or 
                    link_domain.endswith('.' + base_domain) or
                    base_domain.endswith('.' + link_domain) or
                    # Handle mgcafe ↔ ca domain mapping for the same site (e.g., abt.mgcafe.uky.edu ↔ abt.ca.uky.edu)
                    (base_domain.replace('mgcafe.uky.edu', 'ca.uky.edu') == link_domain) or
                    (link_domain.replace('mgcafe.uky.edu', 'ca.uky.edu') == base_domain)):
                    pdf_links.append(link)
        
        return list(set(pdf_links))  # Remove duplicates

    def _extract_images(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Extract all image URLs and metadata from a page"""
        images = []
        for img in soup.find_all('img'):
            img_data = {}
            if img.get('src'):
                img_data['src'] = img['src']
            if img.get('alt'):
                img_data['alt'] = img['alt']
            if img.get('title'):
                img_data['title'] = img['title']
            if img_data:
                images.append(img_data)
        return images

    def _extract_forms(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract form information from a page"""
        forms = []
        for form in soup.find_all('form'):
            form_info = {
                'action': form.get('action', ''),
                'method': form.get('method', 'GET'),
                'fields': []
            }
            
            for input_tag in form.find_all(['input', 'select', 'textarea']):
                field_info = {
                    'type': input_tag.name,
                    'name': input_tag.get('name', ''),
                    'input_type': input_tag.get('type', '') if input_tag.name == 'input' else ''
                }
                form_info['fields'].append(field_info)
            
            forms.append(form_info)
        return forms

    def _extract_headings(self, soup: BeautifulSoup) -> Dict[str, List[str]]:
        """Extract heading structure from a page"""
        headings = {f'h{i}': [] for i in range(1, 7)}
        
        for i in range(1, 7):
            for heading in soup.find_all(f'h{i}'):
                text = heading.get_text().strip()
                if text:
                    headings[f'h{i}'].append(text)
        
        return headings

    async def _fetch_specific_sitemap(self, sitemap_url: str) -> List[str]:
        """Fetch and parse a specific sitemap URL"""
        try:
            parsed = urlparse(sitemap_url)
            await self._rate_limit(parsed.netloc)
            async with self.session.get(sitemap_url) as response:
                if response.status == 200:
                    content = await response.text()
                    # Use XML parser for sitemaps, fallback to HTML
                    try:
                        soup = BeautifulSoup(content, 'xml')
                    except:
                        soup = BeautifulSoup(content, 'lxml')
                    
                    # Extract URLs from sitemap
                    urls = []
                    for loc in soup.find_all('loc'):
                        if loc.text.strip():
                            urls.append(loc.text.strip())
                    
                    # If this is a sitemap index, fetch child sitemaps
                    if soup.find('sitemapindex'):
                        child_urls = []
                        for sitemap in soup.find_all('sitemap'):
                            child_loc = sitemap.find('loc')
                            if child_loc:
                                child_sitemap_urls = await self._fetch_specific_sitemap(child_loc.text.strip())
                                child_urls.extend(child_sitemap_urls)
                        urls.extend(child_urls)
                    
                    if urls:
                        self.logger.info(f"Found {len(urls)} URLs in sitemap: {sitemap_url}")
                        return list(set(urls))  # Remove duplicates
                else:
                    self.logger.debug(f"Sitemap returned status {response.status}: {sitemap_url}")
        except Exception as e:
            self.logger.error(f"Failed to fetch sitemap {sitemap_url}: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
        
        return []

    async def _fetch_sitemap(self, base_url: str) -> List[str]:
        """Fetch and parse sitemap.xml for a website"""
        parsed = urlparse(base_url)
        scheme = parsed.scheme or "https"
        sitemap_urls = [
            f"{scheme}://{parsed.netloc}/sitemap.xml",
            f"{scheme}://{parsed.netloc}/sitemap_index.xml",
            f"{base_url.rstrip('/')}/sitemap.xml"
        ]
        
        for sitemap_url in sitemap_urls:
            urls = await self._fetch_specific_sitemap(sitemap_url)
            if urls:
                return urls
        
        return []

    async def crawl_single_page(self, url: str) -> List[CrawledPage]:
        """Crawl a single page and discover/crawl its PDF links"""
        self.logger.info(f"Starting single page crawl: {url}")
        
        # Setup database if enabled
        if self.db_enabled:
            self._setup_database()
        
        # Create session
        await self._create_session()
        
        try:
            # Determine platform from URL
            platform = self._determine_platform_from_url(url)
            base_domain = urlparse(url).netloc
            
            # Crawl the main page
            page = await self._fetch_page(url, base_domain, platform)
            if page:
                self.crawled_pages.append(page)
                self.logger.info(f"Crawled main page: {url}")
                
                # Discover and crawl PDF links
                if page.content_type.startswith('text/html') and page.links:
                    pdf_links = self._extract_pdf_links(page.links, base_domain)
                    self.logger.info(f"Found {len(pdf_links)} PDF links to crawl")
                    
                    for pdf_url in pdf_links:
                        if pdf_url not in self.visited_urls:
                            # Crawl the PDF with source page information
                            pdf_page = await self._fetch_page(pdf_url, base_domain, platform, source_page=url)
                            if pdf_page:
                                self.crawled_pages.append(pdf_page)
                                self.logger.info(f"Crawled PDF: {pdf_url}")
                                
                                # Save PDF to database immediately
                                if self.db_enabled and self.db_session:
                                    self._save_page_incremental(pdf_page)
                                
                                # Run accessibility testing on PDF if enabled
                                if self.run_accessibility and self.accessibility_checker:
                                    try:
                                        disabled_rules = self._get_disabled_rules_for_platform(platform)
                                        platform_checker = WCAGChecker(disabled_rules=disabled_rules)
                                        
                                        # Create page dict for WCAGChecker
                                        page_dict = {
                                            'url': pdf_page.url,
                                            'html_content': pdf_page.html_content,
                                            'title': pdf_page.title
                                        }
                                        accessibility_report = platform_checker.check_page(page_dict)
                                        pdf_page.issues = [asdict(issue) for issue in accessibility_report.issues]
                                        pdf_page.accessibility_score = int(accessibility_report.score)
                                        self.logger.info(f"Accessibility issues found on {pdf_url}: {len(pdf_page.issues)} issues (Score: {pdf_page.accessibility_score}/100)")
                                        
                                        # Re-save PDF with accessibility data
                                        if self.db_enabled and self.db_session:
                                            self._save_page_incremental(pdf_page)
                                    except Exception as e:
                                        self.logger.warning(f"Failed accessibility check for {pdf_url}: {e}")
                
                # Save to database if enabled (main crawl already saved HTML pages)
                if self.db_enabled and self.db_session:
                    # Save each PDF individually as they were processed
                    for pdf_page in [p for p in self.crawled_pages if p.content_type == 'application/pdf']:
                        self._save_page_incremental(pdf_page)
                    self.logger.info(f"Saved {len([p for p in self.crawled_pages if p.content_type == 'application/pdf'])} PDFs to database")
            
            return self.crawled_pages
            
        finally:
            # Cleanup
            if self.session:
                await self.session.close()
            if self.db_session:
                self.db_session.close()

    async def crawl_single_site(self, url: str, max_depth: int = None, max_pages: int = None) -> List[CrawledPage]:
        """Crawl a single website"""
        if max_depth is None:
            max_depth = self.config['crawler_settings']['max_depth']
        if max_pages is None:
            max_pages = self.config['crawler_settings']['max_pages']
        
        # Setup database and optional incremental saving
        self._setup_incremental_save()
        
        await self._create_session()
        
        try:
            self.logger.info(f"Starting crawl of {url}")
            self.visited_urls.clear()
            self.crawled_pages.clear()
            
            # Get the base domain for filtering
            base_domain = urlparse(url).netloc
            
            # Check if domain is allowed before starting crawl
            allowed_domains = self.config['crawler_settings'].get('allowed_domains', [])
            if allowed_domains and not any(allowed in base_domain for allowed in allowed_domains):
                self.logger.error(f"❌ Cannot crawl '{base_domain}' - domain not in allowed_domains list!")
                self.logger.error(f"   Add '{base_domain}' to config/sites.yaml under crawler_settings.allowed_domains")
                self.logger.error(f"   Current allowed domains: {', '.join(allowed_domains)}")
                return []
            
            # First, try to find sitemap.xml
            sitemap_urls = await self._fetch_sitemap(url)
            
            # Check if sitemap is useful (has more than 10 URLs)
            # If sitemap is too small, fall back to traditional crawling
            if sitemap_urls and len(sitemap_urls) >= 10:
                self.logger.info(f"Using sitemap with {len(sitemap_urls)} URLs")
                # Filter sitemap URLs to same root domain (allow any subdomain)
                filtered_urls = []
                base_domain_parts = base_domain.split('.')
                self.logger.info(f"Filtering {len(sitemap_urls)} URLs for base domain: {base_domain}")
                
                for sitemap_url in sitemap_urls:
                    sitemap_domain = urlparse(sitemap_url).netloc
                    sitemap_domain_parts = sitemap_domain.split('.')
                    
                    # Check if domains share the same root domain (last 2 parts: uky.edu)
                    # This allows events.mgcafe.uky.edu to crawl events.ca.uky.edu URLs
                    if (len(base_domain_parts) >= 2 and len(sitemap_domain_parts) >= 2 and
                        base_domain_parts[-2:] == sitemap_domain_parts[-2:]):
                        filtered_urls.append(sitemap_url)
                    # Also allow exact matches
                    elif sitemap_domain == base_domain:
                        filtered_urls.append(sitemap_url)
                
                self.logger.info(f"After filtering: {len(filtered_urls)} URLs remain")
                
                # For sitemaps, use the actual count unless explicitly capped
                if max_pages == self.config['crawler_settings'].get('max_pages', 1000):
                    # Using default max_pages, allow sitemap to determine count
                    urls_to_visit = [(self._normalize_url(sitemap_url), 0) for sitemap_url in filtered_urls]
                    effective_max_pages = len(urls_to_visit)  # Use sitemap count exactly
                    self.logger.info(f"Will crawl all {len(urls_to_visit)} same-domain URLs from sitemap")
                else:
                    # Explicit max_pages set, respect the limit
                    urls_to_visit = [(self._normalize_url(sitemap_url), 0) for sitemap_url in filtered_urls[:max_pages]]
                    effective_max_pages = max_pages
                    self.logger.info(f"Limited to {len(urls_to_visit)} URLs from sitemap (cap: {max_pages})")
                
                # Debug: Show first few URLs to be crawled
                if urls_to_visit:
                    self.logger.info(f"First 3 URLs to crawl:")
                    for i, (url, depth) in enumerate(urls_to_visit[:3]):
                        self.logger.info(f"  {i+1}. {url}")
            else:
                if sitemap_urls:
                    self.logger.info(f"Sitemap found but only has {len(sitemap_urls)} URLs - using traditional crawling instead")
                else:
                    self.logger.info("No sitemap found, using traditional crawling")
                # Normalize seed URL so root with/without trailing slash are treated the same
                urls_to_visit = [(self._normalize_url(url), 0)]
                effective_max_pages = max_pages
            
            # Track discovered PDFs separately to ensure they get processed
            discovered_pdfs = []
            
            with tqdm(desc="Crawling pages") as pbar:
                while urls_to_visit and len(self.crawled_pages) < effective_max_pages:
                    # Handle both old format (url, depth) and new format (url, depth, source_page)
                    queue_item = urls_to_visit.pop(0)
                    if len(queue_item) == 3:
                        current_url, depth, source_page = queue_item
                    else:
                        current_url, depth = queue_item
                        source_page = None

                    # Normalize current URL and source_page so trailing slashes don't create duplicates
                    normalized_url = self._normalize_url(current_url)
                    if source_page:
                        source_page = self._normalize_url(source_page)
                    
                    self.logger.debug(f"Processing URL: {normalized_url} (depth: {depth})")
                    if source_page:
                        self.logger.debug(f"Source page: {source_page}")
                    
                    if normalized_url in self.visited_urls:
                        self.logger.debug(f"Skipping {normalized_url}: already visited")
                        continue
                    if depth > max_depth:
                        self.logger.debug(f"Skipping {current_url}: depth {depth} > max_depth {max_depth}")
                        continue
                    
                    self.visited_urls.add(normalized_url)
                    self.logger.debug(f"Fetching page: {normalized_url}")
                    # Determine platform from URL or use default
                    platform = self._determine_platform_from_url(normalized_url)
                    page = await self._fetch_page(normalized_url, base_domain, platform, source_page)
                    
                    if page:
                        self.logger.debug(f"Successfully fetched: {current_url}")
                        self.crawled_pages.append(page)
                        
                        # Save page incrementally for real-time dashboard updates
                        self._save_page_incremental(page)
                        
                        # Extract and queue links from HTML pages (for continued crawling)
                        if page.content_type.startswith('text/html') and page.links:
                            # Queue regular HTML links for continued crawling
                            if depth < max_depth:
                                for link_url in page.links:
                                    normalized_link = self._normalize_url(link_url)
                                    if (normalized_link not in self.visited_urls and 
                                        len(self.crawled_pages) < effective_max_pages):
                                        # Add HTML link to crawl queue at next depth
                                        urls_to_visit.append((normalized_link, depth + 1, normalized_url))
                                        self.logger.debug(f"Added HTML link to crawl queue: {normalized_link}")
                            
                            # Collect PDF links for processing after main crawl
                            pdf_links = self._extract_pdf_links(page.links, base_domain)
                            for pdf_url in pdf_links:
                                normalized_pdf = self._normalize_url(pdf_url)
                                if normalized_pdf not in self.visited_urls and normalized_pdf not in [p[0] for p in discovered_pdfs]:
                                    # Store PDF with source page information for later processing
                                    discovered_pdfs.append((normalized_pdf, normalized_url))
                                    self.logger.debug(f"Collected PDF: {normalized_pdf} (from {normalized_url})")
                        
                        # Run accessibility testing if enabled
                        if self.run_accessibility and self.accessibility_checker:
                            try:
                                # Get disabled rules for this platform
                                disabled_rules = self._get_disabled_rules_for_platform(platform)
                                
                                # Create platform-specific accessibility checker
                                platform_checker = WCAGChecker(disabled_rules=disabled_rules)
                                
                                accessibility_report = platform_checker.check_page(asdict(page))
                                self.accessibility_reports.append(accessibility_report)
                                
                                # Apply accessibility results to the page
                                page.accessibility_score = int(accessibility_report.score)
                                page.issue_count = accessibility_report.total_issues  # Use countable issues only
                                page.issues = [asdict(issue) for issue in accessibility_report.issues]
                                
                                # Re-save page to database with accessibility data
                                self._save_page_incremental(page)
                                
                                # Log summary for this page
                                if accessibility_report.total_issues > 0:
                                    self.logger.info(
                                        f"Accessibility issues found on {current_url}: "
                                        f"{accessibility_report.total_issues} issues "
                                        f"(Score: {accessibility_report.score:.1f}/100)"
                                    )
                                else:
                                    self.logger.info(f"No accessibility issues found on {current_url} (Score: {accessibility_report.score:.1f}/100)")
                            except Exception as e:
                                self.logger.error(f"Error running accessibility tests on {current_url}: {e}")
                        
                        pbar.update(1)
                    else:
                        self.logger.debug(f"Failed to fetch page: {current_url}")
                        pbar.update(1)
            
            self.logger.info(f"Crawled {len(self.crawled_pages)} pages")
            
            # Process discovered PDFs after main crawl
            if discovered_pdfs:
                self.logger.info(f"Processing {len(discovered_pdfs)} discovered PDFs...")
                pdf_success_count = 0
                pdf_fail_count = 0
                
                for idx, (pdf_url, source_page) in enumerate(discovered_pdfs, 1):
                    try:
                        normalized_pdf = self._normalize_url(pdf_url)
                        normalized_source = self._normalize_url(source_page) if source_page else None
                        
                        if normalized_pdf in self.visited_urls:
                            self.logger.debug(f"[{idx}/{len(discovered_pdfs)}] Skipping already visited PDF: {normalized_pdf}")
                            continue
                        
                        self.logger.debug(f"[{idx}/{len(discovered_pdfs)}] Processing PDF: {normalized_pdf}")
                        
                        # Check if source page has archive message
                        source_is_archived = False
                        if normalized_source:
                            # Find the source page in crawled pages to check if it's archived
                            for crawled_page in self.crawled_pages:
                                if crawled_page.url == normalized_source:
                                    source_is_archived = crawled_page.is_archived
                                    break
                        
                        # Crawl the PDF with source page information
                        pdf_page = await self._fetch_page(normalized_pdf, base_domain, platform, source_page=normalized_source)
                        if pdf_page:
                            # Mark PDF as archived if source page was archived
                            if source_is_archived:
                                pdf_page.is_archived = True
                                self.logger.info(f"PDF marked as archived (source page has archive message): {normalized_pdf}")
                            self.crawled_pages.append(pdf_page)
                            self.visited_urls.add(normalized_pdf)
                            self.logger.info(f"Crawled PDF: {normalized_pdf} (from {normalized_source})")
                            
                            # Save PDF to database immediately
                            if self.db_enabled and self.db_session:
                                self._save_page_incremental(pdf_page)
                            
                            # Run accessibility testing on PDF if enabled
                            if self.run_accessibility and self.accessibility_checker:
                                try:
                                    disabled_rules = self._get_disabled_rules_for_platform(platform)
                                    platform_checker = WCAGChecker(disabled_rules=disabled_rules)
                                    
                                    # Create page dict for WCAGChecker
                                    page_dict = {
                                        'url': pdf_page.url,
                                        'html_content': pdf_page.html_content,
                                        'title': pdf_page.title
                                    }
                                    accessibility_report = platform_checker.check_page(page_dict)
                                    pdf_page.issues = [asdict(issue) for issue in accessibility_report.issues]
                                    pdf_page.accessibility_score = int(accessibility_report.score)
                                    self.logger.info(f"Accessibility issues found on {pdf_url}: {len(pdf_page.issues)} issues (Score: {pdf_page.accessibility_score}/100)")
                                    
                                    # Re-save PDF with accessibility data
                                    if self.db_enabled and self.db_session:
                                        self._save_page_incremental(pdf_page)
                                except Exception as e:
                                    self.logger.warning(f"Failed accessibility check for {pdf_url}: {e}")
                            
                            pdf_success_count += 1
                        else:
                            self.logger.warning(f"[{idx}/{len(discovered_pdfs)}] Failed to fetch PDF: {normalized_pdf}")
                            pdf_fail_count += 1
                            
                    except Exception as e:
                        self.logger.error(f"[{idx}/{len(discovered_pdfs)}] Error processing PDF {pdf_url}: {e}")
                        import traceback
                        self.logger.error(f"Traceback: {traceback.format_exc()}")
                        pdf_fail_count += 1
                        # Continue to next PDF
                        continue
                
                self.logger.info(f"PDF processing complete: {pdf_success_count} successful, {pdf_fail_count} failed out of {len(discovered_pdfs)} total")
                self.logger.info(f"Final total: {len(self.crawled_pages)} pages (including {pdf_success_count} PDFs)")
            
            return self.crawled_pages
            
        finally:
            await self.session.close()
            # Close database connection
            if self.db_session:
                self.db_session.close()
                self.logger.info("Database connection closed")

    async def crawl_platforms(self, platform_names: List[str] = None, max_depth: int = None, max_pages: int = None) -> Dict[str, List[CrawledPage]]:
        """Crawl multiple platforms"""
        platforms = self.config.get('platforms', {})
        
        if platform_names is None:
            platform_names = list(platforms.keys())
        
        # Setup incremental saving
        self._setup_incremental_save()
        
        results = {}
        self.failed_sites = []
        failed_sites = self.failed_sites
        
        for platform_name in platform_names:
            if platform_name not in platforms:
                self.logger.warning(f"Platform '{platform_name}' not found in config")
                continue
                
            platform_config = platforms[platform_name]
            platform_pages = []
            sites = platform_config.get('sites', [])
            
            self.logger.info(f"Starting platform '{platform_name}' with {len(sites)} sites")
            
            for idx, site in enumerate(sites, 1):
                site_url = site if isinstance(site, str) else site['url']
                site_name = site_url  # Use URL as name since no name field
                
                try:
                    self.logger.info(f"[{idx}/{len(sites)}] Crawling site: {site_url}")
                    pages = await self.crawl_single_site(site_url, max_depth=max_depth, max_pages=max_pages)
                    
                    # Add platform and site info to each page
                    for page in pages:
                        page.platform = platform_config.get('name', platform_name)
                        page.site_name = site_name
                    
                    platform_pages.extend(pages)
                    self.logger.info(f"✅ [{idx}/{len(sites)}] Completed {site_url}: {len(pages)} pages crawled")
                    
                    if not pages:
                        failed_sites.append((site_url, "no pages crawled (site may be down or redirecting)"))
                    
                except Exception as e:
                    self.logger.error(f"❌ [{idx}/{len(sites)}] Failed to crawl {site_url}: {e}")
                    import traceback
                    self.logger.error(f"Traceback: {traceback.format_exc()}")
                    failed_sites.append((site_url, str(e)))
                    # Continue to next site instead of stopping
                    continue
            
            results[platform_name] = platform_pages
            self.logger.info(f"Platform '{platform_name}' complete: {len(platform_pages)} total pages from {len(sites)} sites")
        
        if failed_sites:
            self.logger.warning("=" * 60)
            self.logger.warning(f"⚠️  {len(failed_sites)} site(s) failed or returned zero pages — consider removing from config/sites.yaml:")
            for site_url, reason in failed_sites:
                self.logger.warning(f"   - {site_url} ({reason})")
            self.logger.warning("=" * 60)
        else:
            self.logger.info("All sites crawled successfully")
        
        return results

    def _setup_incremental_save(self, output_dir: str = "output"):
        """Setup incremental saving files and database connection"""
        # Always ensure database is ready for a crawl
        if self.db_enabled and self.db_session is None:
            self._setup_database()

        # If file output is disabled, skip creating JSON backup files
        if not self.incremental_save_enabled:
            return

        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_crawl_file = output_path / f"crawled_pages_{timestamp}.json"
        self.current_latest_file = output_path / "crawled_pages_latest.json"
        
        # Initialize empty files
        with open(self.current_crawl_file, 'w', encoding='utf-8') as f:
            json.dump([], f)
        with open(self.current_latest_file, 'w', encoding='utf-8') as f:
            json.dump([], f)
        
        self.logger.info(f"Setup incremental saving: {self.current_crawl_file}")

    def _setup_database(self):
        """Setup database connection"""
        try:
            from database import get_db_session, init_db
            
            # Initialize database if needed
            init_db()
            
            # Get database session
            self.db_session = get_db_session()
            
            self.logger.info("Database connection established")
            
        except Exception as e:
            print(f"Failed to setup database: {e}")
            import traceback
            traceback.print_exc()
            self.logger.error(f"Failed to setup database: {e}")
            self.db_enabled = False

    def _clean_page_data_for_json(self, page_data: dict) -> dict:
        """Clean page data to remove invalid control characters for JSON serialization"""
        if isinstance(page_data, dict):
            cleaned = {}
            for key, value in page_data.items():
                cleaned[key] = self._clean_page_data_for_json(value)
            return cleaned
        elif isinstance(page_data, list):
            return [self._clean_page_data_for_json(item) for item in page_data]
        elif isinstance(page_data, str):
            # Remove control characters except for common valid ones (tab, newline, carriage return)
            import re
            # Keep \t, \n, \r but remove other control characters
            return re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', page_data)
        else:
            return page_data

    def _save_page_incremental(self, page: CrawledPage):
        """Save a single page incrementally to both file and database"""
        # Save to JSON files (backup)
        if self.incremental_save_enabled and self.current_crawl_file:
            try:
                # Read existing data
                with open(self.current_crawl_file, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                
                # Clean page data and append new page
                try:
                    page_data = asdict(page)
                except Exception:
                    # Fallback for database Page objects
                    page_data = {
                        'url': page.url,
                        'title': page.title,
                        'content_type': page.content_type,
                        'accessibility_score': page.accessibility_score,
                        'issues': getattr(page, 'issues', None),
                        'pdf_analysis': getattr(page, 'pdf_analysis', None),
                        'source_page': getattr(page, 'source_page', None),
                        'platform': getattr(page, 'platform', None),
                        'site_name': getattr(page, 'site_name', None)
                    }
                cleaned_page_data = self._clean_page_data_for_json(page_data)
                existing_data.append(cleaned_page_data)
                
                # Save back to file
                with open(self.current_crawl_file, 'w', encoding='utf-8') as f:
                    json.dump(existing_data, f, indent=2, default=str)
                
                # Also update the "latest" file for dashboard
                with open(self.current_latest_file, 'w', encoding='utf-8') as f:
                    json.dump(existing_data, f, indent=2, default=str)
                
                self.logger.debug(f"Saved page to JSON: {page.url} (Total: {len(existing_data)} pages)")
                
            except Exception as e:
                self.logger.error(f"Error saving page to JSON: {e}")
        
        # Save to database (primary storage)
        if self.db_enabled and self.db_session:
            try:
                from database import create_or_update_site, create_or_update_page, PageLink
                
                # Extract site info from URL
                from urllib.parse import urlparse
                parsed_url = urlparse(page.url)
                site_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                
                # Create/update site record
                site = create_or_update_site(
                    session=self.db_session,
                    url=site_url,
                    title=page.title or site_url,
                    platform=getattr(page, 'platform', None),
                    site_name=getattr(page, 'site_name', parsed_url.netloc)
                )
                
                # Handle issues for different page types
                issues_list = []
                if hasattr(page, 'issues') and page.issues:
                    issues_list = page.issues
                elif hasattr(page, 'pdf_analysis') and page.pdf_analysis and page.pdf_analysis.get('issues'):
                    issues_list = page.pdf_analysis.get('issues', [])
                
                # Create/update page record
                page_record = create_or_update_page(
                    session=self.db_session,
                    site_id=site.id,
                    url=page.url,
                    title=page.title,
                    status_code=page.status_code,
                    content_type=page.content_type,
                    content_length=page.content_length,
                    accessibility_score=page.accessibility_score,
                    issues=issues_list,
                    source_page=getattr(page, 'source_page', None),
                    is_archived=getattr(page, 'is_archived', False)
                )
                
                # Save PDF analysis if available
                if hasattr(page, 'pdf_analysis') and page.pdf_analysis:
                    page_record.pdf_analysis = page.pdf_analysis

                # For HTML pages, capture outgoing links and their anchor text into page_links
                if getattr(page, 'content_type', '').startswith('text/html') and getattr(page, 'html_content', None):
                    try:
                        # Remove existing links for this page to avoid duplicates on re-crawl
                        self.db_session.query(PageLink).filter(PageLink.from_page_id == page_record.id).delete()

                        soup = BeautifulSoup(page.html_content, 'lxml')
                        from urllib.parse import urljoin

                        for a in soup.find_all('a', href=True):
                            href = a['href']
                            full_url = urljoin(page.url, href)
                            normalized_full_url = self._normalize_url(full_url)
                            link_text = a.get_text(strip=True) or ''
                            if not normalized_full_url or not link_text:
                                continue
                            link = PageLink(
                                from_page_id=page_record.id,
                                to_url=normalized_full_url,
                                link_text=link_text
                            )
                            self.db_session.add(link)
                    except Exception as link_error:
                        self.logger.warning(f"Failed to save page links for {page.url}: {link_error}")
                
                # Commit the transaction
                self.db_session.commit()
                
                self.logger.debug(f"Saved page to database: {page.url} (ID: {page_record.id})")
                
            except Exception as e:
                self.logger.error(f"Error saving page to database: {e}")
                if self.db_session:
                    self.db_session.rollback()

    async def save_results(self, crawled_pages: List[CrawledPage], output_dir: str = "output"):
        """Save crawled results to JSON and CSV files"""
        if not self.write_files:
            # No-op when file output is disabled
            self.logger.info("File output disabled (write_files=False); skipping save_results JSON/CSV write")
            return

        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save crawled pages as JSON
        json_file = output_path / f"crawled_pages_{timestamp}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            # Handle both dataclass and dict objects
            pages_data = []
            for page in crawled_pages:
                if hasattr(page, '__dataclass_fields__'):
                    pages_data.append(asdict(page))
                elif isinstance(page, dict):
                    pages_data.append(page)
                else:
                    # Convert object to dict if it's not a dataclass
                    pages_data.append(page.__dict__ if hasattr(page, '__dict__') else str(page))
            json.dump(pages_data, f, indent=2, default=str)
        
        # Save accessibility reports if available
        if self.run_accessibility and self.accessibility_reports:
            accessibility_file = output_path / f"accessibility_report_{timestamp}.json"
            with open(accessibility_file, 'w', encoding='utf-8') as f:
                json.dump([asdict(report) for report in self.accessibility_reports], f, indent=2, default=str)
            
            # Generate accessibility summary
            self._save_accessibility_summary(output_path, timestamp)
        
        # Save as CSV
        csv_file = output_path / f"crawled_pages_{timestamp}.csv"
        
        # First pass: collect all possible fieldnames
        all_fieldnames = set()
        all_rows = []
        
        for page in crawled_pages:
            # Convert complex objects to strings for CSV
            if hasattr(page, '__dataclass_fields__'):
                row = asdict(page)
            elif isinstance(page, dict):
                row = page.copy()
            else:
                row = page.__dict__.copy() if hasattr(page, '__dict__') else {}
            
            # Remove database-specific fields
            row.pop('_sa_instance_state', None)
            
            # Collect all fieldnames
            all_fieldnames.update(row.keys())
            all_rows.append(row)
        
        # Write CSV with all fieldnames
        fieldnames = sorted(list(all_fieldnames))  # Sort for consistent order
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in all_rows:
                # Ensure all fields are strings for CSV
                row['links'] = ';'.join(row['links']) if row.get('links') else ''
                row['images'] = ';'.join([img.get('src', '') for img in row['images']]) if row.get('images') else ''
                row['forms'] = ';'.join([str(form) for form in row['forms']]) if row.get('forms') else ''
                row['headings'] = ';'.join([f"{k}:{','.join(v)}" for k, v in row['headings'].items()]) if row.get('headings') else ''
                
                writer.writerow(row)
        
        self.logger.info(f"Saved results to {output_path}/")
        return str(json_file), str(csv_file)

    def _save_accessibility_summary(self, output_path: Path, timestamp: str):
        """Generate and save accessibility summary report"""
        if not self.accessibility_reports:
            return
        
        # Calculate overall statistics
        total_pages = len(self.accessibility_reports)
        total_issues = sum(report.total_issues for report in self.accessibility_reports)
        avg_score = sum(report.score for report in self.accessibility_reports) / total_pages if total_pages > 0 else 0
        
        # Aggregate issues by severity and level
        severity_counts = {'critical': 0, 'serious': 0, 'moderate': 0, 'minor': 0}
        level_counts = {'A': 0, 'AA': 0, 'AAA': 0}
        
        for report in self.accessibility_reports:
            for severity, count in report.issues_by_severity.items():
                severity_counts[severity] += count
            for level, count in report.issues_by_level.items():
                level_counts[level] += count
        
        # Find pages with most issues
        worst_pages = sorted(self.accessibility_reports, key=lambda r: r.total_issues, reverse=True)[:10]
        
        # Generate summary
        summary = {
            'scan_info': {
                'timestamp': timestamp,
                'total_pages_scanned': total_pages,
                'wcag_level': 'AA',
                'average_score': round(avg_score, 1)
            },
            'overall_statistics': {
                'total_issues_found': total_issues,
                'issues_by_severity': severity_counts,
                'issues_by_wcag_level': level_counts
            },
            'pages_needing_attention': [
                {
                    'url': page.url,
                    'title': page.title,
                    'issues': page.total_issues,
                    'score': page.score
                }
                for page in worst_pages
            ],
            'recommendations': self._generate_recommendations(severity_counts)
        }
        
        # Save summary
        summary_file = output_path / f"accessibility_summary_{timestamp}.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, default=str)
        
        # Also save as readable text report
        text_file = output_path / f"accessibility_report_{timestamp}.txt"
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write("WCAG 2.1 Level AA Accessibility Report\n")
            f.write("=" * 50 + "\n\n")
            
            f.write(f"Scan Date: {timestamp}\n")
            f.write(f"Total Pages Scanned: {total_pages}\n")
            f.write(f"Total Issues Found: {total_issues}\n")
            f.write(f"Average Accessibility Score: {avg_score:.1f}/100\n\n")
            
            f.write("Issues by Severity:\n")
            for severity, count in severity_counts.items():
                f.write(f"  {severity.title()}: {count}\n")
            
            f.write("\nIssues by WCAG Level:\n")
            for level, count in level_counts.items():
                f.write(f"  Level {level}: {count}\n")
            
            f.write("\nTop Pages Needing Attention:\n")
            for i, page in enumerate(worst_pages, 1):
                f.write(f"  {i}. {page.url}\n")
                f.write(f"     Issues: {page.total_issues}, Score: {page.score:.1f}/100\n")
            
            f.write("\nRecommendations:\n")
            for rec in summary['recommendations']:
                f.write(f"  • {rec}\n")
        
        self.logger.info(f"Accessibility summary saved to {summary_file}")
    
    def _generate_recommendations(self, severity_counts: Dict[str, int]) -> List[str]:
        """Generate recommendations based on issue distribution"""
        recommendations = []
        
        if severity_counts['critical'] > 0:
            recommendations.append("Address critical issues first - these create complete barriers to access")
        
        if severity_counts['serious'] > 5:
            recommendations.append("Focus on serious issues - these significantly impact user experience")
        
        if severity_counts['moderate'] > 10:
            recommendations.append("Review moderate issues - these create difficulties for some users")
        
        recommendations.extend([
            "Implement alt text for all meaningful images",
            "Ensure proper heading structure (single H1, no skipped levels)",
            "Add descriptive labels to all form inputs",
            "Test keyboard navigation and focus indicators",
            "Verify color contrast meets WCAG AA standards (4.5:1 for normal text)"
        ])
        
        return recommendations

async def main():
    """Example usage"""
    crawler = AsyncWebCrawler()
    
    # Example: crawl single site
    # pages = await crawler.crawl_single_site("https://www.example-college.edu")
    # await crawler.save_results(pages)
    
    # Example: crawl all platforms
    # results = await crawler.crawl_platforms()
    # await crawler.save_results(results)

if __name__ == "__main__":
    asyncio.run(main())
