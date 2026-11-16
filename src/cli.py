#!/usr/bin/env python3
"""
Command-line interface for the web crawler
"""

import asyncio
import click
import json
from pathlib import Path
from crawler import AsyncWebCrawler
import yaml

@click.group()
def cli():
    """College Website Accessibility Crawler"""
    pass

@cli.command()
@click.option('--url', required=True, help='URL to crawl')
@click.option('--depth', default=3, help='Maximum crawl depth')
@click.option('--pages', default=1000, help='Maximum pages to crawl')
@click.option('--output', default='output', help='Output directory')
@click.option('--config', default='config/sites.yaml', help='Configuration file')
@click.option('--accessibility', is_flag=True, help='Run WCAG 2.1 Level AA accessibility tests')
@click.option('--write-files', is_flag=True, default=False, help='Also write JSON/CSV files in addition to the database')
def single(url, depth, pages, output, config, accessibility, write_files):
    """Crawl a single website"""
    
    async def crawl():
        crawler = AsyncWebCrawler(config, run_accessibility=accessibility, write_files=write_files)
        click.echo(f"Starting crawl of {url} with depth {depth} and max {pages} pages")
        
        if accessibility:
            click.echo("🔍 WCAG 2.1 Level AA accessibility testing enabled")
        
        crawled_pages = await crawler.crawl_single_site(url, max_depth=depth, max_pages=pages)
        await crawler.save_results(crawled_pages, output)
        
        click.echo(f"Crawled {len(crawled_pages)} pages")
        click.echo(f"Results saved to {output}/")
        
        if accessibility and crawler.accessibility_reports:
            total_issues = sum(report.total_issues for report in crawler.accessibility_reports)
            manual_review_issues = sum(report.manual_review_issues for report in crawler.accessibility_reports)
            total_all_issues = total_issues + manual_review_issues
            avg_score = sum(report.score for report in crawler.accessibility_reports) / len(crawler.accessibility_reports)
            click.echo(f"📊 Accessibility Summary: {total_issues} automated issues found, {manual_review_issues} manual review items ({total_all_issues} total)")
            click.echo(f"📊 Average accessibility score: {avg_score:.1f}/100")
    
    asyncio.run(crawl())

@cli.command()
@click.option('--platform', multiple=True, help='Specific platforms to crawl (can be used multiple times)')
@click.option('--all', is_flag=True, help='Crawl all configured platforms')
@click.option('--depth', default=3, help='Maximum crawl depth')
@click.option('--pages', default=1000, help='Maximum pages per site')
@click.option('--output', default='output', help='Output directory')
@click.option('--config', default='config/sites.yaml', help='Configuration file')
@click.option('--accessibility', is_flag=True, help='Run WCAG 2.1 Level AA accessibility tests')
@click.option('--write-files', is_flag=True, default=False, help='Also write JSON/CSV files in addition to the database')
def platforms(platform, all, depth, pages, output, config, accessibility, write_files):
    """Crawl multiple platforms"""
    
    async def crawl():
        crawler = AsyncWebCrawler(config, run_accessibility=accessibility)
        
        if accessibility:
            click.echo("🔍 WCAG 2.1 Level AA accessibility testing enabled")
        
        if all:
            click.echo(f"Crawling all platforms with depth {depth} and max {pages} pages per site")
            results = await crawler.crawl_platforms(max_depth=depth, max_pages=pages)
        elif platform:
            click.echo(f"Crawling platforms: {', '.join(platform)}")
            results = await crawler.crawl_platforms(platform_names=list(platform), max_depth=depth, max_pages=pages)
        else:
            click.echo("Please specify --platform or --all")
            return
        
        # Flatten all pages
        all_pages = []
        for platform_name, pages_list in results.items():
            for page in pages_list:
                all_pages.append(page)
        
        await crawler.save_results(all_pages, output)
        
        click.echo(f"Crawled {len(all_pages)} pages across {len(results)} platforms")
        click.echo(f"Results saved to {output}/")
        
        failed_sites = getattr(crawler, 'failed_sites', [])
        if failed_sites:
            click.echo(f"\n⚠️  {len(failed_sites)} site(s) failed or returned zero pages — consider removing from config/sites.yaml:")
            for site_url, reason in failed_sites:
                click.echo(f"   - {site_url} ({reason})")
        
        if accessibility and crawler.accessibility_reports:
            total_issues = sum(report.total_issues for report in crawler.accessibility_reports)
            manual_review_issues = sum(report.manual_review_issues for report in crawler.accessibility_reports)
            total_all_issues = total_issues + manual_review_issues
            avg_score = sum(report.score for report in crawler.accessibility_reports) / len(crawler.accessibility_reports)
            click.echo(f"📊 Accessibility Summary: {total_issues} automated issues found, {manual_review_issues} manual review items ({total_all_issues} total)")
            click.echo(f"📊 Average accessibility score: {avg_score:.1f}/100")
    
    asyncio.run(crawl())

@cli.command()
@click.option('--config', default='config/sites.yaml', help='Configuration file')
def list_config(config):
    """List configured platforms and sites"""
    
    try:
        with open(config, 'r') as f:
            config_data = yaml.safe_load(f)
        
        platforms = config_data.get('platforms', {})
        
        if not platforms:
            click.echo("No platforms configured")
            return
        
        click.echo("Configured Platforms:")
        click.echo("=" * 50)
        
        for platform_id, platform_config in platforms.items():
            platform_name = platform_config.get('name', platform_id)
            sites = platform_config.get('sites', [])
            
            click.echo(f"\n📁 {platform_name} ({platform_id})")
            click.echo(f"   Sites: {len(sites)}")
            
            for i, site in enumerate(sites, 1):
                site_url = site if isinstance(site, str) else site['url']
                click.echo(f"   {i}. {site_url}")
    
    except FileNotFoundError:
        click.echo(f"Configuration file {config} not found")
    except Exception as e:
        click.echo(f"Error reading config: {e}")

@cli.command()
@click.option('--config', default='config/sites.yaml', help='Configuration file')
def validate_config(config):
    """Validate configuration file"""
    
    try:
        with open(config, 'r') as f:
            config_data = yaml.safe_load(f)
        
        # Check required sections
        required_sections = ['crawler_settings', 'output']
        missing_sections = [s for s in required_sections if s not in config_data]
        
        if missing_sections:
            click.echo(f"❌ Missing required sections: {', '.join(missing_sections)}")
            return
        
        # Check platforms
        platforms = config_data.get('platforms', {})
        if not platforms:
            click.echo("⚠️  No platforms configured")
        else:
            click.echo(f"✅ Found {len(platforms)} platform(s)")
            
            for platform_id, platform_config in platforms.items():
                sites = platform_config.get('sites', [])
                if not sites:
                    click.echo(f"⚠️  Platform {platform_id} has no sites")
                else:
                    click.echo(f"✅ Platform {platform_id} has {len(sites)} site(s)")
        
        # Check crawler settings
        settings = config_data['crawler_settings']
        click.echo(f"✅ Crawler settings: max_depth={settings.get('max_depth')}, "
                  f"delay={settings.get('delay_between_requests')}s")
        
        click.echo("✅ Configuration is valid")
        
    except yaml.YAMLError as e:
        click.echo(f"❌ YAML syntax error: {e}")
    except Exception as e:
        click.echo(f"❌ Error validating config: {e}")

if __name__ == "__main__":
    cli()
