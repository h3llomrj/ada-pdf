import React, { useState, useEffect } from 'react';
import { Layout, Card, Row, Col, Statistic, Progress, Table, Tag, Tabs, Alert, Spin, Modal, Button, Select, Space, message, Typography } from 'antd';
import { 
  FileTextOutlined, 
  ExclamationCircleOutlined, 
  CheckCircleOutlined,
  EyeOutlined,
  BarChartOutlined
} from '@ant-design/icons';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, PieChart, Pie, Cell } from 'recharts';
import axios from 'axios';
import './App.css';

const { Text } = Typography;

const { Header, Content } = Layout;
const { TabPane } = Tabs;


function App() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedPageIssues, setSelectedPageIssues] = useState(null);
  const [issueModalVisible, setIssueModalVisible] = useState(false);
  const [pdfUsage, setPdfUsage] = useState(null);
  const [analyzingPdf, setAnalyzingPdf] = useState(null); // Track which PDF is being analyzed
  const [pdfAnalysisResult, setPdfAnalysisResult] = useState(null);
  const [pdfAnalysisModalVisible, setPdfAnalysisModalVisible] = useState(false);
  
  // Filter states
  const [siteFilter, setSiteFilter] = useState('');
  const [platformFilter, setPlatformFilter] = useState('');
  const [severityFilter, setSeverityFilter] = useState([]);
  const [categoryFilter, setCategoryFilter] = useState([]);

  // Table pagination states
  const [htmlPageSize, setHtmlPageSize] = useState(10);
  const [pdfPageSize, setPdfPageSize] = useState(10);

  // Handle platform change - clear site filter when platform changes
  const handlePlatformChange = (value) => {
    setPlatformFilter(value);
    setSiteFilter(''); // Clear site filter when platform changes
  };

  useEffect(() => {
    fetchResults();
    fetchPdfUsage();
  }, []);

  const fetchPdfUsage = async () => {
    try {
      const response = await axios.get('/api/pdf-usage');
      setPdfUsage(response.data);
    } catch (err) {
      console.error('Error fetching PDF usage:', err);
    }
  };

  const fetchResults = async () => {
    try {
      setLoading(true);
      const response = await axios.get('/api/latest-results');
      setData(response.data);
    } catch (err) {
      setError(`Failed to load accessibility data: ${err.message || 'Unknown error'}`);
      console.error('Error fetching data:', err);
      console.error('Error details:', err.response?.data);
    } finally {
      setLoading(false);
    }
  };

  const showPageIssues = async (pageUrl) => {
    try {
      // Check if this is a PDF by looking at the current data
      const pageData = data?.pages?.find(p => p.url === pageUrl);
      
      console.log('DEBUG showPageIssues for:', pageUrl);
      console.log('Page data from current state:', pageData);
      
      if (pageData?.content_type === 'application/pdf') {
        // For PDFs, show the PDF analysis modal with existing data
        let analysisData;
        
        if (pageData.pdf_analysis) {
          // Use specific PDF analysis data
          analysisData = pageData.pdf_analysis;
        } else {
          // Use WCAG accessibility analysis data
          analysisData = {
            url: pageUrl,
            issue_count: pageData.issue_count || 0,
            accessibility_score: pageData.score || pageData.accessibility_score || 100,
            wcag_compliant: pageData.wcag_compliant,
            issues: pageData.accessibility_issues || pageData.issues || [],
            metadata: {
              analysis_method: 'WCWCAG Accessibility Analysis',
              is_tagged: pageData.wcag_compliant,
              num_pages: 'Unknown'
            }
          };
        }
        setPdfAnalysisResult(analysisData);
        setPdfAnalysisModalVisible(true);
      } else {
        // For HTML pages, fetch detailed issues
        const response = await axios.get(`/api/page-issues/${encodeURIComponent(pageUrl)}`);
        const htmlPageData = response.data;
        
        if (htmlPageData.issues && htmlPageData.issues.length > 0) {
          // Transform the data to match the expected format for the modal
          const formattedData = {
            url: htmlPageData.url,
            title: htmlPageData.title,
            total_issues: htmlPageData.issue_count,
            issues: htmlPageData.issues,
            issues_by_severity: {
              critical: htmlPageData.issues.filter(i => i.severity === 'critical').length,
              serious: htmlPageData.issues.filter(i => i.severity === 'serious').length,
              moderate: htmlPageData.issues.filter(i => i.severity === 'moderate').length,
              minor: htmlPageData.issues.filter(i => i.severity === 'minor').length,
            }
          };
          setSelectedPageIssues(formattedData);
          setIssueModalVisible(true);
        } else {
          Modal.info({
            title: 'No Issues Found',
            content: 'This page has no accessibility issues recorded.',
          });
        }
      }
    } catch (error) {
      message.error('Failed to fetch page issues');
    }
  };

  const normalizeSeverity = (severity) => {
    if (!severity) return '';
    return severity.replace('Severity.', '').toLowerCase();
  };

  const getSeverityColor = (severity) => {
    switch (severity) {
      case 'Severity.CRITICAL': 
      case 'critical': return '#ff4d4f';
      case 'Severity.SERIOUS': 
      case 'serious': return '#faad14';
      case 'Severity.MODERATE': 
      case 'moderate': return '#1890ff';
      case 'Severity.MINOR': 
      case 'minor': return '#52c41a';
      default: return '#d9d9d9';
    }
  };

  const getLevelColor = (level) => {
    switch (level) {
      case 'WCAGLevel.AA': 
      case 'AA': return '#ff4d4f';
      case 'WCAGLevel.A': 
      case 'A': return '#faad14';
      case 'WCAGLevel.AAA': 
      case 'AAA': return '#1890ff';
      default: return '#d9d9d9';
    }
  };

  const analyzePdf = async (pdfUrl, forceRefresh = false) => {
    if (!pdfUsage?.can_make_call && !forceRefresh) {
      Modal.warning({
        title: 'API Limit Reached',
        content: `You've used ${pdfUsage.monthly_usage}/${pdfUsage.monthly_limit} API calls this month. Please wait until next month to analyze more PDFs.`,
      });
      return;
    }

    try {
      setAnalyzingPdf(pdfUrl); // Track which specific PDF is being analyzed
      
      const response = await fetch('/api/analyze-pdf', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
          pdf_url: pdfUrl,
          force_refresh: forceRefresh 
        }),
      });
      const result = await response.json();
      
      if (result.error) {
        message.error(result.error);
      } else {
        // Automatically save the analysis results
        try {
          const saveResponse = await fetch('/api/save-pdf-analysis', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ 
              pdf_url: pdfUrl,
              analysis_result: result
            }),
          });
          
          const saveResult = await saveResponse.json();
          
          if (saveResult.success) {
            message.success('PDF analysis completed and saved!');
            // Refresh the data to show updated scores in the table
            fetchResults();
          }
        } catch (saveError) {
          // Still show the modal even if save fails
          console.warn('Failed to save PDF analysis:', saveError);
        }
        
        setPdfAnalysisResult(result);
        setPdfAnalysisModalVisible(true);
        // Refresh usage data
        fetchPdfUsage();
      }
    } catch (error) {
      message.error('Failed to analyze PDF');
    } finally {
      setAnalyzingPdf(null); // Clear the analyzing state
    }
  };

  const exportPdfData = async (siteName, detailed = true) => {
    try {
      const endpoint = detailed ? `/api/export-pdf-data/${encodeURIComponent(siteName)}` : `/api/export-pdf-summary/${encodeURIComponent(siteName)}`;
      const response = await fetch(endpoint);
      
      if (!response.ok) {
        const errorData = await response.json();
        message.error(errorData.error || 'Export failed');
        return;
      }
      
      // Get filename from response headers or create default
      const contentDisposition = response.headers.get('Content-Disposition');
      const exportType = detailed ? 'detailed' : 'summary';
      let filename = `pdf_accessibility_${exportType}_${siteName}_${new Date().toISOString().split('T')[0]}.csv`;
      
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/);
        if (filenameMatch) {
          filename = filenameMatch[1];
        }
      }
      
      // Download the file
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      
      const exportDescription = detailed ? 'detailed PDF data' : 'PDF summary data';
      message.success(`${exportDescription} exported for ${siteName}`);
    } catch (error) {
      message.error('Export failed');
    }
  };

  const exportAllPdfSummary = async () => {
    try {
      // Use detailed all-platforms endpoint so this matches the per-platform "Export Detailed (All Issues)" export
      const response = await fetch('/api/export-all-pdf-data');
      
      if (!response.ok) {
        const errorData = await response.json();
        message.error(errorData.error || 'Export failed');
        return;
      }
      
      // Get filename from response headers or create default
      const contentDisposition = response.headers.get('Content-Disposition');
      let filename = `pdf_accessibility_ALL_${new Date().toISOString().split('T')[0]}.csv`;
      
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/);
        if (filenameMatch) {
          filename = filenameMatch[1];
        }
      }
      
      // Download the file
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      
      message.success('All detailed PDF data exported successfully');
    } catch (error) {
      message.error('Export failed');
    }
  };

  if (loading) {
    return (
      <div className="loading-container">
        <Spin size="large" />
        <p>Loading accessibility data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <Layout>
        <Header className="header">
          <h1>Accessibility Dashboard</h1>
        </Header>
        <Content style={{ padding: '24px' }}>
          <Alert message="Error" description={error} type="error" showIcon />
        </Content>
      </Layout>
    );
  }

  if (!data) {
    return (
      <Layout>
        <Header className="header">
          <h1>Accessibility Dashboard</h1>
        </Header>
        <Content style={{ padding: '24px' }}>
          <Alert 
            message="No Data Available" 
            description="Please run the crawler with accessibility checking enabled to see results." 
            type="info" 
            showIcon 
          />
        </Content>
      </Layout>
    );
  }

  const { summary } = data;

  const severityData = [
    { name: 'Critical', value: summary.critical_issues, color: '#ff4d4f' },
    { name: 'Serious', value: summary.serious_issues, color: '#faad14' },
    { name: 'Moderate', value: summary.moderate_issues, color: '#1890ff' },
    { name: 'Minor', value: summary.minor_issues, color: '#52c41a' },
  ].filter(item => item.value > 0);

  const categoryData = Object.entries(summary.issues_by_category || {}).map(([category, count]) => ({
    category: category.replace(/_/g, ' ').toUpperCase(),
    count
  }));

  const pageColumns = [
    {
      title: 'Title',
      dataIndex: 'title',
      key: 'title',
      render: (title, record) => (
        <div>
          <div style={{ fontWeight: 'bold', marginBottom: 4 }}>
            {title || 'No Title'}
          </div>
          <a href={record.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: '12px', color: '#666' }}>
            {record.url}
          </a>
          {record.content_type === 'application/pdf' && record.source_page && (
            <div style={{ fontSize: '11px', color: '#999', marginTop: 4 }}>
              <span>Found on: </span>
              <a href={record.source_page} target="_blank" rel="noopener noreferrer" style={{ color: '#999' }}>
                {record.source_page}
              </a>
            </div>
          )}
        </div>
      ),
      ellipsis: true,
    },
    {
      title: 'Platform',
      dataIndex: 'platform',
      key: 'platform',
      render: (platform) => (
        <Tag color="blue">
          {platform || 'Unknown'}
        </Tag>
      ),
    },
    {
      title: 'Issues',
      dataIndex: 'issue_count',
      key: 'issue_count',
      sorter: (a, b) => {
        const aCount = (a.content_type === 'application/pdf' && (a.score === null || a.score === undefined)) ? -1 : a.issue_count;
        const bCount = (b.content_type === 'application/pdf' && (b.score === null || b.score === undefined)) ? -1 : b.issue_count;
        return aCount - bCount;
      },
      render: (count, record) => {
        // Show "N/A" for unanalyzed PDFs (check if score is null/undefined)
        if (record.content_type === 'application/pdf' && (record.score === null || record.score === undefined)) {
          return <Tag color="default">N/A</Tag>;
        }
        return (
          <Tag color={count === 0 ? 'green' : count > 10 ? 'red' : 'orange'}>
            {count}
          </Tag>
        );
      },
    },
    {
      title: 'WCAG Compliant',
      dataIndex: 'wcag_compliant',
      key: 'wcag_compliant',
      sorter: (a, b) => {
        const aCompliant = a.wcag_compliant === true ? 1 : a.wcag_compliant === false ? 0 : -1;
        const bCompliant = b.wcag_compliant === true ? 1 : b.wcag_compliant === false ? 0 : -1;
        return bCompliant - aCompliant;
      },
      render: (compliant, record) => {
        // Show "N/A" for unanalyzed PDFs (check if score is null/undefined)
        if (record.content_type === 'application/pdf' && (record.score === null || record.score === undefined)) {
          return <Tag color="default">N/A</Tag>;
        }
        if (compliant === true) {
          return <Tag color="green">Yes</Tag>;
        } else if (compliant === false) {
          return <Tag color="red">No</Tag>;
        }
        return <Tag color="default">N/A</Tag>;
      },
    },
    {
      title: 'Score',
      dataIndex: 'score',
      key: 'score',
      sorter: (a, b) => {
        const aScore = (a.content_type === 'application/pdf' && (a.score === null || a.score === undefined)) ? -1 : a.score;
        const bScore = (b.content_type === 'application/pdf' && (b.score === null || b.score === undefined)) ? -1 : b.score;
        return aScore - bScore;
      },
      render: (score, record) => {
        // Show "N/A" for unanalyzed PDFs (check if score is null/undefined)
        if (record.content_type === 'application/pdf' && (score === null || score === undefined)) {
          return <Tag color="default">N/A</Tag>;
        }
        return (
          <Progress 
            percent={score} 
            size="small" 
            status={score >= 90 ? 'success' : score >= 70 ? 'normal' : 'exception'}
            format={() => `${score}/100`}
          />
        );
      },
    },
    {
      title: 'Type',
      dataIndex: 'content_type',
      key: 'content_type',
      render: (type) => (
        <Tag icon={type === 'application/pdf' ? <FileTextOutlined /> : <EyeOutlined />}>
          {type === 'application/pdf' ? 'PDF' : 'HTML'}
        </Tag>
      ),
    },
    {
      title: 'Archived',
      dataIndex: 'is_archived',
      key: 'is_archived',
      filters: [
        { text: 'Archived', value: true },
        { text: 'Current', value: false },
      ],
      onFilter: (value, record) => record.is_archived === value,
      render: (isArchived) => (
        isArchived ? <Tag color="orange">Archived</Tag> : <Tag color="green">Current</Tag>
      ),
    },
    {
      title: 'Last Crawled',
      dataIndex: 'crawl_timestamp',
      key: 'crawl_timestamp',
      sorter: (a, b) => {
        if (!a.crawl_timestamp) return 1;
        if (!b.crawl_timestamp) return -1;
        return new Date(a.crawl_timestamp) - new Date(b.crawl_timestamp);
      },
      render: (timestamp) => {
        if (!timestamp) return <Tag color="default">Never</Tag>;
        
        try {
          const date = new Date(timestamp);
          const now = new Date();
          const diffMs = now - date;
          const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
          const diffDays = Math.floor(diffHours / 24);
          
          if (diffDays > 0) {
            return <Tag color="blue">{diffDays} day{diffDays > 1 ? 's' : ''} ago</Tag>;
          } else if (diffHours > 0) {
            return <Tag color="cyan">{diffHours} hour{diffHours > 1 ? 's' : ''} ago</Tag>;
          } else {
            return <Tag color="green">Recently</Tag>;
          }
        } catch (error) {
          return <Tag color="default">Unknown</Tag>;
        }
      },
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_, record) => (
        <Space>
          <Button 
            size="small"
            onClick={() => showPageIssues(record.url)}
          >
            View Issues
          </Button>
        </Space>
      ),
    },
  ];

  const pages = data ? data.pages : [];
  
  // Create a mapping of sites to their platforms
  const siteToPlatformMap = {};
  pages.forEach(page => {
    const url = new URL(page.url);
    const hostname = url.hostname;
    siteToPlatformMap[hostname] = page.platform || 'Unknown';
  });
  
  const platforms = [...new Set(pages.map(page => page.platform || 'Unknown'))];
  
  // Filter sites based on selected platform
  const availableSites = platformFilter 
    ? [...new Set(pages
        .filter(page => page.platform === platformFilter)
        .map(page => {
          const url = new URL(page.url);
          return url.hostname;
        }))]
    : [...new Set(pages.map(page => {
        const url = new URL(page.url);
        return url.hostname;
      }))];
  
  const filteredPages = pages.filter(page => {
    const url = new URL(page.url);
    const siteMatch = !siteFilter || url.hostname === siteFilter;
    const platformMatch = !platformFilter || page.platform === platformFilter;
    return siteMatch && platformMatch;
  });
  
  const htmlPages = filteredPages.filter(page => page.content_type !== 'application/pdf');
  const pdfPages = filteredPages.filter(page => page.content_type === 'application/pdf');

  // Derive available severities and categories from HTML page issues
  const htmlIssues = htmlPages.flatMap(page => page.accessibility_issues || []);
  const severityOptions = Array.from(new Set(
    htmlIssues
      .map(issue => normalizeSeverity(issue.severity))
      .filter(Boolean)
  ));
  const categoryOptions = Array.from(new Set(
    htmlIssues
      .map(issue => (issue.element_type || '').toLowerCase())
      .filter(Boolean)
  ));

  // Apply severity/category filters to HTML pages only
  const htmlPagesFilteredByIssues = htmlPages.filter(page => {
    const issues = page.accessibility_issues || [];
    const matchesSeverity = !severityFilter.length || issues.some(issue =>
      severityFilter.includes(normalizeSeverity(issue.severity))
    );
    const matchesCategory = !categoryFilter.length || issues.some(issue => {
      const cat = (issue.element_type || '').toLowerCase();
      return categoryFilter.includes(cat);
    });
    return matchesSeverity && matchesCategory;
  });

  return (
    <Layout className="layout">
      <Header className="header">
        <div className="header-content">
          <h1>Accessibility Dashboard</h1>
          <p>WCAG 2.1 Level AA Compliance Monitoring</p>
        </div>
      </Header>
      
      <Content style={{ padding: '24px' }}>
        {/* Overview Cards */}
        <Row gutter={[16, 16]} style={{ marginBottom: '24px' }}>
          <Col xs={24} sm={12} md={6}>
            <Card>
              <Statistic
                title="Total Pages"
                value={summary.total_pages}
                prefix={<FileTextOutlined />}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card>
              <Statistic
                title="Total Issues"
                value={summary.total_issues}
                prefix={<ExclamationCircleOutlined />}
                valueStyle={{ color: summary.total_issues > 0 ? '#cf1322' : '#3f8600' }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card>
              <Statistic
                title="Average Score"
                value={summary.average_score}
                precision={1}
                suffix="/100"
                prefix={<CheckCircleOutlined />}
                valueStyle={{ color: summary.average_score >= 90 ? '#3f8600' : summary.average_score >= 70 ? '#faad14' : '#cf1322' }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Card>
              <Statistic
                title="PDF Documents"
                value={pdfPages.length}
                prefix={<FileTextOutlined />}
              />
              {pdfUsage && (
                <div style={{ marginTop: 8, fontSize: '12px', color: '#666' }}>
                  <div>PDF API Usage: {pdfUsage.monthly_usage}/{pdfUsage.monthly_limit}</div>
                  <Progress 
                    percent={(pdfUsage.monthly_usage / pdfUsage.monthly_limit) * 100} 
                    size="small" 
                    status={pdfUsage.can_make_call ? 'normal' : 'exception'}
                    showInfo={false}
                  />
                </div>
              )}
            </Card>
          </Col>
        </Row>

        {/* Charts */}
        <Row gutter={[16, 16]} style={{ marginBottom: '24px' }}>
          <Col xs={24} lg={12}>
            <Card title="Issues by Severity" extra={<BarChartOutlined />}>
              {severityData.length > 0 ? (
                <PieChart width={400} height={300}>
                  <Pie
                    data={severityData}
                    cx={200}
                    cy={150}
                    labelLine={false}
                    label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                    outerRadius={80}
                    fill="#8884d8"
                    dataKey="value"
                  >
                    {severityData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              ) : (
                <div style={{ textAlign: 'center', padding: '50px' }}>
                  <CheckCircleOutlined style={{ fontSize: '48px', color: '#52c41a' }} />
                  <p>No accessibility issues found!</p>
                </div>
              )}
            </Card>
          </Col>
          
          <Col xs={24} lg={12}>
            <Card title="Issues by Category" extra={<BarChartOutlined />}>
              {categoryData.length > 0 ? (
                <BarChart width={400} height={300} data={categoryData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="category" angle={-45} textAnchor="end" height={100} />
                  <YAxis />
                  <Tooltip />
                  <Bar dataKey="count" fill="#1890ff" />
                </BarChart>
              ) : (
                <div style={{ textAlign: 'center', padding: '50px' }}>
                  <CheckCircleOutlined style={{ fontSize: '48px', color: '#52c41a' }} />
                  <p>No issues by category to display</p>
                </div>
              )}
            </Card>
          </Col>
        </Row>

        {/* Filters */}
        <Card title="Filters" style={{ marginBottom: 16 }}>
          <Row gutter={[16, 16]}>
            <Col span={8}>
              <label>Platform:</label>
              <Select
                style={{ width: '100%', marginTop: 4 }}
                placeholder="All platforms"
                allowClear
                value={platformFilter || undefined}
                onChange={handlePlatformChange}
              >
                {platforms.map(platform => (
                  <Select.Option key={platform} value={platform}>
                    {platform}
                  </Select.Option>
                ))}
              </Select>
            </Col>
            <Col span={8}>
              <label>Site:</label>
              <Select
                style={{ width: '100%', marginTop: 4 }}
                placeholder={platformFilter ? "Select site..." : "All sites"}
                allowClear
                value={siteFilter || undefined}
                onChange={setSiteFilter}
                disabled={platformFilter && availableSites.length === 0}
              >
                {availableSites.map(site => (
                  <Select.Option key={site} value={site}>
                    {site}
                  </Select.Option>
                ))}
              </Select>
            </Col>
            <Col span={8}>
              <label>Results:</label>
              <div style={{ marginTop: 4 }}>
                <Statistic
                  title="Filtered Pages"
                  value={filteredPages.length}
                  suffix={`/ ${pages.length} total`}
                />
              </div>
            </Col>
          </Row>
          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col span={8}>
              <label>HTML Severity:</label>
              <Select
                mode="multiple"
                style={{ width: '100%', marginTop: 4 }}
                placeholder="All severities"
                allowClear
                value={severityFilter}
                onChange={setSeverityFilter}
              >
                {severityOptions.map(sev => (
                  <Select.Option key={sev} value={sev}>
                    {sev.charAt(0).toUpperCase() + sev.slice(1)}
                  </Select.Option>
                ))}
              </Select>
            </Col>
            <Col span={8}>
              <label>HTML Category:</label>
              <Select
                mode="multiple"
                style={{ width: '100%', marginTop: 4 }}
                placeholder="All categories"
                allowClear
                value={categoryFilter}
                onChange={setCategoryFilter}
              >
                {categoryOptions.map(cat => (
                  <Select.Option key={cat} value={cat}>
                    {cat}
                  </Select.Option>
                ))}
              </Select>
            </Col>
          </Row>
        </Card>

        {/* Detailed Tables */}
        <Card>
          <Tabs defaultActiveKey="html">
            <TabPane tab={`HTML Pages (${htmlPages.length})`} key="html">
              <Table
                columns={pageColumns}
                dataSource={htmlPagesFilteredByIssues}
                rowKey="url"
                pagination={{
                  pageSize: htmlPageSize,
                  showSizeChanger: true,
                  pageSizeOptions: ['10', '20', '50', '100'],
                  onShowSizeChange: (current, size) => setHtmlPageSize(size),
                }}
                scroll={{ x: true }}
              />
            </TabPane>
            
            <TabPane tab={`PDF Documents (${pdfPages.length})`} key="pdf">
              {/* Export buttons grouped by site */}
              <div style={{ marginBottom: 16 }}>
                <div style={{ marginBottom: 12 }}>
                  <Button
                    type="primary"
                    icon={<FileTextOutlined />}
                    onClick={exportAllPdfSummary}
                    disabled={pdfPages.length === 0}
                  >
                    Export All PDFs - Detailed (All Issues) ({pdfPages.length} total PDFs)
                  </Button>
                  <Text style={{ marginLeft: 8, color: '#666' }}>
                    Downloads a detailed report of all PDFs from all sites (one row per PDF with full metadata and issues)
                  </Text>
                </div>
                <h4>Export PDF Data by Site:</h4>
                <Space wrap>
                  {Object.entries(
                    pdfPages.reduce((acc, pdf) => {
                      const site = pdf.platform || 'Unknown Site';
                      if (!acc[site]) acc[site] = [];
                      acc[site].push(pdf);
                      return acc;
                    }, {})
                  ).map(([siteName, sitePdfs]) => (
                    <div key={siteName} style={{ marginBottom: 8 }}>
                      <Text strong>{siteName} ({sitePdfs.length} PDFs):</Text>
                      <div style={{ marginTop: 4 }}>
                        <Space>
                          <Button
                            size="small"
                            type="default"
                            icon={<FileTextOutlined />}
                            onClick={() => exportPdfData(siteName, true)}
                            disabled={sitePdfs.length === 0}
                          >
                            Export Detailed (All Issues)
                          </Button>
                          <Button
                            size="small"
                            type="default"
                            icon={<FileTextOutlined />}
                            onClick={() => exportPdfData(siteName, false)}
                            disabled={sitePdfs.length === 0}
                          >
                            Export Summary (One Row Per PDF)
                          </Button>
                        </Space>
                      </div>
                    </div>
                  ))}
                </Space>
              </div>
              
              <Table
                columns={pageColumns}
                dataSource={pdfPages}
                rowKey="url"
                pagination={{
                  pageSize: pdfPageSize,
                  showSizeChanger: true,
                  pageSizeOptions: ['10', '20', '50', '100', '500'],
                  onShowSizeChange: (current, size) => setPdfPageSize(size),
                }}
                scroll={{ x: true }}
              />
            </TabPane>
          </Tabs>
        </Card>

        {/* Issues Detail Modal */}
        <Modal
          title={
            <div>
              <ExclamationCircleOutlined style={{ marginRight: 8, color: '#faad14' }} />
              Accessibility Issues for {selectedPageIssues?.title}
              <br />
              <small style={{ color: '#666' }}>{selectedPageIssues?.url}</small>
            </div>
          }
          visible={issueModalVisible}
          onCancel={() => setIssueModalVisible(false)}
          footer={[
            <Button key="close" onClick={() => setIssueModalVisible(false)}>
              Close
            </Button>,
            <Button 
              key="visit" 
              type="primary" 
              href={selectedPageIssues?.url} 
              target="_blank"
            >
              Visit Page
            </Button>
          ]}
          width={1000}
        >
          {selectedPageIssues && (
            <div>
              <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                <Col span={8}>
                  <Card size="small">
                    <Statistic
                      title="Total Issues"
                      value={selectedPageIssues.total_issues}
                      valueStyle={{ color: selectedPageIssues.total_issues > 0 ? '#cf1322' : '#3f8600' }}
                    />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small">
                    <Statistic
                      title="Critical"
                      value={selectedPageIssues.issues_by_severity?.critical || 0}
                      valueStyle={{ color: '#ff4d4f' }}
                    />
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small">
                    <Statistic
                      title="Serious"
                      value={selectedPageIssues.issues_by_severity?.serious || 0}
                      valueStyle={{ color: '#faad14' }}
                    />
                  </Card>
                </Col>
              </Row>

              <h4>Detailed Issues</h4>
              {selectedPageIssues.issues && selectedPageIssues.issues.length > 0 ? (
                <div>
                  {selectedPageIssues.issues.map((issue, index) => (
                    <Card 
                      key={index} 
                      size="small" 
                      style={{ marginBottom: 12, borderLeft: `4px solid ${getSeverityColor(issue.severity)}` }}
                    >
                      <Row gutter={[16, 8]}>
                        <Col span={24}>
                          <strong>{issue.rule_title}</strong>
                          <div style={{ marginTop: 4 }}>
                            <Tag color={getSeverityColor(issue.severity)} style={{ marginRight: 8 }}>
                              {issue.severity?.replace('Severity.', '')}
                            </Tag>
                            <Tag color={getLevelColor(issue.wcag_level)} style={{ marginRight: 8 }}>
                              {issue.wcag_level?.replace('WCAGLevel.', '')}
                            </Tag>
                            <Tag color="blue">
                              {issue.element_type}
                            </Tag>
                          </div>
                        </Col>
                        <Col span={24}>
                          <p style={{ margin: '8px 0', color: '#666' }}>
                            {issue.description}
                          </p>
                        </Col>
                        <Col span={24}>
                          <strong>Recommendation:</strong>
                          <p style={{ margin: '4px 0', color: '#1890ff' }}>
                            {issue.recommendation}
                          </p>
                        </Col>
                        {issue.element && issue.element !== 'page' && (
                          <Col span={24}>
                            <code style={{ background: '#f5f5f5', padding: '4px 8px', borderRadius: 4 }}>
                              Element: {issue.element}
                            </code>
                          </Col>
                        )}
                      </Row>
                    </Card>
                  ))}
                </div>
              ) : (
                <Alert
                  message="No Issues"
                  description="This page has no accessibility issues detected."
                  type="success"
                  showIcon
                />
              )}
            </div>
          )}
        </Modal>

        {/* PDF Analysis Results Modal */}
        <Modal
          title={
            <div>
              <FileTextOutlined style={{ marginRight: 8, color: '#1890ff' }} />
              PDF Accessibility Analysis
              {pdfAnalysisResult?.cached && (
                <Tag color="blue" style={{ marginLeft: 8 }}>Cached</Tag>
              )}
              <br />
              <small style={{ color: '#666' }}>{pdfAnalysisResult?.url}</small>
            </div>
          }
          visible={pdfAnalysisModalVisible}
          onCancel={() => setPdfAnalysisModalVisible(false)}
          footer={[
            <Button key="close" onClick={() => setPdfAnalysisModalVisible(false)}>
              Close
            </Button>,
            <Button 
              key="download" 
              type="primary" 
              href={pdfAnalysisResult?.url} 
              target="_blank"
            >
              Download PDF
            </Button>
          ]}
          width={1000}
        >
          {pdfAnalysisResult && (
            <div>
              <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                <Col span={6}>
                  <Card size="small">
                    <Statistic
                      title="Total Issues"
                      value={pdfAnalysisResult.issue_count || 0}
                      valueStyle={{ color: (pdfAnalysisResult.issue_count || 0) > 0 ? '#cf1322' : '#3f8600' }}
                    />
                  </Card>
                </Col>
                <Col span={6}>
                  <Card size="small">
                    <Statistic
                      title="WCAG Compliant"
                      value={pdfAnalysisResult.wcag_compliant ? 'Yes' : 'No'}
                      valueStyle={{ color: pdfAnalysisResult.wcag_compliant ? '#3f8600' : '#cf1322' }}
                    />
                  </Card>
                </Col>
                <Col span={6}>
                  <Card size="small">
                    <Statistic
                      title="Accessibility Score"
                      value={pdfAnalysisResult.accessibility_score || 0}
                      suffix="/100"
                      valueStyle={{ color: (pdfAnalysisResult.accessibility_score || 0) >= 90 ? '#3f8600' : (pdfAnalysisResult.accessibility_score || 0) >= 70 ? '#faad14' : '#cf1322' }}
                    />
                  </Card>
                </Col>
                <Col span={6}>
                  <Card size="small">
                    <Statistic
                      title="Pages"
                      value={pdfAnalysisResult.metadata?.num_pages || 0}
                      valueStyle={{ color: '#1890ff' }}
                    />
                  </Card>
                </Col>
              </Row>

              {pdfAnalysisResult.pdf_properties && (
                <Card title="PDF Properties" size="small" style={{ marginBottom: 16 }}>
                  <Row gutter={[16, 8]}>
                    <Col span={8}><strong>Title:</strong> {pdfAnalysisResult.pdf_properties.title}</Col>
                    <Col span={8}><strong>Language:</strong> {pdfAnalysisResult.pdf_properties.language}</Col>
                    <Col span={8}><strong>Pages:</strong> {pdfAnalysisResult.pdf_properties.page_count}</Col>
                    <Col span={8}><strong>File Size:</strong> {(pdfAnalysisResult.pdf_properties.file_size / 1024 / 1024).toFixed(2)} MB</Col>
                    <Col span={8}><strong>Tagged:</strong> {pdfAnalysisResult.pdf_properties.tagged ? 'Yes' : 'No'}</Col>
                    <Col span={8}><strong>Has Forms:</strong> {pdfAnalysisResult.pdf_properties.has_forms ? 'Yes' : 'No'}</Col>
                  </Row>
                </Card>
              )}

              <h4>Accessibility Issues</h4>
              
              {/* Show PDF Analysis Results */}
              {pdfAnalysisResult.issues && pdfAnalysisResult.issues.length > 0 ? (
                <div>
                  <h5>PDF Analysis Results</h5>
                  {pdfAnalysisResult.issues.map((issue, index) => (
                    <Card 
                      key={index} 
                      size="small" 
                      style={{ marginBottom: 12, borderLeft: `4px solid ${getSeverityColor(issue.severity)}` }}
                    >
                      <Row gutter={[16, 8]}>
                        <Col span={24}>
                          <strong>{issue.rule_title || issue.rule}</strong>
                          <div style={{ marginTop: 4 }}>
                            <Tag color={getSeverityColor(issue.severity)} style={{ marginRight: 8 }}>
                              {issue.severity}
                            </Tag>
                            <Tag color="blue" style={{ marginRight: 8 }}>
                              {issue.element_type || issue.element}
                            </Tag>
                            {issue.wcag_level && (
                              <Tag color="purple" style={{ marginRight: 8 }}>
                                {issue.wcag_level}
                              </Tag>
                            )}
                          </div>
                        </Col>
                        <Col span={24}>
                          <p style={{ margin: '8px 0', color: '#666' }}>
                            {issue.description}
                          </p>
                        </Col>
                        <Col span={24}>
                          <strong>Recommendation:</strong>
                          <p style={{ margin: '4px 0', color: '#1890ff' }}>
                            {issue.recommendation}
                          </p>
                        </Col>
                      </Row>
                    </Card>
                  ))}
                </div>
              ) : pdfAnalysisResult.issues && pdfAnalysisResult.issues.length > 0 ? (
                <div>
                  <h5>PDF Analysis Results</h5>
                  {pdfAnalysisResult.issues.map((issue, index) => (
                    <Card 
                      key={index} 
                      size="small" 
                      style={{ marginBottom: 12, borderLeft: `4px solid ${getSeverityColor(issue.severity)}` }}
                    >
                      <Row gutter={[16, 8]}>
                        <Col span={24}>
                          <strong>{issue.rule_title || issue.rule}</strong>
                          <div style={{ marginTop: 4 }}>
                            <Tag color={getSeverityColor(issue.severity)} style={{ marginRight: 8 }}>
                              {issue.severity}
                            </Tag>
                            <Tag color="blue" style={{ marginRight: 8 }}>
                              {issue.element_type || issue.element}
                            </Tag>
                            {issue.wcag_level && (
                              <Tag color="purple" style={{ marginRight: 8 }}>
                                {issue.wcag_level}
                              </Tag>
                            )}
                          </div>
                          <p style={{ margin: '8px 0', color: '#666' }}>
                            {issue.description}
                          </p>
                        </Col>
                        <Col span={24}>
                          <strong>Recommendation:</strong>
                          <p style={{ margin: '4px 0', color: '#1890ff' }}>
                            {issue.recommendation}
                          </p>
                        </Col>
                      </Row>
                    </Card>
                  ))}
                </div>
              ) : (
                <Alert
                  message="No Issues Found"
                  description="This PDF meets WCAG 2.1 accessibility requirements."
                  type="success"
                  showIcon
                />
              )}
            </div>
          )}
        </Modal>
      </Content>
    </Layout>
  );
}

export default App;
