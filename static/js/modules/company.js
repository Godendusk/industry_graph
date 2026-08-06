// 企业主页模块 - 处理企业主页相关逻辑
// 包含企业基本信息查询、资讯查询等功能

// 当前显示的企业信息
let currentCompany = null;
let currentNewsPage = 1;
let newsTotalPages = 1;

// 清除企业信息和资讯数据
function clearCompanyData() {
    console.log('清除企业信息和资讯数据');
    
    // 清除企业基本信息
    const infoElements = [
        'company-full-name',
        'company-social-credit-code',
        'company-legal-person',
        'company-establish-date',
        'company-registered-capital',
        'company-paid-in-capital',
        'company-operating-status',
        'company-industry',
        'company-registered-address',
        'company-business-scope',
        'company-registration-authority'
    ];
    
    infoElements.forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.textContent = '--';
        }
    });
    
    // 清除徽章状态
    const typeBadgeElement = document.getElementById('company-type-badge');
    if (typeBadgeElement) {
        typeBadgeElement.textContent = '未知';
        typeBadgeElement.className = 'px-3 py-1 rounded-full text-xs font-semibold bg-gray-100 text-gray-800';
    }
    
    const statusBadgeElement = document.getElementById('company-status-badge');
    if (statusBadgeElement) {
        statusBadgeElement.textContent = '正常经营';
        statusBadgeElement.className = 'px-3 py-1 rounded-full text-xs font-semibold bg-green-100 text-green-800';
    }
    
    // 清除资讯列表
    const newsContainer = document.getElementById('company-news-items-container');
    if (newsContainer) {
        newsContainer.innerHTML = `
            <div class="text-center py-12 text-gray-500">
                <i class="fas fa-newspaper text-4xl mb-4 opacity-50"></i>
                <p class="text-lg">暂无企业资讯</p>
                <p class="text-sm mt-2">点击刷新数据获取最新资讯</p>
            </div>
        `;
    }
    
    // 更新资讯计数
    const newsCountElement = document.getElementById('news-count');
    if (newsCountElement) {
        newsCountElement.textContent = '0';
    }
    
    // 隐藏分页
    const newsPaginationElement = document.getElementById('news-pagination');
    if (newsPaginationElement) {
        newsPaginationElement.classList.add('hidden');
    }
    
    // 清除页面标题链接
    const companyPageTitleElement = document.getElementById('company-page-title');
    if (companyPageTitleElement) {
        companyPageTitleElement.innerHTML = '';
        const icon = document.createElement('i');
        icon.className = 'fas fa-building text-blue-600';
        companyPageTitleElement.appendChild(icon);
        companyPageTitleElement.appendChild(document.createTextNode(' '));
        const textSpan = document.createElement('span');
        textSpan.textContent = '企业详情';
        companyPageTitleElement.appendChild(textSpan);
    }
    
    // 清除公司名称
    const companyNameElement = document.getElementById('company-name');
    if (companyNameElement) {
        companyNameElement.textContent = '企业详情';
    }
}

// 显示企业主页
function showCompanyPage(node) {
    console.log('显示企业主页:', node);
    
    // 清除之前的企业数据
    clearCompanyData();
    
    // 重置分页参数到第一页
    currentNewsPage = 1;
    console.log('重置分页参数: currentNewsPage =', currentNewsPage);
    
    // 调试：检查view-company元素的状态
    const companyView = document.getElementById('view-company');
    console.log('切换前view-company状态:', companyView ? companyView.className : '元素不存在');
    
    // 切换到企业主页视图
    switchView('company');
    
    // 再次检查view-company元素的状态
    setTimeout(() => {
        const companyViewAfter = document.getElementById('view-company');
        console.log('切换后view-company状态:', companyViewAfter ? companyViewAfter.className : '元素不存在');
        
        // 强制显示企业详情页面（调试用）
        if (companyViewAfter && companyViewAfter.classList.contains('hidden')) {
            console.warn('view-company仍然有hidden类，强制移除');
            companyViewAfter.classList.remove('hidden');
            companyViewAfter.style.display = 'flex';
            companyViewAfter.style.opacity = '1';
            companyViewAfter.style.visibility = 'visible';
        }
        
        // 额外检查：确保父容器没有隐藏
        let parent = companyViewAfter;
        while (parent) {
            const style = window.getComputedStyle(parent);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
                console.warn(`父元素 ${parent.id || parent.tagName} 被隐藏:`, {
                    display: style.display,
                    visibility: style.visibility,
                    opacity: style.opacity
                });
                parent.style.display = parent.style.display === 'none' ? 'block' : parent.style.display;
                parent.style.visibility = 'visible';
                parent.style.opacity = '1';
            }
            parent = parent.parentElement;
        }
    }, 10);
    
    // 使用setTimeout确保DOM已经渲染完成
    setTimeout(() => {
        // 更新页面标题
        const companyName = node.properties.name || node.id;
        const companyNameElement = document.getElementById('company-name');
        const companyPageTitleElement = document.getElementById('company-page-title');
        
        // 获取信用代码
        const creditCode = node.properties?.credit_code || node.properties?.social_credit_code || node.properties?.creditCode;
        
        // 更新公司名称（保持普通文本）
        if (companyNameElement) {
            companyNameElement.textContent = companyName;
        }
        
        // 更新页面标题（添加链接功能）
        if (companyPageTitleElement) {
            // 清空标题内容
            companyPageTitleElement.innerHTML = '';
            
            // 添加空格
            companyPageTitleElement.appendChild(document.createTextNode(' '));
            
            // 如果有信用代码，创建可点击元素
            if (creditCode) {
                const clickableSpan = document.createElement('span');
                clickableSpan.textContent = companyName;
                clickableSpan.className = 'company-title-link';
                clickableSpan.addEventListener('click', () => {
                    window.open(`https://sasac-rc.com/index.html#/company/home?socialCreditCode=${encodeURIComponent(creditCode)}`, '_blank');
                });
            
                companyPageTitleElement.appendChild(clickableSpan);
            } else {
                // 没有信用代码，显示普通文本
                const textSpan = document.createElement('span');
                textSpan.textContent = companyName;
                companyPageTitleElement.appendChild(textSpan);
            }
        }
        
        if (creditCode) {
            const socialCreditCodeElement = document.getElementById('company-social-credit-code');
            if (socialCreditCodeElement) {
                socialCreditCodeElement.textContent = creditCode;
            }

            // 调用API获取企业详细信息
            fetchCompanyDetail(creditCode);
        } else {
            // 如果没有信用代码，使用节点属性显示基本信息
            updateCompanyBasicInfo(node);
        }
        
        // 加载企业资讯（会使用重置后的currentNewsPage = 1）
        loadCompanyNews(node);
        
        // 保存当前企业信息
        currentCompany = node;

    }, 50); // 50ms延迟确保DOM渲染完成
}

// 调用企业基本信息API
async function fetchCompanyDetail(creditCode) {
    console.log('获取企业详情，信用代码:', creditCode);
    
    // 显示加载状态
    showLoadingState(true);
    
    try {
        // 企业基本信息API
        const apiUrl = `https://sasac-rc.com/api/sdServerUrl/company/enterprise/detail/baseInfo?socialCreditCode=${encodeURIComponent(creditCode)}`;
         
        // 调用API
        const response = await fetch(apiUrl, {});
        
        if (response.ok) {
            const data = await response.json();
            console.log('企业详情API响应:', data);
            
            if (data.code === 200 && data.result) {
                // 更新企业基本信息
                updateCompanyInfoFromAPI(data.result);
            } else {
                console.warn('企业详情API返回错误:', data.message || '未知错误');
                // 使用节点属性显示基本信息
                if (currentCompany) {
                    updateCompanyBasicInfo(currentCompany);
                }
            }
        } else {
            console.error('企业详情API请求失败:', response.status);
            // 使用节点属性显示基本信息
            if (currentCompany) {
                updateCompanyBasicInfo(currentCompany);
            }
        }
    } catch (error) {
        console.error('获取企业详情失败:', error);
        // 使用节点属性显示基本信息
        if (currentCompany) {
            updateCompanyBasicInfo(currentCompany);
        }
    } finally {
        // 隐藏加载状态
        showLoadingState(false);
    }
}

// 从API数据更新企业信息
function updateCompanyInfoFromAPI(apiData) {
    console.log('从API更新企业信息:', apiData);
    
    // 企业名称
    const fullNameElement = document.getElementById('company-full-name');
    if (fullNameElement) fullNameElement.textContent = apiData.name || '--';
    
    // 企业类型
    const category = apiData.enterpriseType || apiData.category || '未知';
    const typeBadgeElement = document.getElementById('company-type-badge');
    if (typeBadgeElement) {
        typeBadgeElement.textContent = category;
        typeBadgeElement.className = getCompanyTypeBadgeClass(category);
    }
    
    // 法定代表人
    const legalPersonElement = document.getElementById('company-legal-person');
    if (legalPersonElement) legalPersonElement.textContent = apiData.legalPerson || apiData.legal_person || '--';
    
    // 成立日期
    const establishDateElement = document.getElementById('company-establish-date');
    if (establishDateElement) establishDateElement.textContent = apiData.incorporationDate || '--';
    
    // 注册资本
    const registeredCapitalElement = document.getElementById('company-registered-capital');
    if (registeredCapitalElement) registeredCapitalElement.textContent = apiData.capital || '--';
    
    // 实缴资本
    const paidInCapitalElement = document.getElementById('company-paid-in-capital');
    if (paidInCapitalElement) paidInCapitalElement.textContent = apiData.paidCapital || '--';
    
    // 经营状态
    const operatingStatus = apiData.registerStatus || '正常经营';
    const operatingStatusElement = document.getElementById('company-operating-status');
    const statusBadgeElement = document.getElementById('company-status-badge');
    if (operatingStatusElement) operatingStatusElement.textContent = operatingStatus;
    if (statusBadgeElement) {
        statusBadgeElement.textContent = operatingStatus;
        statusBadgeElement.className = getOperatingStatusBadgeClass(operatingStatus);
    }
    
    // 所属行业
    const industryElement = document.getElementById('company-industry');
    if (industryElement) industryElement.textContent = apiData.industry || '--';
    
    // 注册地址
    const registeredAddressElement = document.getElementById('company-registered-address');
    if (registeredAddressElement) registeredAddressElement.textContent = apiData.address || '--';
    
    // 经营范围
    const businessScopeElement = document.getElementById('company-business-scope');
    if (businessScopeElement) businessScopeElement.textContent = apiData.businessRange || '--';
    
    // 登记机关
    const registrationAuthorityElement = document.getElementById('company-registration-authority');
    if (registrationAuthorityElement) registrationAuthorityElement.textContent = apiData.registerDepartment || '--';
}

// 使用节点属性更新企业基本信息（备用）
function updateCompanyBasicInfo(node) {
    const properties = node.properties || {};
    
    // 企业名称
    const fullNameElement = document.getElementById('company-full-name');
    if (fullNameElement) fullNameElement.textContent = properties.name || '--';
    
    // 企业类型
    const category = properties.category || '未知';
    const typeBadgeElement = document.getElementById('company-type-badge');
    if (typeBadgeElement) {
        typeBadgeElement.textContent = category;
        typeBadgeElement.className = getCompanyTypeBadgeClass(category);
    }
    
    // 法定代表人
    const legalPersonElement = document.getElementById('company-legal-person');
    if (legalPersonElement) legalPersonElement.textContent = properties.legal_person || properties.legalPerson || '--';
    
    // 成立日期
    const establishDateElement = document.getElementById('company-establish-date');
    if (establishDateElement) establishDateElement.textContent = properties.establish_date || properties.establishDate || '--';
    
    // 注册资本
    const registeredCapitalElement = document.getElementById('company-registered-capital');
    if (registeredCapitalElement) registeredCapitalElement.textContent = properties.registered_capital || properties.registeredCapital || '--';
    
    // 实缴资本
    const paidInCapitalElement = document.getElementById('company-paid-in-capital');
    if (paidInCapitalElement) paidInCapitalElement.textContent = properties.paid_in_capital || properties.paidInCapital || '--';
    
    // 经营状态
    const operatingStatus = properties.operating_status || properties.operatingStatus || '正常经营';
    const operatingStatusElement = document.getElementById('company-operating-status');
    const statusBadgeElement = document.getElementById('company-status-badge');
    if (operatingStatusElement) operatingStatusElement.textContent = operatingStatus;
    if (statusBadgeElement) {
        statusBadgeElement.textContent = operatingStatus;
        statusBadgeElement.className = getOperatingStatusBadgeClass(operatingStatus);
    }
    
    // 所属行业
    const industryElement = document.getElementById('company-industry');
    if (industryElement) industryElement.textContent = properties.industry || '--';
    
    // 注册地址
    const registeredAddressElement = document.getElementById('company-registered-address');
    if (registeredAddressElement) registeredAddressElement.textContent = properties.registered_address || properties.registeredAddress || '--';
    
    // 经营范围
    const businessScopeElement = document.getElementById('company-business-scope');
    if (businessScopeElement) businessScopeElement.textContent = properties.business_scope || properties.businessScope || '--';
    
    // 登记机关
    const registrationAuthorityElement = document.getElementById('company-registration-authority');
    if (registrationAuthorityElement) registrationAuthorityElement.textContent = properties.registration_authority || properties.registrationAuthority || '--';
}

// 获取企业类型徽章样式
function getCompanyTypeBadgeClass(category) {
    const baseClass = "px-3 py-1 rounded-full text-xs font-semibold";
    switch(category) {
        case '央企/国企':
            return `${baseClass} bg-red-100 text-red-800`;
        case '外资企业':
            return `${baseClass} bg-green-100 text-green-800`;
        case '民营企业':
            return `${baseClass} bg-blue-100 text-blue-800`;
        default:
            return `${baseClass} bg-gray-100 text-gray-800`;
    }
}

// 获取经营状态徽章样式
function getOperatingStatusBadgeClass(status) {
    const baseClass = "px-3 py-1 rounded-full text-xs font-semibold";
    if (status.includes('正常') || status.includes('存续') || status.includes('在营')) {
        return `${baseClass} bg-green-100 text-green-800`;
    } else if (status.includes('注销') || status.includes('吊销')) {
        return `${baseClass} bg-red-100 text-red-800`;
    } else if (status.includes('停业') || status.includes('清算')) {
        return `${baseClass} bg-yellow-100 text-yellow-800`;
    } else {
        return `${baseClass} bg-gray-100 text-gray-800`;
    }
}

// 显示/隐藏加载状态
function showLoadingState(show) {
    const loadingElement = document.getElementById('company-loading');
    if (!loadingElement) {
        // 如果没有加载元素，创建一个
        const loadingDiv = document.createElement('div');
        loadingDiv.id = 'company-loading';
        loadingDiv.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 hidden';
        loadingDiv.innerHTML = `
            <div class="bg-white rounded-lg p-6 flex flex-col items-center">
                <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mb-4"></div>
                <p class="text-gray-700">加载企业信息中...</p>
            </div>
        `;
        document.body.appendChild(loadingDiv);
    }
    
    const element = document.getElementById('company-loading');
    if (show) {
        element.classList.remove('hidden');
    } else {
        element.classList.add('hidden');
    }
}

// 加载企业资讯
function loadCompanyNews(node) {
    console.log('加载企业资讯:', node);
    
    // 获取信用代码
    const creditCode = node.properties?.credit_code || node.properties?.social_credit_code || node.properties?.creditCode;
    if (creditCode) {
        // 调用API获取企业资讯
        fetchCompanyNews(creditCode, currentNewsPage);
    } 
}

// 调用企业资讯API
async function fetchCompanyNews(creditCode, page = 1) {
    console.log('获取企业资讯，信用代码:', creditCode, '页码:', page);
    
    try {
        // 企业资讯分页列表API
        const apiUrl = `https://sasac-rc.com/api/sdServerUrl/channel/datapull/column/queryInfoList`;

        // 准备请求参数
        const requestBody ={
            "checkStatusList": [
                1
            ],
            "column": "publishDate",
            "columnId": "2011706553489526786",
            "deleteFlag": 0,
            "order": "desc",
            "pageNo": page,
            "pageSize": 10,
            "searchAccuracy": "精确",
            "searchInfo": "",
            "searchScope": 2,
            "socialCreditCode": creditCode,
            "ynChannel": 1,
            "sortType": "publishDate",
            "ynProject": 0
        }
        
        // 准备请求头
        const headers = {
            'Content-Type': 'application/json'
        };
        
        // 调用API
        const response = await fetch(apiUrl, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(requestBody)
        });
        
        if (response.ok) {
            const data = await response.json();
            console.log('企业资讯API响应:', data);
            
            // 检查API响应是否成功
            const isSuccess = data.code === 200 || data.code === 0 || data.status === 'success' || data.success === true;
            
            if (isSuccess) {
                // 获取实际数据
                const resultData = data.result || data.data || data;
                
                // 调试：打印API返回的数据结构
                console.log('API 返回的数据结构:', JSON.stringify(resultData, null, 2));
                
                // 更新资讯列表
                updateNewsListFromAPI(resultData);
            } else {
                console.warn('企业资讯API返回错误:', data.message || data.msg || '未知错误');
               
            }
        } else {
            console.error('企业资讯API请求失败:', response.status);
        }
    } catch (error) {
        console.error('获取企业资讯失败:', error);
    }
}

// 从API数据更新资讯列表
function updateNewsListFromAPI(apiData) {
    console.log('从API更新资讯列表 - 完整数据:', apiData);
    

    let newsList = apiData.records;
    let total = apiData.total;
    
    // 更新分页信息
    newsTotalPages = apiData.pages;
    currentNewsPage = apiData.current || 1;
    
    console.log('分页信息 - newsTotalPages:', newsTotalPages, 'currentNewsPage:', currentNewsPage);
    
    // 转换数据格式
    const formattedNews = newsList.map(item => {
        // 调试：查看原始数据结构
        console.log('原始资讯项:', item);
        
        const formattedItem = {
            id: item.id || item.infoId || item.newsId || null,
            title: item.title || item.infoTitle || item.infoTitle || '无标题',
            date: item.publishTime || item.createTime || item.date || item.publishDate || '未知日期',
            summary: item.content || item.summary || item.abstract || item.infoContent || '暂无摘要',
            tags: item.tags || item.keywords || item.label || []
        };
        
        // 如果 tags 是字符串，转换为数组
        if (typeof formattedItem.tags === 'string') {
            formattedItem.tags = formattedItem.tags.split(',').filter(tag => tag.trim());
        }
        
        console.log('转换后的资讯项:', formattedItem);
        return formattedItem;
    });
    
    console.log('最终转换的资讯列表:', formattedNews);
    
    // 更新UI
    updateNewsList(formattedNews,total);
    
    // 更新分页UI
    updatePaginationUI();
}

// 显示模拟资讯数据（备用）
function showMockNews() {
    console.log('显示模拟资讯数据');
    
    const mockNews = [
        {
            title: "企业获得新一轮融资",
            date: "2024-03-15",
            summary: "该公司近日宣布完成新一轮融资，融资金额达数亿元，将用于技术研发和市场拓展。",
            tags: ["融资", "投资"]
        },
        {
            title: "发布新产品线",
            date: "2024-03-10",
            summary: "企业正式发布AI智能产品线，涵盖多个应用场景，预计将提升市场竞争力。",
            tags: ["产品", "AI"]
        },
        {
            title: "与行业巨头达成战略合作",
            date: "2024-03-05",
            summary: "该公司与行业领先企业达成战略合作协议，将在技术研发和市场推广方面深度合作。",
            tags: ["合作", "战略"]
        }
    ];
    
    // 更新资讯列表
    updateNewsList(mockNews);
}

// 更新资讯列表UI
function updateNewsList(newsList,total) {
    
    const container = document.getElementById('company-news-items-container');
    const template = document.querySelector('.news-item-template');
    
    // 清空容器
    container.innerHTML = '';
    
    if (!newsList || newsList.length === 0) {
        console.log('资讯列表为空，显示无数据提示');
        container.innerHTML = `
            <div class="text-center py-12 text-gray-500">
                <i class="fas fa-newspaper text-4xl mb-4 opacity-50"></i>
                <p class="text-lg">暂无企业资讯</p>
                <p class="text-sm mt-2">点击刷新数据获取最新资讯</p>
            </div>
        `;
        const newsCountElement = document.getElementById('news-count');
        const newsPaginationElement = document.getElementById('news-pagination');
        if (newsCountElement) newsCountElement.textContent = '0';
        if (newsPaginationElement) newsPaginationElement.classList.add('hidden');
        return;
    }
    

    
    // 添加资讯项
    newsList.forEach((news, index) => {
        console.log(`处理第 ${index + 1} 个资讯项:`, news);
        
        const clone = template.cloneNode(true);
        clone.classList.remove('hidden');

        
        // 填充数据
        const titleElement = clone.querySelector('.news-title');
        const dateElement = clone.querySelector('.news-date');
        const summaryElement = clone.querySelector('.news-summary');
        
        console.log('找到的元素:', { titleElement, dateElement, summaryElement });
        
        if (titleElement) {
            // 设置完整标题，CSS会处理截断
            titleElement.textContent = news.title;
            // 添加title属性显示完整标题（鼠标悬停时显示）
            titleElement.title = news.title;
            console.log('设置标题:', news.title);
        }
        if (dateElement) {
            dateElement.textContent = news.date;
            console.log('设置日期:', news.date);
        }
        if (summaryElement) {
            // 设置完整摘要，CSS会处理截断
            summaryElement.textContent = news.summary;
            // 添加title属性显示完整摘要（鼠标悬停时显示）
            summaryElement.title = news.summary;
            console.log('设置摘要:', news.summary);
        }
        
        // 添加标签
        const tagsContainer = clone.querySelector('.flex.gap-2');
        console.log('标签容器:', tagsContainer);
        
        if (tagsContainer) {
            tagsContainer.innerHTML = '';
            if (news.tags && news.tags.length > 0) {
                console.log('添加标签:', news.tags);
                news.tags.forEach(tag => {
                    const tagSpan = document.createElement('span');
                    tagSpan.className = 'px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded';
                    tagSpan.textContent = tag;
                    tagsContainer.appendChild(tagSpan);
                });
            } else {
                console.log('资讯项没有标签');
            }
        } else {
            console.warn('未找到标签容器 .flex.gap-2');
        }
        
        // 添加详情按钮事件
        const detailBtn = clone.querySelector('.news-detail-btn');
        if (detailBtn) {
            detailBtn.addEventListener('click', () => showNewsDetail(news));
        }
        
        container.appendChild(clone);
    });
    
    // 更新统计信息
    const newsCountElement = document.getElementById('news-count');
    if (newsCountElement) newsCountElement.textContent = total;
    
    // 显示分页（如果有多个页面）
    const newsPaginationElement = document.getElementById('news-pagination');

    if (newsPaginationElement && newsTotalPages > 1) {
        newsPaginationElement.classList.remove('hidden');
    }
}

// 调用资讯详情API
async function fetchNewsDetail(newsId) {
    console.log('获取资讯详情，ID:', newsId);
    
    try {
        // 资讯详情API
        const apiUrl = `https://sasac-rc.com/api/sdServerUrl/channel/datapull/column/queryById?id=${encodeURIComponent(newsId)}`;
        
        // 调用API
        const response = await fetch(apiUrl, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            console.log('资讯详情API响应:', data);
            
            // 检查API响应是否成功
            const isSuccess = data.code === 200 || data.code === 0 || data.status === 'success' || data.success === true;
            
            if (isSuccess) {
                // 获取实际数据
                const resultData = data.result || data.data || data;
                console.log('资讯详情数据:', resultData);
                return resultData;
            } else {
                console.warn('资讯详情API返回错误:', data.message || data.msg || '未知错误');
                return null;
            }
        } else {
            console.error('资讯详情API请求失败:', response.status);
            return null;
        }
    } catch (error) {
        console.error('获取资讯详情失败:', error);
        return null;
    }
}

// 显示资讯详情页面
function showNewsDetail(news) {
    console.log('显示企业资讯详情:', news);
    
    // 保存当前资讯到 sessionStorage，使用企业专用的 key
    sessionStorage.setItem('currentCompanyNewsDetail', JSON.stringify(news));
    
    // 切换到企业资讯详情视图
    switchView('company-news-detail');
}

// 更新分页UI
function updatePaginationUI() {
    const currentPageElement = document.getElementById('current-page');
    const totalPagesElement = document.getElementById('total-pages');
    
    if (currentPageElement) currentPageElement.textContent = currentNewsPage;
    if (totalPagesElement) totalPagesElement.textContent = newsTotalPages;
    
    // 更新按钮状态
    const prevBtn = document.querySelector('button[onclick="prevNewsPage()"]');
    const nextBtn = document.querySelector('button[onclick="nextNewsPage()"]');
    
    if (prevBtn) {
        prevBtn.disabled = currentNewsPage <= 1;
    }
    if (nextBtn) {
        nextBtn.disabled = currentNewsPage >= newsTotalPages;
    }
}

// 分页控制函数
function prevNewsPage() {
    if (currentNewsPage > 1) {
        currentNewsPage--;
        if (currentCompany) {
            loadCompanyNews(currentCompany);
        }
    }
}

function nextNewsPage() {
    if (currentNewsPage < newsTotalPages) {
        currentNewsPage++;
        if (currentCompany) {
            loadCompanyNews(currentCompany);
        }
    }
}



// 刷新企业数据
function refreshCompanyData() {
    if (!currentCompany) return;
    
    // 重新加载企业信息
    const creditCode = currentCompany.properties?.credit_code || currentCompany.properties?.social_credit_code || currentCompany.properties?.creditCode;
    if (creditCode) {
        fetchCompanyDetail(creditCode);
    }
    
    // 重新加载资讯
    loadCompanyNews(currentCompany);
}

// 导出函数供其他模块使用
window.showCompanyPage = showCompanyPage;
window.refreshCompanyData = refreshCompanyData;
window.prevNewsPage = prevNewsPage;
window.nextNewsPage = nextNewsPage;