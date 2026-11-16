#!/usr/bin/env python3
"""
Database-driven backend server for accessibility dashboard - Database Driven
"""

import os
import sys
import json
from typing import List, Dict, Any, Optional
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.sql import func
import uvicorn

# Add src directory to Python path
sys.path.append('/app/src')

app = FastAPI(title="Accessibility Dashboard API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://10.47.100.6:3000", 
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AccessibilityIssueDetail(BaseModel):
    rule_id: str
    rule_title: str
    description: str
    wcag_level: str
    severity: str
    element: str
    element_type: str
    line_number: Optional[int] = None
    recommendation: str

class PageSummary(BaseModel):
    url: str
    title: str
    issue_count: int
    score: float
    content_type: str
    wcag_compliant: Optional[bool] = None
    platform: str = ""
    accessibility_issues: List[AccessibilityIssueDetail] = []
    crawl_timestamp: Optional[str] = None
    source_page: Optional[str] = None
    pdf_analysis: Optional[Dict[str, Any]] = None
    is_archived: bool = False

def get_db_session():
    """Get database session"""
    try:
        import sys
        sys.path.append('/app/src')
        from database import get_db_session as db_get_session
        return db_get_session()
    except Exception as e:
        print(f"Database connection failed: {e}")
        return None

@app.get("/")
async def root():
    return {"message": "Accessibility Dashboard API - Database Driven"}

@app.get("/api/latest-results")
async def get_latest_results():
    """Get latest crawl results from database"""
    try:
        session = get_db_session()
        if not session:
            # Fallback to JSON files if database is not available
            return await get_latest_results_from_files()
        
        from database import Site, Page, AccessibilityIssue
        
        # Query all pages with their sites
        pages = session.query(Page).join(Site).all()
        
        # Create page summaries
        summaries = []
        for page in pages:
            # Get platform from site relationship
            platform = page.site.platform if page.site and page.site.platform else ""
            
            # Get accessibility issues
            issues = []
            page_issues = session.query(AccessibilityIssue).filter(AccessibilityIssue.page_id == page.id).all()
            if page_issues:
                for issue in page_issues:
                    issues.append(AccessibilityIssueDetail(
                        rule_id=issue.rule_id or "",
                        rule_title=issue.rule_title or "",
                        description=issue.description or "",
                        wcag_level=issue.wcag_level or "",
                        severity=issue.severity or "",
                        element=issue.element or "",
                        element_type=issue.element_type or "",
                        line_number=issue.line_number,
                        recommendation=issue.recommendation or ""
                    ))
            
            # Handle PDFs differently - prioritize PDF-specific analysis
            if page.content_type == 'application/pdf':
                # Use PDF-specific analysis if available
                if page.pdf_analysis:
                    issue_count = page.pdf_analysis.get('issue_count', 0)
                    score = page.pdf_analysis.get('accessibility_score', 100)
                    wcag_compliant = page.pdf_analysis.get('wcag_compliant', None)
                    
                    # Convert PDF analysis issues to the expected format for modal
                    pdf_issues = []
                    if page.pdf_analysis.get('issues'):
                        for issue in page.pdf_analysis['issues']:
                            pdf_issues.append(AccessibilityIssueDetail(
                                rule_id=issue.get('rule_id', ''),
                                rule_title=issue.get('rule_title', ''),
                                description=issue.get('description', ''),
                                wcag_level=issue.get('wcag_level', 'PDF'),
                                severity=issue.get('severity', ''),
                                element=issue.get('element', ''),
                                element_type=issue.get('element_type', 'PDF'),
                                line_number=issue.get('line_number'),
                                recommendation=issue.get('recommendation', '')
                            ))
                    issues = pdf_issues
                else:
                    # Fallback to database analysis for PDFs without specific analysis
                    has_accessibility_analysis = page.accessibility_score is not None and page.accessibility_score != 100
                    
                    if has_accessibility_analysis:
                        issue_count = len(issues)
                        score = page.accessibility_score
                        wcag_compliant = issue_count == 0
                    else:
                        # Unanalyzed PDF - show as neutral
                        issue_count = 0
                        score = 100
                        wcag_compliant = None
                        issues = []  # Don't show page issues for unanalyzed PDFs
            else:
                issue_count = len(issues)
                wcag_compliant = issue_count == 0
            
            summaries.append(PageSummary(
                url=page.url,
                title=page.title or "",
                issue_count=issue_count,
                score=score if page.content_type == 'application/pdf' else (page.accessibility_score or 100),
                content_type=page.content_type or "text/html",
                wcag_compliant=wcag_compliant,
                platform=platform,
                accessibility_issues=issues,
                crawl_timestamp=page.crawl_timestamp.isoformat() if page.crawl_timestamp else None,
                source_page=page.source_page,
                pdf_analysis=page.pdf_analysis,
                is_archived=page.is_archived or False
            ))
        
        # Sort pages alphabetically by URL
        summaries.sort(key=lambda x: x.url.lower())
        
        # Calculate summary
        total_pages = len(summaries)
        total_issues = sum(p.issue_count for p in summaries)

        # Aggregate issues by severity and category
        from database import AccessibilityIssue

        severity_counts: Dict[str, int] = {
            "critical": 0,
            "serious": 0,
            "moderate": 0,
            "minor": 0,
        }
        category_counts: Dict[str, int] = {}

        issue_query = session.query(AccessibilityIssue.severity, AccessibilityIssue.element_type)
        for severity, element_type in issue_query:
            if severity:
                key = severity.lower()
                if key in severity_counts:
                    severity_counts[key] += 1
            if element_type:
                category_counts[element_type] = category_counts.get(element_type, 0) + 1

        # Average accessibility score across pages that have a defined score
        avg_score = session.query(func.avg(Page.accessibility_score)).scalar()
        average_score = float(avg_score) if avg_score is not None else 100.0

        session.close()
        
        return {
            "pages": [s.dict() for s in summaries],
            "summary": {
                "total_pages": total_pages,
                "total_issues": total_issues,
                "average_score": average_score,
                "critical_issues": severity_counts["critical"],
                "serious_issues": severity_counts["serious"],
                "moderate_issues": severity_counts["moderate"],
                "minor_issues": severity_counts["minor"],
                "issues_by_category": category_counts,
            },
        }
        
    except Exception as e:
        print(f"Error reading from database: {e}")
        # Fallback to JSON files
        return await get_latest_results_from_files()

async def get_latest_results_from_files():
    """Fallback method to get results from JSON files"""
    try:
        output_dir = Path("../output")
        
        # First try to get the real-time latest file
        latest_file = output_dir / "crawled_pages_latest.json"
        
        if latest_file.exists():
            # Use the real-time file
            data_file = latest_file
        else:
            # Fallback to timestamped files
            json_files = list(output_dir.glob("crawled_pages_*.json"))
            if not json_files:
                return {"pages": [], "summary": {"total_pages": 0, "total_issues": 0}}
            # Get the most recent file
            data_file = max(json_files, key=os.path.getctime)
        
        with open(data_file, 'r') as f:
            crawled_data = json.load(f)
        
        # Create page summaries
        summaries = []
        for page in crawled_data:
            content_type = page.get('content_type', 'text/html')
            
            if content_type == 'application/pdf':
                # Check if this PDF has been analyzed (has pdf_analysis metadata or specific PDF issues)
                has_pdf_analysis = (
                    page.get('pdf_analysis') or 
                    (page.get('accessibility_issues') and 
                     any(issue.get('rule') == 'Tagged PDF' for issue in page.get('accessibility_issues', [])))
                )
                
                if has_pdf_analysis:
                    issue_count = page.get('issue_count', 0)
                    score = page.get('accessibility_score', 100)
                    wcag_compliant = page.get('wcag_compliant', False)
                else:
                    # Unanalyzed PDF - show as neutral
                    issue_count = 0
                    score = 100
                    wcag_compliant = None
            else:
                issue_count = page.get('issue_count', 0)
                score = page.get('accessibility_score', 100)
                wcag_compliant = issue_count == 0
            
            summaries.append(PageSummary(
                url=page.get('url', ''),
                title=page.get('title', ''),
                issue_count=issue_count,
                score=score,
                content_type=content_type,
                wcag_compliant=wcag_compliant,
                platform=page.get('platform', ''),
                accessibility_issues=[],
                crawl_timestamp=page.get('crawl_timestamp'),
                source_page=page.get('source_page'),
                is_archived=page.get('is_archived', False)
            ))
        
        # Calculate summary
        total_pages = len(summaries)
        total_issues = sum(p.issue_count for p in summaries)
        
        return {
            "pages": [s.dict() for s in summaries],
            "summary": {
                "total_pages": total_pages,
                "total_issues": total_issues
            }
        }
        
    except Exception as e:
        print(f"Error loading latest results from files: {e}")
        return {"pages": [], "summary": {"total_pages": 0, "total_issues": 0}}

@app.get("/api/page-issues/{url:path}")
async def get_page_issues(url: str):
    """Get detailed accessibility issues for a specific page"""
    try:
        session = get_db_session()
        if not session:
            return {"issues": [], "error": "Database not available"}
        
        from database import Site, Page
        
        # Find the page
        page = session.query(Page).join(Site).filter(Page.url == url).first()
        
        if not page:
            return {"issues": [], "error": "Page not found"}
        
        # Get platform from site relationship
        platform = page.site.platform if page.site and page.site.platform else ""
        
        # Get accessibility issues
        issues = []
        if page.accessibility_issues:
            for issue in page.accessibility_issues:
                issues.append({
                    "rule_id": issue.rule_id or "",
                    "rule_title": issue.rule_title or "",
                    "description": issue.description or "",
                    "wcag_level": issue.wcag_level or "",
                    "severity": issue.severity or "",
                    "element": issue.element or "",
                    "element_type": issue.element_type or "",
                    "line_number": issue.line_number,
                    "recommendation": issue.recommendation or ""
                })
        
        session.close()
        
        return {
            "url": page.url,
            "title": page.title or "",
            "platform": platform,
            "issue_count": len(issues),
            "score": page.accessibility_score or 100,
            "issues": issues
        }
        
    except Exception as e:
        print(f"Error getting page issues: {e}")
        return {"issues": [], "error": str(e)}

@app.get("/health")
async def health_check():
    """Health check that includes database status"""
    try:
        session = get_db_session()
        if session:
            session.close()
            return {"status": "healthy", "database": "connected"}
        else:
            return {"status": "healthy", "database": "disconnected"}
    except Exception as e:
        return {"status": "healthy", "database": "error", "error": str(e)}

# PDF Analysis endpoints
@app.get("/api/pdf-usage")
async def get_pdf_usage():
    """Get current PDF API usage statistics"""
    # Using local pypdf analysis - no API limits
    return {
        "can_make_call": True,
        "monthly_usage": 0,
        "monthly_limit": "unlimited",
        "analysis_method": "pypdf Basic Analysis",
        "message": "Basic PDF analysis available - no API limits"
    }

@app.post("/api/analyze-pdf")
async def analyze_pdf(request: dict):
    """Analyze a PDF for accessibility issues"""
    try:
        pdf_url = request.get("pdf_url")
        if not pdf_url:
            return {"error": "PDF URL is required"}
        
        import sys
        sys.path.append('/app/src')
        import aiohttp
        
        # Download PDF content
        async with aiohttp.ClientSession() as session:
            async with session.get(pdf_url) as response:
                if response.status != 200:
                    return {"error": f"Failed to download PDF: HTTP {response.status}"}
                pdf_content = await response.read()
        
        # Basic PDF analysis with pypdf
        import pypdf
        import io
        
        try:
            pdf_file = io.BytesIO(pdf_content)
            pdf_reader = pypdf.PdfReader(pdf_file)
            
            # Extract basic PDF info
            num_pages = len(pdf_reader.pages)
            is_tagged = False
            
            # Check if PDF is tagged (basic check)
            try:
                if '/StructTreeRoot' in pdf_reader.trailer['/Root']:
                    is_tagged = True
            except:
                pass
            
            # Generate basic accessibility report
            issues = []
            issue_count = 0
            
            if not is_tagged:
                issues.append({
                    "rule": "Tagged PDF",
                    "description": "PDF is not tagged for accessibility",
                    "severity": "Critical",
                    "element": "Document",
                    "recommendation": "Use Adobe Acrobat to add tags to the PDF for screen reader compatibility"
                })
                issue_count += 1
            
            # Calculate score (simple scoring)
            accessibility_score = max(100 - (issue_count * 20), 0)
            
            result = {
                "url": pdf_url,
                "issue_count": issue_count,
                "accessibility_score": accessibility_score,
                "wcag_compliant": issue_count == 0,
                "issues": issues,
                "metadata": {
                    "num_pages": num_pages,
                    "is_tagged": is_tagged,
                    "file_size": len(pdf_content),
                    "analysis_method": "pypdf Basic Analysis"
                }
            }
            
            return result
            
        except Exception as pdf_error:
            # If PDF analysis fails, return basic error info
            return {
                "url": pdf_url,
                "issue_count": 1,
                "accessibility_score": 0,
                "wcag_compliant": False,
                "issues": [{
                    "rule": "PDF Analysis Error",
                    "description": f"Failed to analyze PDF: {str(pdf_error)}",
                    "severity": "Critical",
                    "element": "Document",
                    "recommendation": "Check if the PDF is valid and accessible"
                }],
                "metadata": {
                    "analysis_method": "Error",
                    "error": str(pdf_error)
                    }
                }
        
    except Exception as e:
        return {"error": str(e), "issues": []}

@app.post("/api/save-pdf-analysis")
async def save_pdf_analysis(request: dict):
    """Save PDF analysis results to database"""
    try:
        pdf_url = request.get("pdf_url")
        analysis_result = request.get("analysis_result")
        
        if not pdf_url or not analysis_result:
            return {"error": "PDF URL and analysis result are required"}
        
        session = get_db_session()
        if not session:
            return {"error": "Database connection failed"}
        
        try:
            import sys
            sys.path.append('/app/src')
            from database import Page
            
            # Find the PDF page in database
            page = session.query(Page).filter(Page.url == pdf_url).first()
            if not page:
                return {"error": "PDF page not found in database"}
            
            # Update the page with PDF analysis results
            page.issue_count = analysis_result.get("issue_count", 0)
            page.accessibility_score = analysis_result.get("accessibility_score", 100)
            page.wcag_compliant = analysis_result.get("issue_count", 0) == 0
            
            # Store the full analysis result in pdf_analysis field
            page.pdf_analysis = analysis_result
            
            # Remove existing accessibility issues for this page
            from database import AccessibilityIssue
            session.query(AccessibilityIssue).filter(AccessibilityIssue.page_id == page.id).delete()
            
            # Create accessibility issues from PDF analysis
            issues = analysis_result.get("issues", [])
            for issue_data in issues:
                issue = AccessibilityIssue(
                    page_id=page.id,
                    rule_id=issue_data.get("rule", ""),
                    rule_title=issue_data.get("rule", ""),
                    description=issue_data.get("description", ""),
                    wcag_level="PDF",  # PDF-specific issues
                    severity=issue_data.get("severity", ""),
                    element=issue_data.get("element", ""),
                    element_type="PDF",
                    line_number=None,
                    recommendation=issue_data.get("recommendation", "")
                )
                session.add(issue)
            
            session.commit()
            
            return {"success": True, "message": "PDF analysis saved successfully"}
            
        finally:
            session.close()
            
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/export-all-pdf-data")
async def export_all_pdf_data():
    """Export PDF accessibility data for ALL platforms as CSV (detailed format).

    This is similar to /api/export-pdf-data/{platform_name} but for all PDFs.
    To keep it fast and avoid timeouts behind nginx, we avoid extra per-PDF
    database lookups for PageLink and simply leave link_text empty.
    """
    try:
        session = get_db_session()
        if not session:
            return {"error": "Database connection failed"}

        try:
            import sys
            sys.path.append('/app/src')
            from database import Page
            import csv
            import io
            from datetime import datetime

            # Get all PDF pages across all platforms
            pdf_pages = session.query(Page).filter(
                Page.content_type == 'application/pdf'
            ).all()

            if not pdf_pages:
                return {"error": "No PDFs found"}

            # Create CSV content
            output = io.StringIO()
            writer = csv.writer(output)

            # Write comprehensive header matching the legacy detailed PDF export
            # plus a hostname column derived from the PDF URL
            header = [
                'url', 'hostname', 'downloaded_size_bytes', 'downloaded_size_human', 'download_timestamp',
                'title', 'author', 'subject', 'keywords', 'creator', 'producer',
                'creation_date', 'modification_date', 'page_count', 'is_encrypted',
                'has_tags', 'has_title', 'has_language', 'language', 'has_outline',
                'outline_items', 'is_tagged_pdf', 'has_form_fields', 'has_annotations',
                'annotation_count', 'image_count', 'text_content', 'accessibility_issues_count',
                'accessibility_issues', 'has_tables', 'table_count', 'tables_with_headers',
                'images_with_alt_text', 'total_images', 'color_contrast_issues',
                'reading_order_valid', 'has_scanned_content', 'ocr_needed', 'error',
                'original_PDF_URL', 'analysis_method', 'issue_count', 'score',
                'source_page', 'is_archived', 'link_text'
            ]
            writer.writerow(header)

            # One row per PDF, aggregating issues into a single string
            for page in pdf_pages:
                pdf_analysis = page.pdf_analysis or {}
                metadata = pdf_analysis.get('metadata', {}) or {}
                features = pdf_analysis.get('accessibility_features', {}) or {}
                issues = pdf_analysis.get('issues', []) or []

                # Convert issues list to a human-readable string
                accessibility_issues_str = '; '.join([
                    f"{issue.get('rule', issue.get('rule_id', ''))}: {issue.get('description', '')}"
                    for issue in issues
                ]) if issues else ''

                downloaded_size_bytes = metadata.get('downloaded_size_bytes', metadata.get('file_size', ''))
                downloaded_size_human = metadata.get('downloaded_size_human', '')
                download_timestamp = metadata.get('download_timestamp', pdf_analysis.get('analysis_timestamp', ''))

                page_count = features.get('num_pages', 0)
                is_encrypted = features.get('is_encrypted', False)
                has_tags = features.get('has_tags', features.get('is_tagged_pdf', False))
                is_tagged_pdf = features.get('is_tagged_pdf', False)
                has_title = features.get('has_title', False)
                has_language = features.get('has_language', False)
                language = features.get('language', '')
                has_outline = features.get('has_outline', False)
                outline_items = features.get('outline_items', 0)
                has_form_fields = features.get('has_form_fields', False)
                has_annotations = features.get('has_annotations', False)
                annotation_count = features.get('annotation_count', 0)
                image_count = features.get('image_count', features.get('total_images', 0))
                text_content = features.get('text_content', False)
                has_tables = features.get('has_tables', False)
                table_count = features.get('table_count', 0)
                tables_with_headers = features.get('tables_with_headers', 0)
                images_with_alt_text = features.get('images_with_alt_text', 0)
                total_images = features.get('total_images', 0)
                color_contrast_issues = features.get('color_contrast_issues', False)
                reading_order_valid = features.get('reading_order_valid', True)
                has_scanned_content = features.get('has_scanned_content', False)
                ocr_needed = features.get('ocr_needed', False)

                error = pdf_analysis.get('error', '')
                analysis_method = pdf_analysis.get('analysis_method', metadata.get('analysis_method', 'pypdf Local Analysis'))
                issue_count = pdf_analysis.get('issue_count', page.issue_count or 0)
                score = pdf_analysis.get('score', page.accessibility_score or 100)

                # Derive hostname from the PDF URL for easier filtering/grouping
                parsed = urlparse(page.url or "")
                hostname = parsed.hostname or ""

                # We skip resolving link_text here for performance; leave it empty
                link_text = ''

                row = [
                    page.url,
                    hostname,
                    downloaded_size_bytes,
                    downloaded_size_human,
                    download_timestamp,
                    metadata.get('title', '') or (page.title or ''),
                    metadata.get('author', ''),
                    metadata.get('subject', ''),
                    metadata.get('keywords', ''),
                    metadata.get('creator', ''),
                    metadata.get('producer', ''),
                    metadata.get('creation_date', ''),
                    metadata.get('modification_date', ''),
                    page_count,
                    is_encrypted,
                    has_tags,
                    has_title,
                    has_language,
                    language,
                    has_outline,
                    outline_items,
                    is_tagged_pdf,
                    has_form_fields,
                    has_annotations,
                    annotation_count,
                    image_count,
                    text_content,
                    len(issues),
                    accessibility_issues_str,
                    has_tables,
                    table_count,
                    tables_with_headers,
                    images_with_alt_text,
                    total_images,
                    color_contrast_issues,
                    reading_order_valid,
                    has_scanned_content,
                    ocr_needed,
                    error,
                    page.url,  # original_PDF_URL
                    analysis_method,
                    issue_count,
                    score,
                    page.source_page or '',
                    page.is_archived or False,
                    link_text
                ]
                writer.writerow(row)

            # Generate filename
            filename = f"pdf_accessibility_ALL_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            # Return CSV file
            csv_content = output.getvalue()
            output.close()

            from fastapi.responses import Response
            return Response(
                content=csv_content,
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )

        finally:
            session.close()

    except Exception as e:
        return {"error": str(e)}

@app.get("/api/export-pdf-data/{platform_name}")
async def export_pdf_data(platform_name: str):
    """Export PDF accessibility data for a specific platform as CSV (detailed format)"""
    try:
        session = get_db_session()
        if not session:
            return {"error": "Database connection failed"}
        
        try:
            import sys
            sys.path.append('/app/src')
            from database import Page, AccessibilityIssue, Site, PageLink
            import csv
            import io
            from datetime import datetime
            
            # Get all PDF pages for this platform
            pdf_pages = session.query(Page).filter(
                Page.content_type == 'application/pdf'
            ).join(Site).filter(Site.platform == platform_name).all()
            
            if not pdf_pages:
                return {"error": f"No PDFs found for platform '{platform_name}'"}
            
            # Create CSV content
            output = io.StringIO()
            writer = csv.writer(output)

            # Write comprehensive header matching the legacy detailed PDF export
            header = [
                'url', 'downloaded_size_bytes', 'downloaded_size_human', 'download_timestamp',
                'title', 'author', 'subject', 'keywords', 'creator', 'producer',
                'creation_date', 'modification_date', 'page_count', 'is_encrypted',
                'has_tags', 'has_title', 'has_language', 'language', 'has_outline',
                'outline_items', 'is_tagged_pdf', 'has_form_fields', 'has_annotations',
                'annotation_count', 'image_count', 'text_content', 'accessibility_issues_count',
                'accessibility_issues', 'has_tables', 'table_count', 'tables_with_headers',
                'images_with_alt_text', 'total_images', 'color_contrast_issues',
                'reading_order_valid', 'has_scanned_content', 'ocr_needed', 'error',
                'original_PDF_URL', 'analysis_method', 'issue_count', 'score',
                'source_page', 'is_archived', 'link_text'
            ]
            writer.writerow(header)

            # One row per PDF, aggregating issues into a single string
            for page in pdf_pages:
                pdf_analysis = page.pdf_analysis or {}
                metadata = pdf_analysis.get('metadata', {}) or {}
                features = pdf_analysis.get('accessibility_features', {}) or {}
                issues = pdf_analysis.get('issues', []) or []

                # Convert issues list to a human-readable string
                accessibility_issues_str = '; '.join([
                    f"{issue.get('rule', issue.get('rule_id', ''))}: {issue.get('description', '')}"
                    for issue in issues
                ]) if issues else ''

                downloaded_size_bytes = metadata.get('downloaded_size_bytes', metadata.get('file_size', ''))
                downloaded_size_human = metadata.get('downloaded_size_human', '')
                download_timestamp = metadata.get('download_timestamp', pdf_analysis.get('analysis_timestamp', ''))

                page_count = features.get('num_pages', 0)
                is_encrypted = features.get('is_encrypted', False)
                has_tags = features.get('has_tags', features.get('is_tagged_pdf', False))
                is_tagged_pdf = features.get('is_tagged_pdf', False)
                has_title = features.get('has_title', False)
                has_language = features.get('has_language', False)
                language = features.get('language', '')
                has_outline = features.get('has_outline', False)
                outline_items = features.get('outline_items', 0)
                has_form_fields = features.get('has_form_fields', False)
                has_annotations = features.get('has_annotations', False)
                annotation_count = features.get('annotation_count', 0)
                image_count = features.get('image_count', features.get('total_images', 0))
                text_content = features.get('text_content', False)
                has_tables = features.get('has_tables', False)
                table_count = features.get('table_count', 0)
                tables_with_headers = features.get('tables_with_headers', 0)
                images_with_alt_text = features.get('images_with_alt_text', 0)
                total_images = features.get('total_images', 0)
                color_contrast_issues = features.get('color_contrast_issues', False)
                reading_order_valid = features.get('reading_order_valid', True)
                has_scanned_content = features.get('has_scanned_content', False)
                ocr_needed = features.get('ocr_needed', False)

                error = pdf_analysis.get('error', '')
                analysis_method = pdf_analysis.get('analysis_method', metadata.get('analysis_method', 'pypdf Local Analysis'))
                issue_count = pdf_analysis.get('issue_count', page.issue_count or 0)
                score = pdf_analysis.get('score', page.accessibility_score or 100)

                # Derive link_text: anchor text from the source HTML page that links to this PDF
                link_text = ''
                if page.source_page:
                    try:
                        source_page = session.query(Page).filter(Page.url == page.source_page).first()
                        if source_page:
                            link_rows = session.query(PageLink).filter(
                                PageLink.from_page_id == source_page.id,
                                PageLink.to_url == page.url
                            ).all()
                            if link_rows:
                                # Join distinct non-empty link texts in case there are multiple links
                                texts = sorted({(l.link_text or '').strip() for l in link_rows if (l.link_text or '').strip()})
                                link_text = '; '.join(texts)
                    except Exception as link_lookup_error:
                        # Don't fail export if link lookup has issues
                        print(f"Warning: failed to resolve link_text for {page.url}: {link_lookup_error}")

                row = [
                    page.url,
                    downloaded_size_bytes,
                    downloaded_size_human,
                    download_timestamp,
                    metadata.get('title', '') or (page.title or ''),
                    metadata.get('author', ''),
                    metadata.get('subject', ''),
                    metadata.get('keywords', ''),
                    metadata.get('creator', ''),
                    metadata.get('producer', ''),
                    metadata.get('creation_date', ''),
                    metadata.get('modification_date', ''),
                    page_count,
                    is_encrypted,
                    has_tags,
                    has_title,
                    has_language,
                    language,
                    has_outline,
                    outline_items,
                    is_tagged_pdf,
                    has_form_fields,
                    has_annotations,
                    annotation_count,
                    image_count,
                    text_content,
                    len(issues),
                    accessibility_issues_str,
                    has_tables,
                    table_count,
                    tables_with_headers,
                    images_with_alt_text,
                    total_images,
                    color_contrast_issues,
                    reading_order_valid,
                    has_scanned_content,
                    ocr_needed,
                    error,
                    page.url,  # original_PDF_URL
                    analysis_method,
                    issue_count,
                    score,
                    page.source_page or '',
                    page.is_archived or False,
                    link_text  # link_text from PageLink if available
                ]
                writer.writerow(row)
            
            # Generate filename
            filename = f"pdf_accessibility_{platform_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            # Return CSV file
            csv_content = output.getvalue()
            output.close()
            
            from fastapi.responses import Response
            return Response(
                content=csv_content,
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
            
        finally:
            session.close()
            
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/export-pdf-summary/{platform_name}")
async def export_pdf_summary(platform_name: str):
    """Export PDF accessibility summary data for a specific platform as CSV (one row per PDF)"""
    try:
        session = get_db_session()
        if not session:
            return {"error": "Database connection failed"}
        
        try:
            import sys
            sys.path.append('/app/src')
            from database import Page, AccessibilityIssue, Site
            import csv
            import io
            from datetime import datetime
            
            # Get all PDF pages for this platform with site information
            pdf_pages = session.query(Page, Site).filter(
                Page.content_type == 'application/pdf'
            ).join(Site).filter(Site.platform == platform_name).all()
            
            if not pdf_pages:
                return {"error": f"No PDFs found for platform '{platform_name}'"}
            
            # Create CSV content
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            header = [
                'Site', 'PDF_URL', 'PDF_Title', 'Source_Page', 'Issue_Count',
                'Accessibility_Score', 'WCAG_Compliant', 'File_Size', 'Pages',
                'Is_Tagged', 'Analysis_Method', 'Critical_Issues', 'Moderate_Issues',
                'Serious_Issues', 'Total_Issues', 'Issues_Summary'
            ]
            writer.writerow(header)
            
            # Write data for each PDF (one row per PDF)
            for page, site in pdf_pages:
                # Extract PDF analysis metadata
                pdf_analysis = page.pdf_analysis or {}
                metadata = pdf_analysis.get('metadata', {})
                
                # Get issues from PDF analysis if available (Adobe results), otherwise from database
                pdf_issues = pdf_analysis.get('issues', [])
                
                # Use PDF analysis data if available, otherwise fall back to database fields
                analysis_method = metadata.get('analysis_method', 'Basic Analysis')
                issue_count = pdf_analysis.get('issue_count', page.issue_count or 0)
                accessibility_score = pdf_analysis.get('accessibility_score', page.accessibility_score or 100)
                wcag_compliant = pdf_analysis.get('wcag_compliant', page.wcag_compliant)
                
                # Count issues by severity
                critical_count = 0
                moderate_count = 0
                serious_count = 0
                issues_summary = []
                
                # Use PDF analysis issues if available, otherwise get from database
                issues_to_analyze = pdf_issues if pdf_issues else session.query(AccessibilityIssue).filter(
                    AccessibilityIssue.page_id == page.id
                ).all()
                
                for issue in issues_to_analyze:
                    if isinstance(issue, dict):
                        # Adobe analysis format
                        severity = issue.get('severity', '').lower()
                        rule_title = issue.get('rule_title', issue.get('rule', 'Unknown'))
                        description = issue.get('description', '')
                    else:
                        # Database format
                        severity = getattr(issue, 'severity', '').lower()
                        rule_title = getattr(issue, 'rule_id', 'Unknown')
                        description = getattr(issue, 'description', '')
                    
                    # Count by severity
                    if 'critical' in severity:
                        critical_count += 1
                    elif 'moderate' in severity:
                        moderate_count += 1
                    elif 'serious' in severity:
                        serious_count += 1
                    
                    # Add to summary (limit to first few issues to keep CSV readable)
                    if len(issues_summary) < 3:
                        issues_summary.append(f"{rule_title}: {description[:50]}...")
                
                # Create issues summary string
                issues_summary_str = '; '.join(issues_summary) if issues_summary else 'No issues found'
                
                # Write one row per PDF
                row = [
                    site.url,
                    page.url,
                    page.title,
                    page.source_page or '',
                    issue_count,
                    accessibility_score,
                    wcag_compliant,
                    metadata.get('file_size', page.content_length),
                    metadata.get('num_pages', 'Unknown'),
                    metadata.get('is_tagged', 'Unknown'),
                    analysis_method,
                    critical_count,
                    moderate_count,
                    serious_count,
                    issue_count,
                    issues_summary_str
                ]
                writer.writerow(row)
            
            # Generate filename
            filename = f"pdf_accessibility_summary_{platform_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            # Return CSV file
            csv_content = output.getvalue()
            output.close()
            
            from fastapi.responses import Response
            return Response(
                content=csv_content,
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
            
        finally:
            session.close()
            
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/export-all-pdf-summary")
async def export_all_pdf_summary():
    """Export PDF accessibility summary data for ALL platforms as CSV (one row per PDF)"""
    try:
        session = get_db_session()
        if not session:
            return {"error": "Database connection failed"}
        
        try:
            import sys
            sys.path.append('/app/src')
            from database import Page, AccessibilityIssue, Site
            import csv
            import io
            from datetime import datetime
            
            # Get all PDF pages from all platforms with site information
            pdf_pages = session.query(Page, Site).filter(
                Page.content_type == 'application/pdf'
            ).join(Site).all()
            
            if not pdf_pages:
                return {"error": "No PDFs found"}
            
            # Create CSV content
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            header = [
                'Site', 'PDF_URL', 'PDF_Title', 'Source_Page', 'Issue_Count',
                'Accessibility_Score', 'WCAG_Compliant', 'File_Size', 'Pages',
                'Is_Tagged', 'Analysis_Method', 'Critical_Issues', 'Moderate_Issues',
                'Serious_Issues', 'Total_Issues', 'Issues_Summary'
            ]
            writer.writerow(header)
            
            # Write data for each PDF (one row per PDF)
            for page, site in pdf_pages:
                # Extract PDF analysis metadata
                pdf_analysis = page.pdf_analysis or {}
                metadata = pdf_analysis.get('metadata', {})
                
                # Get issues from PDF analysis if available (Adobe results), otherwise from database
                pdf_issues = pdf_analysis.get('issues', [])
                
                # Use PDF analysis data if available, otherwise fall back to database fields
                analysis_method = metadata.get('analysis_method', 'Basic Analysis')
                issue_count = pdf_analysis.get('issue_count', page.issue_count or 0)
                accessibility_score = pdf_analysis.get('accessibility_score', page.accessibility_score or 100)
                wcag_compliant = pdf_analysis.get('wcag_compliant', page.wcag_compliant)
                
                # Count issues by severity
                critical_count = 0
                moderate_count = 0
                serious_count = 0
                issues_summary = []
                
                # Use PDF analysis issues if available, otherwise get from database
                issues_to_analyze = pdf_issues if pdf_issues else session.query(AccessibilityIssue).filter(
                    AccessibilityIssue.page_id == page.id
                ).all()
                
                for issue in issues_to_analyze:
                    if isinstance(issue, dict):
                        # Adobe analysis format
                        severity = issue.get('severity', '').lower()
                        rule_title = issue.get('rule_title', issue.get('rule', 'Unknown'))
                        description = issue.get('description', '')
                    else:
                        # Database format
                        severity = getattr(issue, 'severity', '').lower()
                        rule_title = getattr(issue, 'rule_id', 'Unknown')
                        description = getattr(issue, 'description', '')
                    
                    # Count by severity
                    if 'critical' in severity:
                        critical_count += 1
                    elif 'moderate' in severity:
                        moderate_count += 1
                    elif 'serious' in severity:
                        serious_count += 1
                    
                    # Add to summary (limit to first few issues to keep CSV readable)
                    if len(issues_summary) < 3:
                        issues_summary.append(f"{rule_title}: {description[:50]}...")
                
                # Create issues summary string
                issues_summary_str = '; '.join(issues_summary) if issues_summary else 'No issues found'
                
                # Write one row per PDF
                row = [
                    site.url,
                    page.url,
                    page.title,
                    page.source_page or '',
                    issue_count,
                    accessibility_score,
                    wcag_compliant,
                    metadata.get('file_size', page.content_length),
                    metadata.get('num_pages', 'Unknown'),
                    metadata.get('is_tagged', 'Unknown'),
                    analysis_method,
                    critical_count,
                    moderate_count,
                    serious_count,
                    issue_count,
                    issues_summary_str
                ]
                writer.writerow(row)
            
            # Generate filename
            filename = f"pdf_accessibility_summary_ALL_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            # Return CSV file
            csv_content = output.getvalue()
            output.close()
            
            from fastapi.responses import Response
            return Response(
                content=csv_content,
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
            
        finally:
            session.close()
            
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
