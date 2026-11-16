#!/usr/bin/env python3
"""
PDF Accessibility Checker using pypdf
Replaces Adobe PDF Services SDK with local pypdf-based analysis
"""

import io
import logging
from typing import Dict, Any, Optional
from datetime import datetime

try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False
    logging.warning("pypdf not available - PDF accessibility checking disabled")


def _format_bytes(num_bytes: int) -> str:
    """Format bytes in a human-readable form (e.g., 1.2 MB)."""
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"

class PDFAccessibilityChecker:
    """PDF accessibility checker using pypdf library"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        if not PYPDF_AVAILABLE:
            raise ImportError("pypdf is required for PDF accessibility checking")
    
    def analyze_pdf_accessibility(self, pdf_content: bytes, url: str = None) -> Dict[str, Any]:
        """
        Analyze PDF accessibility using pypdf
        
        Args:
            pdf_content: PDF file content as bytes
            url: Optional URL of the PDF for logging
            
        Returns:
            Dictionary containing accessibility analysis results
        """
        if not PYPDF_AVAILABLE:
            return {
                'error': 'pypdf not available',
                'issues': [],
                'issue_count': 0,
                'score': 0,
                'analysis_method': 'None'
            }
        
        analysis_result = {
            'url': url,
            'analysis_timestamp': datetime.now().isoformat(),
            'issues': [],
            'issue_count': 0,
            'score': 100,  # Start with perfect score
            'analysis_method': 'pypdf Local Analysis',
            'metadata': {},
            'accessibility_features': {
                'has_title': False,
                'has_language': False,
                'language': None,
                'is_tagged_pdf': False,
                'has_outline': False,
                'outline_items': 0,
                'has_form_fields': False,
                'has_annotations': False,
                'annotation_count': 0,
                'total_images': 0,
                'images_with_alt_text': 0,
                'has_tables': False,
                'table_count': 0,
                'tables_with_headers': 0,
                'text_content': False,
                'has_scanned_content': False,
                'ocr_needed': False,
                'num_pages': 0,
                'is_encrypted': False
            }
        }
        
        try:
            # File-level metadata (size + timestamp) used for CSV exports
            file_size = len(pdf_content)
            analysis_result['metadata'].update({
                'downloaded_size_bytes': file_size,
                'downloaded_size_human': _format_bytes(file_size),
                'download_timestamp': analysis_result['analysis_timestamp'],
                'file_size': file_size,
                # Mirror analysis_method here so older code that looks in metadata still works
                'analysis_method': analysis_result['analysis_method'],
            })

            pdf_stream = io.BytesIO(pdf_content)
            reader = pypdf.PdfReader(pdf_stream)
            
            # Basic info
            analysis_result['accessibility_features']['num_pages'] = len(reader.pages)
            analysis_result['accessibility_features']['is_encrypted'] = reader.is_encrypted
            
            if reader.is_encrypted:
                analysis_result['issues'].append({
                    'rule': 'Encrypted PDF',
                    'description': 'PDF is encrypted and may not be accessible to screen readers',
                    'recommendation': 'Provide an unencrypted version or ensure proper accessibility permissions',
                    'wcag_level': 'PDF/UA',
                    'severity': 'high',
                    'element_type': 'PDF'
                })
                analysis_result['score'] -= 20
            
            # Extract metadata
            if reader.metadata:
                meta = reader.metadata
                # Preserve any existing metadata entries (file size, timestamps, etc.)
                analysis_result['metadata'].update({
                    'title': meta.get('/Title', '').strip() or None,
                    'author': meta.get('/Author', '').strip() or None,
                    'subject': meta.get('/Subject', '').strip() or None,
                    'keywords': meta.get('/Keywords', '').strip() or None,
                    'creator': meta.get('/Creator', '').strip() or None,
                    'producer': meta.get('/Producer', '').strip() or None,
                    'creation_date': str(meta.get('/CreationDate', '')),
                    'modification_date': str(meta.get('/ModDate', ''))
                })
                
                # Check for title
                if meta.get('/Title') and meta.get('/Title', '').strip():
                    analysis_result['accessibility_features']['has_title'] = True
                else:
                    analysis_result['issues'].append({
                        'rule': 'Missing Document Title',
                        'description': 'PDF lacks a descriptive title in metadata',
                        'recommendation': 'Add a descriptive title to the PDF document properties',
                        'wcag_level': 'PDF/UA',
                        'severity': 'medium',
                        'element_type': 'PDF'
                    })
                    analysis_result['score'] -= 10
            
            # Check for tagged PDF (critical for accessibility)
            try:
                if '/StructTreeRoot' in reader.trailer['/Root']:
                    analysis_result['accessibility_features']['is_tagged_pdf'] = True
                    analysis_result['accessibility_features']['has_tags'] = True
                else:
                    analysis_result['issues'].append({
                        'rule': 'Tagged PDF',
                        'description': 'PDF is not tagged for accessibility',
                        'recommendation': 'Use Adobe Acrobat or other tools to add tags to the PDF for screen reader compatibility',
                        'wcag_level': 'PDF/UA',
                        'severity': 'high',
                        'element_type': 'PDF'
                    })
                    analysis_result['score'] -= 30
            except Exception:
                analysis_result['issues'].append({
                    'rule': 'Tagged PDF',
                    'description': 'Unable to verify if PDF is tagged for accessibility',
                    'recommendation': 'Verify PDF tagging status and ensure proper structure',
                    'wcag_level': 'PDF/UA',
                    'severity': 'high',
                    'element_type': 'PDF'
                })
                analysis_result['score'] -= 25
            
            # Check for language specification
            try:
                catalog = reader.trailer['/Root']
                if '/Lang' in catalog:
                    analysis_result['accessibility_features']['has_language'] = True
                    analysis_result['accessibility_features']['language'] = str(catalog['/Lang'])
                else:
                    analysis_result['issues'].append({
                        'rule': 'Language Specification',
                        'description': 'PDF does not specify the primary language',
                        'recommendation': 'Set the document language in PDF properties for better screen reader support',
                        'wcag_level': 'PDF/UA',
                        'severity': 'medium',
                        'element_type': 'PDF'
                    })
                    analysis_result['score'] -= 10
            except Exception:
                pass
            
            # Check for outline/bookmarks
            try:
                if reader.outline:
                    analysis_result['accessibility_features']['has_outline'] = True
                    analysis_result['accessibility_features']['outline_items'] = len(reader.outline)
            except Exception:
                pass
            
            # Check for form fields
            try:
                if '/AcroForm' in catalog and catalog['/AcroForm']:
                    analysis_result['accessibility_features']['has_form_fields'] = True
            except Exception:
                pass
            
            # Enhanced content analysis
            total_images = 0
            images_with_alt = 0
            table_count = 0
            tables_with_headers = 0
            has_text = False
            scanned_content = False
            
            for page_num, page in enumerate(reader.pages):
                try:
                    page_text = page.extract_text().strip()
                    
                    # Check for text content
                    if page_text:
                        has_text = True
                        # Simple heuristic for scanned content
                        if len(page_text) < 50 and total_images > 0:
                            scanned_content = True
                    
                    # Enhanced image analysis
                    if '/Resources' in page and '/XObject' in page['/Resources']:
                        xobjects = page['/Resources']['/XObject']
                        for obj_name in xobjects:
                            obj = xobjects[obj_name]
                            if obj.get('/Subtype') == '/Image':
                                total_images += 1
                                # In tagged PDFs, assume images have alt text (simplified)
                                if analysis_result['accessibility_features']['is_tagged_pdf']:
                                    images_with_alt += 1
                    
                    # Table detection (simplified)
                    if page_text:
                        text_lines = page_text.split('\n')
                        for line in text_lines:
                            # Simple table detection: multiple tabs/spaces in regular pattern
                            if line.count('\t') > 2 or (line.count('   ') > 3 and len(line.split()) > 4):
                                table_count += 1
                                # Check for potential headers
                                if text_lines.index(line) == 0 or any(word.lower() in ['name', 'date', 'amount', 'total', 'description'] for word in line.split()):
                                    tables_with_headers += 1
                                break
                                
                except Exception as e:
                    self.logger.debug(f"Error analyzing page {page_num}: {e}")
                    continue
            
            # Update accessibility features
            analysis_result['accessibility_features'].update({
                'total_images': total_images,
                'images_with_alt_text': images_with_alt if analysis_result['accessibility_features']['is_tagged_pdf'] else 0,
                'has_tables': table_count > 0,
                'table_count': table_count,
                'tables_with_headers': tables_with_headers,
                'text_content': has_text,
                'has_scanned_content': scanned_content,
                'ocr_needed': scanned_content and not has_text,
                # Additional flags used in legacy CSV exports
                'color_contrast_issues': total_images > 0 and not analysis_result['accessibility_features']['is_tagged_pdf'],
                'reading_order_valid': has_text and not scanned_content,
                'image_count': total_images,
            })
            
            # Additional accessibility checks
            if not has_text:
                analysis_result['issues'].append({
                    'rule': 'Text Content',
                    'description': 'PDF appears to have no searchable text content',
                    'recommendation': 'Ensure PDF contains searchable text or consider OCR for scanned documents',
                    'wcag_level': 'PDF/UA',
                    'severity': 'high',
                    'element_type': 'PDF'
                })
                analysis_result['score'] -= 25
            
            if total_images > 0 and not analysis_result['accessibility_features']['is_tagged_pdf']:
                analysis_result['issues'].append({
                    'rule': 'Image Accessibility',
                    'description': 'Images present but PDF is not tagged for screen readers',
                    'recommendation': 'Tag the PDF and add alternative text for images',
                    'wcag_level': 'PDF/UA',
                    'severity': 'high',
                    'element_type': 'PDF'
                })
                analysis_result['score'] -= 15
            
            if analysis_result['accessibility_features']['ocr_needed']:
                analysis_result['issues'].append({
                    'rule': 'Scanned Content',
                    'description': 'Scanned content detected - OCR recommended for accessibility',
                    'recommendation': 'Run OCR on the document to provide searchable text',
                    'wcag_level': 'PDF/UA',
                    'severity': 'medium',
                    'element_type': 'PDF'
                })
                analysis_result['score'] -= 10
            
            # Check for annotations
            try:
                annotation_count = 0
                for page in reader.pages:
                    if '/Annots' in page:
                        annotation_count += len(page['/Annots'])
                analysis_result['accessibility_features']['annotation_count'] = annotation_count
                analysis_result['accessibility_features']['has_annotations'] = annotation_count > 0
            except Exception:
                pass
            
            # Ensure score doesn't go below 0
            analysis_result['score'] = max(0, analysis_result['score'])
            analysis_result['issue_count'] = len(analysis_result['issues'])
            
            self.logger.info(f"PDF analysis completed for {url or 'local file'} - {analysis_result['issue_count']} issues found (Score: {analysis_result['score']}/100)")
            
        except Exception as e:
            self.logger.error(f"Error analyzing PDF {url}: {e}")
            analysis_result['error'] = str(e)
            analysis_result['issues'] = [{
                'rule': 'Analysis Error',
                'description': f'Failed to analyze PDF: {str(e)}',
                'recommendation': 'Check if PDF file is corrupted or password protected',
                'wcag_level': 'PDF/UA',
                'severity': 'high',
                'element_type': 'PDF'
            }]
            analysis_result['issue_count'] = 1
            analysis_result['score'] = 0
        
        return analysis_result
    
    def get_usage_status(self) -> Dict:
        """Get current usage status (local processing has no limits)"""
        return {
            'method': 'Local pypdf processing',
            'monthly_limit': 'unlimited',
            'monthly_usage': 0,
            'usage_history': []
        }
    
    def get_pdf_analysis_history(self) -> Dict:
        """Get PDF analysis history (local processing stores no history)"""
        return {"history": []}
