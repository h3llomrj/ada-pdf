"""
Accessibility Testing Module for WCAG 2.1 Level AA Compliance
Tests crawled pages for accessibility violations and issues
"""

import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum
import logging
from urllib.parse import urlparse

class Severity(Enum):
    """WCAG violation severity levels"""
    CRITICAL = "critical"  # Complete barriers to access
    SERIOUS = "serious"    # Significant barriers 
    MODERATE = "moderate"  # Difficulties for some users
    MINOR = "minor"        # Minor annoyances or potential issues

class WCAGLevel(Enum):
    """WCAG conformance levels"""
    A = "A"
    AA = "AA"
    AAA = "AAA"

@dataclass
class AccessibilityIssue:
    """Represents an accessibility violation found on a page"""
    rule_id: str
    rule_title: str
    description: str
    wcag_level: WCAGLevel
    severity: Severity
    element: str
    element_type: str
    url: str
    line_number: Optional[int] = None
    recommendation: str = ""

@dataclass
class AccessibilityReport:
    """Complete accessibility report for a page"""
    url: str
    title: str
    total_issues: int
    issues_by_severity: Dict[str, int]
    issues_by_level: Dict[str, int]
    issues: List[AccessibilityIssue]
    score: float  # Accessibility score (0-100)
    manual_review_issues: int = 0  # Count of manual review issues (excluded from total)

class WCAGChecker:
    """WCAG 2.1 Level AA accessibility checker"""
    
    def __init__(self, disabled_rules: List[str] = None):
        self.logger = logging.getLogger(__name__)
        self.issues = []
        self.disabled_rules = disabled_rules or []
        
        # WCAG 2.1 Level AA rules implementation
        self.rules = {
            # Images (1.1.1 Non-text Content, 1.4.5 Images of Text)
            'missing_alt_text': self._check_missing_alt_text,
            'inappropriate_alt_text': self._check_inappropriate_alt_text,
            'images_of_text': self._check_images_of_text,
            
            # Headings (1.3.1 Info and Relationships, 2.4.1 Bypass Blocks, 2.4.6 Headings and Labels)
            'missing_h1': self._check_missing_h1,
            'skipped_headings': self._check_skipped_headings,
            'empty_headings': self._check_empty_headings,
            
            # Links (2.4.4 Link Purpose, 1.4.1 Use of Color)
            'empty_links': self._check_empty_links,
            'vague_link_text': self._check_vague_link_text,
            'redundant_links': self._check_redundant_links,
            
            # Forms (1.3.1 Info and Relationships, 3.3.2 Labels or Instructions, 4.1.2 Name, Role, Value)
            'missing_labels': self._check_missing_labels,
            'missing_placeholders': self._check_missing_placeholders,
            'unlabeled_inputs': self._check_unlabeled_inputs,
            
            # Color (1.4.3 Contrast, 1.4.6 Contrast)
            'low_contrast_warning': self._check_low_contrast_warning,
            
            # Keyboard (2.1.1 Keyboard, 2.1.2 No Keyboard Trap)
            'keyboard_trap_warning': self._check_keyboard_trap_warning,
            
            # Focus (2.4.7 Focus Visible)
            'missing_focus_indicators': self._check_missing_focus_indicators,
            
            # Language (3.1.1 Language of Page)
            'missing_lang_attribute': self._check_missing_lang_attribute,
            
            # Page Title (2.4.2 Page Titled)
            'missing_page_title': self._check_missing_page_title,
            
            # Structure (1.3.1 Info and Relationships)
            'missing_landmarks': self._check_missing_landmarks,
        }
    
    def check_page(self, crawled_page: Dict[str, Any]) -> AccessibilityReport:
        """Run accessibility checks on a crawled page"""
        self.issues = []
        
        # Extract page data
        url = crawled_page.get('url', '')
        title = crawled_page.get('title', '')
        html_content = crawled_page.get('html_content', '')
        
        # Run all accessibility rules except disabled ones
        for rule_name, rule_func in self.rules.items():
            if rule_name in self.disabled_rules:
                self.logger.debug(f"Skipping disabled accessibility rule: {rule_name}")
                continue
            try:
                rule_func(crawled_page)
            except Exception as e:
                self.logger.warning(f"Error running rule {rule_name} on {url}: {e}")
        
        # Generate report
        return self._generate_report(url, title)
    
    def _generate_report(self, url: str, title: str) -> AccessibilityReport:
        """Generate accessibility report from found issues"""
        issues_by_severity = {severity.value: 0 for severity in Severity}
        issues_by_level = {level.value: 0 for level in WCAGLevel}
        
        # Separate manual review issues from countable issues
        manual_review_issues = []
        countable_issues = []
        
        for issue in self.issues:
            # Check if this is a manual review issue
            is_manual_review = (
                'manual review' in issue.description.lower() or
                'manual testing' in issue.description.lower() or
                'manual review needed' in issue.description.lower() or
                'manual testing required' in issue.description.lower() or
                'review needed' in issue.description.lower() or
                'testing required' in issue.description.lower() or
                'verify' in issue.description.lower() or
                'review for' in issue.description.lower() or
                'review needed' in issue.rule_title.lower() or
                'testing required' in issue.rule_title.lower()
            )
            
            if is_manual_review:
                manual_review_issues.append(issue)
            else:
                countable_issues.append(issue)
                issues_by_severity[issue.severity.value] += 1
                issues_by_level[issue.wcag_level.value] += 1
        
        # Calculate accessibility score based only on countable issues
        total_issues = len(countable_issues)  # Only count non-manual issues
        critical_weight = 10
        serious_weight = 5
        moderate_weight = 2
        minor_weight = 1
        
        weighted_score = (
            issues_by_severity['critical'] * critical_weight +
            issues_by_severity['serious'] * serious_weight +
            issues_by_severity['moderate'] * moderate_weight +
            issues_by_severity['minor'] * minor_weight
        )
        
        max_possible_score = 100  # Perfect score
        score = max(0, max_possible_score - weighted_score)
        
        return AccessibilityReport(
            url=url,
            title=title,
            total_issues=total_issues,
            issues_by_severity=issues_by_severity,
            issues_by_level=issues_by_level,
            issues=self.issues,  # Keep all issues in the full list
            manual_review_issues=len(manual_review_issues),  # Add manual review count
            score=score
        )
    
    def _add_issue(self, rule_id: str, rule_title: str, description: str, 
                   wcag_level: WCAGLevel, severity: Severity, element: str, 
                   element_type: str, url: str, recommendation: str = ""):
        """Add an accessibility issue to the report"""
        issue = AccessibilityIssue(
            rule_id=rule_id,
            rule_title=rule_title,
            description=description,
            wcag_level=wcag_level,
            severity=severity,
            element=element,
            element_type=element_type,
            url=url,
            recommendation=recommendation
        )
        self.issues.append(issue)
    
    # Image Accessibility Rules
    
    def _check_missing_alt_text(self, page: Dict[str, Any]):
        """WCAG 1.1.1: All images must have alt text"""
        images = page.get('images', [])
        url = page.get('url', '')
        
        for img in images:
            src = img.get('src', '')
            alt = img.get('alt', '')
            
            if alt is None or alt.strip() == '':
                self._add_issue(
                    rule_id='missing_alt_text',
                    rule_title='Missing Alt Text',
                    description=f'Image missing alt text: {src}',
                    wcag_level=WCAGLevel.A,
                    severity=Severity.CRITICAL,
                    element=src,
                    element_type='img',
                    url=url,
                    recommendation='Add descriptive alt text to explain image content'
                )
    
    def _check_inappropriate_alt_text(self, page: Dict[str, Any]):
        """WCAG 1.1.1: Alt text should not be file names or "image of" """
        images = page.get('images', [])
        url = page.get('url', '')
        
        inappropriate_patterns = [
            r'\.jpg$', r'\.png$', r'\.gif$', r'\.jpeg$',
            r'^image of', r'^picture of', r'^photo of'
        ]
        
        for img in images:
            src = img.get('src', '')
            alt = img.get('alt', '')
            
            if alt:
                alt_lower = alt.lower().strip()
                for pattern in inappropriate_patterns:
                    if re.search(pattern, alt_lower):
                        self._add_issue(
                            rule_id='inappropriate_alt_text',
                            rule_title='Inappropriate Alt Text',
                            description=f'Image has unhelpful alt text: "{alt}"',
                            wcag_level=WCAGLevel.A,
                            severity=Severity.MODERATE,
                            element=src,
                            element_type='img',
                            url=url,
                            recommendation='Replace with descriptive alt text that conveys image content'
                        )
    
    def _check_images_of_text(self, page: Dict[str, Any]):
        """WCAG 1.4.5: Avoid using images of text unless essential"""
        # This is a simplified check - in real implementation would analyze image content
        url = page.get('url', '')
        images = page.get('images', [])
        
        for img in images:
            src = img.get('src', '').lower()
            alt = img.get('alt', '')
            
            # Check if image filename suggests it contains text
            text_indicators = ['banner', 'header', 'title', 'text', 'button']
            if any(indicator in src for indicator in text_indicators):
                self._add_issue(
                    rule_id='images_of_text',
                    rule_title='Image of Text Detected',
                    description=f'Image may contain text: {src}',
                    wcag_level=WCAGLevel.AA,
                    severity=Severity.MODERATE,
                    element=src,
                    element_type='img',
                    url=url,
                    recommendation='Use actual text instead of images of text when possible'
                )
    
    # Heading Accessibility Rules
    
    def _check_missing_h1(self, page: Dict[str, Any]):
        """WCAG 1.3.1, 2.4.6: Pages should have exactly one h1"""
        headings = page.get('headings', {})
        url = page.get('url', '')
        
        h1_headings = headings.get('h1', [])
        
        if len(h1_headings) == 0:
            self._add_issue(
                rule_id='missing_h1',
                rule_title='Missing H1 Heading',
                description='Page has no H1 heading',
                wcag_level=WCAGLevel.A,
                severity=Severity.SERIOUS,
                element='page',
                element_type='structure',
                url=url,
                recommendation='Add one H1 heading that describes the page content'
            )
        elif len(h1_headings) > 1:
            self._add_issue(
                rule_id='missing_h1',
                rule_title='Multiple H1 Headings',
                description=f'Page has {len(h1_headings)} H1 headings',
                wcag_level=WCAGLevel.A,
                severity=Severity.MODERATE,
                element='page',
                element_type='structure',
                url=url,
                recommendation='Use exactly one H1 heading per page'
            )
    
    def _check_skipped_headings(self, page: Dict[str, Any]):
        """WCAG 1.3.1, 2.4.6: Heading levels should not be skipped"""
        headings = page.get('headings', {})
        url = page.get('url', '')
        
        # This is a simplified check - real implementation would analyze document order
        for level in ['h2', 'h3', 'h4', 'h5', 'h6']:
            if headings.get(level):
                # Check if previous level exists
                level_num = int(level[1])
                if level_num > 2:
                    prev_level = f'h{level_num - 1}'
                    if not headings.get(prev_level):
                        self._add_issue(
                            rule_id='skipped_headings',
                            rule_title='Skipped Heading Level',
                            description=f'Found {level.upper()} but missing {prev_level.upper()}',
                            wcag_level=WCAGLevel.A,
                            severity=Severity.MODERATE,
                            element='page',
                            element_type='structure',
                            url=url,
                            recommendation='Do not skip heading levels (e.g., H1 → H3)'
                        )
    
    def _check_empty_headings(self, page: Dict[str, Any]):
        """WCAG 2.4.6: Headings should not be empty"""
        headings = page.get('headings', {})
        url = page.get('url', '')
        
        for level, heading_list in headings.items():
            for heading in heading_list:
                if heading.strip() == '':
                    self._add_issue(
                        rule_id='empty_headings',
                        rule_title='Empty Heading',
                        description=f'Empty {level.upper()} heading found',
                        wcag_level=WCAGLevel.A,
                        severity=Severity.MINOR,
                        element=level,
                        element_type='heading',
                        url=url,
                        recommendation='Remove empty headings or add descriptive text'
                    )
    
    # Link Accessibility Rules
    
    def _check_empty_links(self, page: Dict[str, Any]):
        """WCAG 2.4.4: Links should have descriptive text"""
        links = page.get('links', [])
        url = page.get('url', '')
        
        for link in links:
            # This is simplified - real implementation would analyze link text
            if not link or link.strip() == '':
                self._add_issue(
                    rule_id='empty_links',
                    rule_title='Empty Link',
                    description='Link with no text found',
                    wcag_level=WCAGLevel.A,
                    severity=Severity.SERIOUS,
                    element=link,
                    element_type='link',
                    url=url,
                    recommendation='Add descriptive text to links'
                )
    
    def _check_vague_link_text(self, page: Dict[str, Any]):
        """WCAG 2.4.4: Link text should be descriptive out of context"""
        # This would need actual link text analysis
        url = page.get('url', '')
        
        # Placeholder for vague link text detection
        vague_text = ['click here', 'read more', 'learn more', 'here', 'more']
        
        # This is a simplified warning since we don't have link text in crawled data
        self._add_issue(
            rule_id='vague_link_text',
            rule_title='Vague Link Text Warning',
            description='Review links for vague text like "click here"',
            wcag_level=WCAGLevel.A,
            severity=Severity.MINOR,
            element='page',
            element_type='links',
            url=url,
            recommendation='Use descriptive link text that makes sense out of context'
        )
    
    def _check_redundant_links(self, page: Dict[str, Any]):
        """WCAG 2.4.4: Avoid multiple links with same text pointing to different URLs"""
        # This would need link text analysis
        url = page.get('url', '')
        
        # Placeholder for redundant link detection
        pass
    
    # Form Accessibility Rules
    
    def _check_missing_labels(self, page: Dict[str, Any]):
        """WCAG 3.3.2: Form inputs should have labels"""
        forms = page.get('forms', [])
        url = page.get('url', '')
        
        for form in forms:
            fields = form.get('fields', [])
            for field in fields:
                field_name = field.get('name', '')
                field_type = field.get('input_type', '')
                
                if field_type not in ['hidden', 'submit', 'button']:
                    # Simplified check - real implementation would check for associated labels
                    if not field_name:
                        self._add_issue(
                            rule_id='missing_labels',
                            rule_title='Missing Form Label',
                            description=f'Form input missing name/label: {field_type}',
                            wcag_level=WCAGLevel.A,
                            severity=Severity.SERIOUS,
                            element=field_type,
                            element_type='form',
                            url=url,
                            recommendation='Add descriptive labels to all form inputs'
                        )
    
    def _check_missing_placeholders(self, page: Dict[str, Any]):
        """WCAG 3.3.2: Form inputs should have placeholders or instructions"""
        forms = page.get('forms', [])
        url = page.get('url', '')
        
        for form in forms:
            fields = form.get('fields', [])
            for field in fields:
                field_type = field.get('input_type', '')
                
                if field_type in ['text', 'email', 'search', 'tel']:
                    # Check if field has placeholder (simplified)
                    if not field.get('placeholder'):
                        self._add_issue(
                            rule_id='missing_placeholders',
                            rule_title='Missing Form Placeholder',
                            description=f'Form input could benefit from placeholder: {field_type}',
                            wcag_level=WCAGLevel.AA,
                            severity=Severity.MINOR,
                            element=field_type,
                            element_type='form',
                            url=url,
                            recommendation='Add helpful placeholder text or instructions'
                        )
    
    def _check_unlabeled_inputs(self, page: Dict[str, Any]):
        """WCAG 4.1.2: Form inputs should have proper name, role, value"""
        forms = page.get('forms', [])
        url = page.get('url', '')
        
        for form in forms:
            fields = form.get('fields', [])
            for field in fields:
                field_name = field.get('name', '')
                field_type = field.get('input_type', '')
                
                if field_type not in ['hidden'] and not field_name:
                    self._add_issue(
                        rule_id='unlabeled_inputs',
                        rule_title='Unlabeled Form Input',
                        description=f'Form input missing name attribute: {field_type}',
                        wcag_level=WCAGLevel.A,
                        severity=Severity.SERIOUS,
                        element=field_type,
                        element_type='form',
                        url=url,
                        recommendation='Add name attribute to form inputs for proper identification'
                    )
    
    # Color and Contrast Rules
    
    def _check_low_contrast_warning(self, page: Dict[str, Any]):
        """WCAG 1.4.3, 1.4.6: Color contrast warning"""
        url = page.get('url', '')
        
        # This would need actual color analysis - placeholder warning
        self._add_issue(
            rule_id='low_contrast_warning',
            rule_title='Color Contrast Review Needed',
            description='Manual review needed for color contrast compliance',
            wcag_level=WCAGLevel.AA,
            severity=Severity.MINOR,
            element='page',
            element_type='style',
            url=url,
            recommendation='Ensure text meets WCAG AA contrast ratios (4.5:1 for normal text)'
        )
    
    # Keyboard and Focus Rules
    
    def _check_keyboard_trap_warning(self, page: Dict[str, Any]):
        """WCAG 2.1.1, 2.1.2: Keyboard accessibility warning"""
        url = page.get('url', '')
        
        # This would need interactive element analysis
        self._add_issue(
            rule_id='keyboard_trap_warning',
            rule_title='Keyboard Navigation Review Needed',
            description='Manual testing required for keyboard accessibility',
            wcag_level=WCAGLevel.A,
            severity=Severity.MODERATE,
            element='page',
            element_type='interaction',
            url=url,
            recommendation='Test all interactive elements with keyboard only'
        )
    
    def _check_missing_focus_indicators(self, page: Dict[str, Any]):
        """WCAG 2.4.7: Focus indicators should be visible"""
        url = page.get('url', '')
        
        # This would need CSS analysis
        self._add_issue(
            rule_id='missing_focus_indicators',
            rule_title='Focus Indicator Review Needed',
            description='Manual review needed for focus indicators',
            wcag_level=WCAGLevel.AA,
            severity=Severity.MODERATE,
            element='page',
            element_type='style',
            url=url,
            recommendation='Ensure all interactive elements have visible focus indicators'
        )
    
    # Language and Structure Rules
    
    def _check_missing_lang_attribute(self, page: Dict[str, Any]):
        """WCAG 3.1.1: Page should have lang attribute"""
        url = page.get('url', '')
        
        # This would need HTML analysis
        self._add_issue(
            rule_id='missing_lang_attribute',
            rule_title='Language Attribute Review Needed',
            description='Verify page has proper lang attribute',
            wcag_level=WCAGLevel.A,
            severity=Severity.MINOR,
            element='page',
            element_type='structure',
            url=url,
            recommendation='Add lang attribute to HTML element (e.g., lang="en")'
        )
    
    def _check_missing_page_title(self, page: Dict[str, Any]):
        """WCAG 2.4.2: Page should have descriptive title"""
        url = page.get('url', '')
        title = page.get('title', '')
        
        if not title or title.strip() == '':
            self._add_issue(
                rule_id='missing_page_title',
                rule_title='Missing Page Title',
                description='Page has no title',
                wcag_level=WCAGLevel.A,
                severity=Severity.SERIOUS,
                element='page',
                element_type='structure',
                url=url,
                recommendation='Add descriptive page title'
            )
        elif len(title.strip()) < 10:
            self._add_issue(
                rule_id='missing_page_title',
                rule_title='Short Page Title',
                description=f'Page title is very short: "{title}"',
                wcag_level=WCAGLevel.A,
                severity=Severity.MINOR,
                element=title,
                element_type='title',
                url=url,
                recommendation='Use more descriptive page titles'
            )
    
    def _check_missing_landmarks(self, page: Dict[str, Any]):
        """WCAG 1.3.1: Page should have landmark elements"""
        url = page.get('url', '')
        
        # This would need HTML structure analysis
        self._add_issue(
            rule_id='missing_landmarks',
            rule_title='Landmark Elements Review Needed',
            description='Review page for proper landmark elements (nav, main, etc.)',
            wcag_level=WCAGLevel.A,
            severity=Severity.MINOR,
            element='page',
            element_type='structure',
            url=url,
            recommendation='Use HTML5 landmark elements for better page structure'
        )
