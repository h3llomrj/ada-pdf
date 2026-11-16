"""
Database connection and models for the accessibility crawler
"""
import os
import asyncio
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, BigInteger, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
import redis

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://ada_pdf_user:ada_pdf_password@localhost:5432/ada_pdf")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Create SQLAlchemy engine
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Redis connection
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

Base = declarative_base()

# Database Models
class Site(Base):
    __tablename__ = "sites"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False, unique=True)
    platform = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_crawled_at = Column(DateTime(timezone=True))
    
    # Relationships
    pages = relationship("Page", back_populates="site", cascade="all, delete-orphan")
    crawl_sessions = relationship("CrawlSession", back_populates="site")

class Page(Base):
    __tablename__ = "pages"
    
    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    url = Column(String(500), nullable=False)
    title = Column(Text)
    status_code = Column(Integer)
    content_type = Column(String(100))
    content_length = Column(BigInteger)
    html_content = Column(Text)
    crawl_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    platform = Column(String(100))
    site_name = Column(String(255))
    
    # Accessibility fields
    issue_count = Column(Integer, default=0)
    accessibility_score = Column(Integer, default=100)
    wcag_compliant = Column(Boolean, default=None)
    
    # PDF-specific fields
    pdf_analysis = Column(JSONB, default=None)
    
    # Source tracking
    source_page = Column(String(500), default=None)  # Page where this PDF was discovered
    
    # Archive tracking
    is_archived = Column(Boolean, default=False)  # Whether page/PDF has archive notice
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    site = relationship("Site", back_populates="pages")
    links = relationship("PageLink", back_populates="page", cascade="all, delete-orphan")
    images = relationship("PageImage", back_populates="page", cascade="all, delete-orphan")
    forms = relationship("PageForm", back_populates="page", cascade="all, delete-orphan")
    headings = relationship("PageHeading", back_populates="page", cascade="all, delete-orphan")
    accessibility_issues = relationship("AccessibilityIssue", back_populates="page", cascade="all, delete-orphan")

class PageLink(Base):
    __tablename__ = "page_links"
    
    id = Column(Integer, primary_key=True, index=True)
    from_page_id = Column(Integer, ForeignKey("pages.id"), nullable=False)
    to_url = Column(Text, nullable=False)
    link_text = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    page = relationship("Page", back_populates="links")

class PageImage(Base):
    __tablename__ = "page_images"
    
    id = Column(Integer, primary_key=True, index=True)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=False)
    src = Column(String(500), nullable=False)
    alt = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    page = relationship("Page", back_populates="images")

class PageForm(Base):
    __tablename__ = "page_forms"
    
    id = Column(Integer, primary_key=True, index=True)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=False)
    form_data = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    page = relationship("Page", back_populates="forms")

class PageHeading(Base):
    __tablename__ = "page_headings"
    
    id = Column(Integer, primary_key=True, index=True)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=False)
    heading_type = Column(String(10), nullable=False)  # h1, h2, h3, etc.
    heading_text = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    page = relationship("Page", back_populates="headings")

class AccessibilityIssue(Base):
    __tablename__ = "accessibility_issues"
    
    id = Column(Integer, primary_key=True, index=True)
    page_id = Column(Integer, ForeignKey("pages.id"), nullable=False)
    rule_id = Column(String(100), nullable=False)
    rule_title = Column(Text, nullable=False)
    description = Column(Text)
    wcag_level = Column(String(20))
    severity = Column(String(20))
    element = Column(Text)
    element_type = Column(String(50))
    recommendation = Column(Text)
    line_number = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    page = relationship("Page", back_populates="accessibility_issues")

class PDFAnalysisHistory(Base):
    __tablename__ = "pdf_analysis_history"
    
    id = Column(Integer, primary_key=True, index=True)
    pdf_url = Column(String(500), nullable=False)
    analysis_result = Column(JSONB, nullable=False)
    success = Column(Boolean, nullable=False)
    error_message = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class CrawlSession(Base):
    __tablename__ = "crawl_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    session_name = Column(String(255))
    platform = Column(String(100))
    start_time = Column(DateTime(timezone=True), server_default=func.now())
    end_time = Column(DateTime(timezone=True))
    pages_crawled = Column(Integer, default=0)
    total_issues = Column(Integer, default=0)
    status = Column(String(50), default='running')  # running, completed, failed
    config = Column(JSONB, default=None)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Foreign key to Site
    site_id = Column(Integer, ForeignKey("sites.id"))
    
    # Relationships
    site = relationship("Site", back_populates="crawl_sessions")

# Database dependency (for FastAPI)
def get_db() -> Session:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Database session function (for regular use)
def get_db_session() -> Session:
    """Get database session for regular use"""
    return SessionLocal()

# Database initialization
def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)

# CRUD operations
def create_or_update_site(session: Session, url: str, title: str = None, platform: str = None, site_name: str = None) -> Site:
    """Create or update a site record"""
    # Check if site exists
    site = session.query(Site).filter_by(url=url).first()
    
    if site:
        # Update existing site
        site.name = title or site.name
        site.platform = platform or site.platform
        site.updated_at = func.now()
    else:
        # Create new site
        site = Site(
            url=url,
            name=title or site_name or url,
            platform=platform
        )
        session.add(site)
    
    session.flush()  # Get the ID without committing
    return site

def create_or_update_page(session: Session, site_id: int, url: str, title: str = None, 
                         status_code: int = None, content_type: str = None, 
                         content_length: int = None, accessibility_score: int = None, 
                         issues: List[Dict] = None, source_page: str = None, is_archived: bool = False) -> Page:
    """Create or update a page record"""
    # Check if page exists
    page = session.query(Page).filter_by(url=url).first()
    
    if page:
        # Update existing page
        page.title = title or page.title
        page.status_code = status_code or page.status_code
        page.content_type = content_type or page.content_type
        page.content_length = content_length or page.content_length
        page.accessibility_score = accessibility_score or page.accessibility_score
        page.source_page = source_page or page.source_page
        page.is_archived = is_archived
        page.updated_at = func.now()
        
        # Handle accessibility issues
        if issues is not None:
            # Remove existing issues
            session.query(AccessibilityIssue).filter_by(page_id=page.id).delete()
            
            # Add new issues
            for issue_data in issues:
                # Convert enum values to strings
                wcag_level = issue_data.get('wcag_level', '')
                if hasattr(wcag_level, 'value'):
                    wcag_level = wcag_level.value
                
                severity = issue_data.get('severity', '')
                if hasattr(severity, 'value'):
                    severity = severity.value
                
                issue = AccessibilityIssue(
                    page_id=page.id,
                    rule_id=issue_data.get('rule_id', ''),
                    rule_title=issue_data.get('rule_title', ''),
                    description=issue_data.get('description', ''),
                    wcag_level=wcag_level,
                    severity=severity,
                    element=issue_data.get('element', ''),
                    element_type=issue_data.get('element_type', ''),
                    line_number=issue_data.get('line_number'),
                    recommendation=issue_data.get('recommendation', '')
                )
                session.add(issue)
    else:
        # Create new page
        page = Page(
            site_id=site_id,
            url=url,
            title=title,
            status_code=status_code,
            content_type=content_type,
            content_length=content_length,
            accessibility_score=accessibility_score,
            source_page=source_page,
            is_archived=is_archived
        )
        session.add(page)
        session.flush()  # Get the ID for creating issues
        
        # Add accessibility issues if provided
        if issues:
            for issue_data in issues:
                # Convert enum values to strings
                wcag_level = issue_data.get('wcag_level', '')
                if hasattr(wcag_level, 'value'):
                    wcag_level = wcag_level.value
                
                severity = issue_data.get('severity', '')
                if hasattr(severity, 'value'):
                    severity = severity.value
                
                issue = AccessibilityIssue(
                    page_id=page.id,
                    rule_id=issue_data.get('rule_id', ''),
                    rule_title=issue_data.get('rule_title', ''),
                    description=issue_data.get('description', ''),
                    wcag_level=wcag_level,
                    severity=severity,
                    element=issue_data.get('element', ''),
                    element_type=issue_data.get('element_type', ''),
                    line_number=issue_data.get('line_number'),
                    recommendation=issue_data.get('recommendation', '')
                )
                session.add(issue)
    
    session.flush()  # Get the ID without committing
    return page

# Database operations class
class DatabaseManager:
    """Database operations manager"""
    
    def __init__(self):
        self.db = SessionLocal()
    
    def close(self):
        """Close database connection"""
        self.db.close()
    
    # Site operations
    def get_or_create_site(self, name: str, url: str, platform: str = None) -> Site:
        """Get or create a site"""
        site = self.db.query(Site).filter(Site.url == url).first()
        if not site:
            site = Site(name=name, url=url, platform=platform)
            self.db.add(site)
            self.db.commit()
            self.db.refresh(site)
        return site
    
    # Page operations
    def create_or_update_page(self, page_data: Dict[str, Any]) -> Page:
        """Create or update a page"""
        # Get site
        site = self.get_or_create_site(
            page_data.get('site_name', 'Unknown'),
            page_data.get('url', '').split('/')[2] if page_data.get('url') else 'Unknown',
            page_data.get('platform')
        )
        
        # Check if page exists
        page = self.db.query(Page).filter(Page.url == page_data['url']).first()
        
        if page:
            # Update existing page
            for key, value in page_data.items():
                if hasattr(page, key):
                    setattr(page, key, value)
            page.updated_at = datetime.now()
        else:
            # Create new page
            page = Page(site_id=site.id, **page_data)
            self.db.add(page)
        
        self.db.commit()
        self.db.refresh(page)
        return page
    
    def update_page_pdf_analysis(self, page_url: str, analysis_result: Dict[str, Any]) -> Optional[Page]:
        """Update page with PDF analysis results"""
        page = self.db.query(Page).filter(Page.url == page_url).first()
        if page:
            page.pdf_analysis = analysis_result
            page.issue_count = analysis_result.get('total_issues', 0)
            page.accessibility_score = max(0, 100 - (analysis_result.get('total_issues', 0) * 5))
            page.wcag_compliant = analysis_result.get('wcag_compliant', False)
            page.updated_at = datetime.now()
            
            # Clear existing issues and add new ones
            self.db.query(AccessibilityIssue).filter(AccessibilityIssue.page_id == page.id).delete()
            
            for issue in analysis_result.get('issues', []):
                db_issue = AccessibilityIssue(
                    page_id=page.id,
                    rule_id=issue.get('rule_id'),
                    rule_title=issue.get('rule_title'),
                    description=issue.get('description'),
                    wcag_level=issue.get('wcag_level'),
                    severity=issue.get('severity'),
                    element=issue.get('element'),
                    element_type=issue.get('element_type'),
                    recommendation=issue.get('recommendation'),
                    line_number=issue.get('line_number')
                )
                self.db.add(db_issue)
            
            self.db.commit()
            self.db.refresh(page)
            
            # Record in PDF analysis history
            history = PDFAnalysisHistory(
                pdf_url=page_url,
                analysis_result=analysis_result,
                success=True
            )
            self.db.add(history)
            self.db.commit()
            
        return page
    
    def get_pages_with_filters(self, platform: str = None, content_type: str = None, 
                              wcag_compliant: bool = None, limit: int = 1000) -> List[Page]:
        """Get pages with optional filters"""
        query = self.db.query(Page)
        
        if platform:
            query = query.filter(Page.platform == platform)
        if content_type:
            query = query.filter(Page.content_type == content_type)
        if wcag_compliant is not None:
            query = query.filter(Page.wcag_compliant == wcag_compliant)
        
        return query.limit(limit).all()
    
    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Get dashboard summary statistics"""
        total_pages = self.db.query(Page).count()
        total_issues = self.db.query(func.sum(Page.issue_count)).scalar() or 0
        
        # Count by severity
        pages_with_issues = self.db.query(Page).filter(Page.issue_count > 0).all()
        critical_issues = sum(1 for p in pages_with_issues if p.issue_count > 10)
        serious_issues = sum(1 for p in pages_with_issues if 5 < p.issue_count <= 10)
        moderate_issues = sum(1 for p in pages_with_issues if 1 < p.issue_count <= 5)
        minor_issues = sum(1 for p in pages_with_issues if p.issue_count == 1)
        
        # WCAG compliance
        wcag_compliant_pages = self.db.query(Page).filter(Page.wcag_compliant == True).count()
        wcag_non_compliant_pages = self.db.query(Page).filter(Page.wcag_compliant == False).count()
        
        return {
            'total_pages': total_pages,
            'total_issues': total_issues,
            'critical_issues': critical_issues,
            'serious_issues': serious_issues,
            'moderate_issues': moderate_issues,
            'minor_issues': minor_issues,
            'wcag_compliant_pages': wcag_compliant_pages,
            'wcag_non_compliant_pages': wcag_non_compliant_pages
        }

# Redis operations
class CacheManager:
    """Redis cache operations manager"""
    
    def __init__(self):
        self.redis = redis_client
    
    def cache_pdf_analysis(self, pdf_url: str, result: Dict[str, Any], ttl: int = 3600):
        """Cache PDF analysis result"""
        key = f"pdf_analysis:{pdf_url}"
        self.redis.setex(key, ttl, json.dumps(result))
    
    def get_cached_pdf_analysis(self, pdf_url: str) -> Optional[Dict[str, Any]]:
        """Get cached PDF analysis result"""
        key = f"pdf_analysis:{pdf_url}"
        cached = self.redis.get(key)
        if cached:
            return json.loads(cached)
        return None
    
    def invalidate_cache(self, pattern: str):
        """Invalidate cache keys matching pattern"""
        keys = self.redis.keys(pattern)
        if keys:
            self.redis.delete(*keys)
