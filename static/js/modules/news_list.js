// 行业资讯列表模块 - 重构版本
class NewsListManager {
    constructor() {
        this.currentPage = 1;
        this.pageSize = 20;
        this.totalCount = 0;
        this.totalPages = 1;
        this.currentNewsData = [];
        this._initialized = false;
        this._eventListenersBound = false;
    }

    // 初始化新闻列表
    init() {
        console.log('初始化行业资讯列表');
        
        // 检查最关键元素是否存在
        const criticalContainer = document.getElementById('news-items-container');
        if (!criticalContainer) {
            console.error('关键容器 news-items-container 不存在');
            return;
        }
        
        // 避免重复初始化
        if (this._initialized) {
            console.log('新闻列表已初始化，跳过重复初始化');
            this.loadNews(); // 只重新加载数据
            return;
        }
        
        this.setupDefaultDates();
        this.bindEventListeners();
        this.loadNews();
        
        this._initialized = true;
    }

    // 设置默认日期为最近两周
    setupDefaultDates() {
        const today = new Date();
        const twoWeeksAgo = new Date(today);
        twoWeeksAgo.setDate(today.getDate() - 14);
        
        const formatDate = (date) => {
            const year = date.getFullYear();
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const day = String(date.getDate()).padStart(2, '0');
            return `${year}-${month}-${day}`;
        };
        
        document.getElementById('news-start-date').value = formatDate(twoWeeksAgo);
        document.getElementById('news-end-date').value = formatDate(today);
    }

    // 绑定事件监听器
    bindEventListeners() {
        // 避免重复绑定事件
        if (this._eventListenersBound) {
            console.log('事件监听器已绑定，跳过重复绑定');
            return;
        }
        
        // 搜索按钮
        document.getElementById('news-search-btn').addEventListener('click', () => this.searchNews());
        
        // 回车搜索
        document.getElementById('news-keyword-search').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.searchNews();
        });
        
        // 重置按钮
        document.getElementById('news-reset-btn').addEventListener('click', () => this.resetSearch());
        
        // 分页控制
        document.getElementById('prev-news-page').addEventListener('click', () => this.prevPage());
        document.getElementById('next-news-page').addEventListener('click', () => this.nextPage());
        

        
        // 页面大小
        document.getElementById('news-page-size').addEventListener('change', (e) => {
            this.pageSize = parseInt(e.target.value);
            this.currentPage = 1;
            this.loadNews();
        });
        
        this._eventListenersBound = true;
    }

    // 搜索新闻
    searchNews() {
        this.currentPage = 1;
        this.loadNews();
    }

    // 重置搜索
    resetSearch() {
        document.getElementById('news-keyword-search').value = '';
        this.setupDefaultDates();
        this.currentPage = 1;
        this.loadNews();
    }

    // 加载新闻数据
    async loadNews() {
        this.showLoadingState();
        
        try {
            const keyword = document.getElementById('news-keyword-search').value.trim();
            const startDate = document.getElementById('news-start-date').value;
            const endDate = document.getElementById('news-end-date').value;
            const currentIndustry = window.currentIndustry || 'ai';
            
            let newsList = [];
            let total = 0;
            
            // 根据行业选择调用不同的API接口
            if (currentIndustry === 'ai') {
                // 人工智能行业 - 使用原有API
                const result = await this.loadAiNews(keyword, startDate, endDate);
                newsList = result.newsList;
                total = result.total;
            } else if (currentIndustry === 'embodied' || currentIndustry === 'low_altitude' || currentIndustry === 'sea' || currentIndustry === 'quantum' || currentIndustry === 'biology' || currentIndustry === 'brain' || currentIndustry === 'material') {
                // 具身智能或低空经济或海洋经济或量子科技或生物制造或脑机接口或新材料 - 使用专题API
                const result = await this.loadSubjectNews(currentIndustry, keyword, startDate, endDate);
                newsList = result.newsList;
                total = result.total;
            } else {
                console.warn('未知行业类型:', currentIndustry);
                this.showEmptyState('未知行业类型');
                return;
            }
            
            // 转换数据格式
            this.currentNewsData = newsList.map((item, index) => ({
                id: item.id || item.articleId || index + 1,
                title: item.title || item.articleTitle || '无标题',
                date: item.publishDate || '未知日期',
                source: item.origin ||  '未知来源',
                author: item.author ||  '未知作者',
                summary: item.summary || '暂无摘要',
                content: item.content || item.summary || '暂无内容',
                tags: item.tags ? (Array.isArray(item.tags) ? item.tags : item.tags.split(',')) : [],
                links: item.links || (item.url ? [{ title: '原文链接', url: item.url }] : []),
                attachments: item.attachments || []
            }));
            
            this.totalCount = total;
            this.totalPages = Math.ceil(total / this.pageSize);
            
            this.updateUI();
            this.updatePagination();
            
        } catch (error) {
            console.error('加载新闻数据失败:', error);
            this.showEmptyState('加载失败，请稍后重试');
        }
    }
    
    // 加载人工智能行业新闻（原有API）
    async loadAiNews(keyword, startDate, endDate) {
        const url = `https://sasac-rc.com/api/sdServerUrl/research/special/universal/getUniSpecialArticleList`;
        const params = new URLSearchParams({
            pageNum: this.currentPage,
            pageSize: this.pageSize
        });
        
        // 根据当前产业设置industryNames参数
        let industryNames = "";
        const currentIndustry = window.currentIndustry || 'ai';
        
        if (currentIndustry === 'ai') {
            industryNames = "";
        } else if (currentIndustry === 'embodied') {
            industryNames = "具身智能";
        } else if (currentIndustry === 'low_altitude') {
            industryNames = "低空经济";
        }
        
        const payload = {
            classificationType: "2,3,1,4,6,0",
            id: "1532332673159036929",
            keyWords: keyword || "",
            startTime: startDate || "2026-03-10",
            endTime: endDate || "2026-03-24",
            coids: "",
            countryNames: "",
            industryNames: industryNames,
            searchAccuracy: "模糊",
            column: "publishDate",
            order: "desc"
        };
        
        console.log('调用AI资讯接口:', `${url}?${params.toString()}`, payload);
        
        const response = await fetch(`${url}?${params.toString()}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        
        const data = await response.json();
        console.log('AI接口响应:', data);
        
        // 调试：检查数据结构
        if (!data) {
            console.warn('接口返回空数据');
            return { newsList: [], total: 0 };
        } else if (data.errorcode !== 0) {
            console.warn('接口返回错误码:', data.errorcode, data.message || '');
            return { newsList: [], total: 0 };
        } else if (!data.model) {
            console.warn('接口返回数据缺少 model 字段');
            return { newsList: [], total: 0 };
        } else if (!data.model.records) {
            console.warn('接口返回数据缺少 records 字段，model 内容:', data.model);
            return { newsList: [], total: 0 };
        }
        
        return {
            newsList: data.model.records || [],
            total: data.model.total || 0
        };
    }
    
    // 加载专题新闻（具身智能/低空经济）
    async loadSubjectNews(industry, keyword, startDate, endDate) {
        const url = `https://clb4yjzx.ciglobal.cn/clb-api/subjectServer/info/subjectPageList`;
        
        // 根据行业设置subjectId
        let subjectId = "";
        if (industry === 'embodied') {
            subjectId = "2043590589800853505"; // 具身智能
        } else if (industry === 'low_altitude') {
            subjectId = "2043592642522591234"; // 低空经济
        } else if (industry === 'sea') {
            subjectId = "2059101745323782145"; // 海洋经济
        } else if (industry === 'quantum') {
            subjectId = "2064547487748272130"; // 量子科技
        } else if (industry === 'biology') {
            subjectId = "2069959956532637698"; // 生物制造
        } else if (industry === 'brain') {
            subjectId = "2070700677342507010"; // 脑机接口
        } else if (industry === 'material') {
            subjectId = "2071534475089096705"; // 新材料
        } else {
            throw new Error(`未知行业类型: ${industry}`);
        }
        
        var searchwords=[{
            "searchLogicRelationship": "",
            "searchInfo": keyword,
            "searchScope": "3",
            "searchAccuracy": "模糊"
            }
        ]
    
        const payload = {
            "searchWordList": keyword ? searchwords : [],
            "fetchFields": [
                "id",
                "title",
                "summary",
                "author",
                "sourceAddress",
                "publishDate",
                "content"
            ],
            "isSubject": "1",
            "column": "publishDate",
            "order": "desc",
            "subjectId": subjectId,  
            "startTime": startDate,
            "endTime": endDate,
            "pageNo": this.currentPage,
            "pageSize": this.pageSize,
            "labelIds": [],
            "labelList": [],
            "category": 1,
            "wordFrequency": [],
            "status": 1,
            "socialCreditCodeList": [],
            "dateFormat": "yyyy-MM-dd"
        }
        
        console.log('调用专题资讯接口:', url, payload);
        let token = sessionStorage.getItem('klbToken');
        //token='eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHAiOjE3NzY2NDc4MzgsInVzZXJuYW1lIjoibHkifQ.GgK5w4E2SdeSA-CRu87H-xcxBZ43PwmY2am0eeggPTg'
       
        const response = await fetch(url, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'x-access-token': token
            },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        
        const data = await response.json();
        console.log('专题接口响应:', data);
        
        // 调试：检查数据结构
        if (!data) {
            console.warn('接口返回空数据');
            return { newsList: [], total: 0 };
        } else if (data.code !== 200) {
            console.warn('接口返回错误码:', data.code, data.msg || '');
            return { newsList: [], total: 0 };
        } else if (!data.result) {
            console.warn('接口返回数据缺少 data 字段');
            return { newsList: [], total: 0 };
        } else if (!data.result.records) {
            console.warn('接口返回数据缺少 records 字段，data 内容:', data.result);
            return { newsList: [], total: 0 };
        }
        
        // 转换数据格式以匹配前端展示需求
        const newsList = data.result.records.map((item, index) => ({
            id: item.id || item.infoId || index + 1,
            title: item.title || '无标题',
            publishDate: item.publishDate.split(' ')[0]|| '未知日期',
            sourceAddress: item.sourceAddress || '未知来源',
            content: item.content || '暂无内容',
            // 为兼容原有字段
            articleId: item.id,
            articleTitle: item.title,
            origin:  item.origin ||  '未知来源',
            summary: item.summary,
            // 保留原始字段，可能用于详情接口
            originalItem: item,
            infoId: item.infoId,
            subjectId: item.subjectId
        }));
        
        return {
            newsList: newsList,
            total: data.result.total || 0
        };
    }

    // 显示加载状态
    showLoadingState() {
        document.getElementById('news-items-container').innerHTML = '';
        document.getElementById('news-empty-state').classList.add('hidden');
        document.getElementById('news-loading-state').classList.remove('hidden');
        document.getElementById('news-list-pagination').classList.add('hidden');
    }

    // 显示空状态
    showEmptyState(message = '暂无资讯数据') {
        const emptyState = document.getElementById('news-empty-state');
        emptyState.querySelector('p').textContent = message;
        emptyState.classList.remove('hidden');
        document.getElementById('news-loading-state').classList.add('hidden');
        document.getElementById('news-list-pagination').classList.add('hidden');
    }

    // 更新UI
    updateUI() {
        const container = document.getElementById('news-items-container');
        
        if (!container) {
            console.error('news-items-container 不存在，无法更新UI');
            return;
        }

        console.log('更新UI，新闻数量:', this.currentNewsData.length);
        container.innerHTML = '';
        console.log('清空容器子元素数量:', container);
        
        if (this.currentNewsData.length === 0) {
            this.showEmptyState();
            return;
        }
        
        document.getElementById('news-loading-state').classList.add('hidden');
        document.getElementById('news-empty-state').classList.add('hidden');
        
        this.currentNewsData.forEach(news => {
            const newsElement = this.createNewsElement(news);
            container.appendChild(newsElement);
        });
        
        console.log('UI更新完成，容器子元素数量:', container.children.length);
    }

    // 创建新闻元素（模仿企业主页样式）
    createNewsElement(news) {
        // console.log('创建新闻元素:', news);
        const newsDiv = document.createElement('div');
        newsDiv.className = 'border border-gray-200 rounded-lg p-4 hover:bg-gray-50 transition';
        
        // 标题和日期区域
        const headerDiv = document.createElement('div');
        headerDiv.className = 'flex justify-between items-start mb-2';
        
        // 标题
        const titleElement = document.createElement('h3');
        titleElement.className = 'font-semibold text-gray-800 text-lg news-title truncate-title';
        titleElement.textContent = news.title;
        titleElement.title = news.title;
        titleElement.addEventListener('click', () => {
            // 存储当前新闻数据到 sessionStorage
            sessionStorage.setItem('currentNewsDetail', JSON.stringify(news));
            // 切换到详情页面
            switchView('news-detail');
        });
        
        // 日期
        const dateElement = document.createElement('span');
        dateElement.className = 'text-sm text-gray-500 news-date';
        dateElement.textContent = news.date;
        
        headerDiv.appendChild(titleElement);
        headerDiv.appendChild(dateElement);
        
        // 摘要
        const summaryDiv = document.createElement('div');
        summaryDiv.className = 'text-gray-600 mb-3 news-summary truncate-summary';
        summaryDiv.textContent = news.summary;
        summaryDiv.title = news.summary;
        
        // 标签和详情按钮区域
        const footerDiv = document.createElement('div');
        footerDiv.className = 'flex justify-between items-center';
        
        // 标签容器
        const tagsDiv = document.createElement('div');
        tagsDiv.className = 'flex gap-2';
        
        if (news.tags && news.tags.length > 0) {
            news.tags.forEach(tag => {
                const tagSpan = document.createElement('span');
                tagSpan.className = 'px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded news-tag';
                tagSpan.textContent = tag;
                tagsDiv.appendChild(tagSpan);
            });
        }
        
        // 详情按钮
        const detailBtn = document.createElement('button');
        detailBtn.className = 'text-blue-600 hover:text-blue-800 text-sm font-medium news-detail-btn';
        detailBtn.innerHTML = '查看详情 <i class="fas fa-chevron-right ml-1"></i>';
        detailBtn.addEventListener('click', () => {
            // 存储当前新闻数据到 sessionStorage
            sessionStorage.setItem('currentNewsDetail', JSON.stringify(news));
            // 切换到详情页面
            switchView('news-detail');
        });
        
        footerDiv.appendChild(tagsDiv);
        footerDiv.appendChild(detailBtn);
        
        newsDiv.appendChild(headerDiv);
        newsDiv.appendChild(summaryDiv);
        newsDiv.appendChild(footerDiv);
        
        return newsDiv;
    }

    // 更新分页UI
    updatePagination() {
        document.getElementById('total-news-count').textContent = this.totalCount;
        document.getElementById('news-current-page-display').textContent = this.currentPage;
        document.getElementById('news-total-pages').textContent = this.totalPages;
        
        const pagination = document.getElementById('news-list-pagination');
        if (pagination) {
            pagination.classList.toggle('hidden', this.totalCount === 0);
        }
        
        // 更新分页按钮状态
        document.getElementById('prev-news-page').disabled = this.currentPage <= 1;
        document.getElementById('next-news-page').disabled = this.currentPage >= this.totalPages;
    }

    // 上一页
    prevPage() {
        if (this.currentPage > 1) {
            this.currentPage--;
            this.loadNews();
        }
    }

    // 下一页
    nextPage() {
        if (this.currentPage < this.totalPages) {
            this.currentPage++;
            this.loadNews();
        }
    }

    // HTML转义函数
    escapeHtml(text) {
        if (typeof text !== 'string') return text;
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, m => map[m]);
    }
}

// 全局实例
const newsListManager = new NewsListManager();

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM内容加载完成，准备监听视图切换事件');
    
    document.addEventListener('viewChanged', function(e) {
        console.log('收到视图切换事件:', e.detail);
        if (e.detail.viewName === 'news-list') {
            console.log('初始化新闻列表视图');
            newsListManager.init();
        }
    });
    
    // 监听产业切换事件
    document.addEventListener('industryChanged', function(e) {
        console.log('收到产业切换事件:', e.detail);
        
        // 检查当前是否在新闻列表视图
        const newsListView = document.getElementById('view-news-list');
        if (newsListView && !newsListView.classList.contains('hidden')) {
            console.log('当前在新闻列表视图，重新加载数据');
            
            // 重置分页到第一页
            newsListManager.currentPage = 1;
            
            // 重新加载新闻数据
            setTimeout(() => {
                newsListManager.loadNews();
            }, 100);
        }
    });
    
    // 调试：延迟初始化以确保所有元素都已加载
    setTimeout(() => {
        if (document.getElementById('view-news-list') && !document.getElementById('view-news-list').classList.contains('hidden')) {
            console.log('页面直接显示新闻列表，延迟初始化');
            newsListManager.init();
        }
    }, 500);
});

// 导出函数供全局使用（向后兼容）
window.searchNews = () => newsListManager.searchNews();
window.resetNewsSearch = () => newsListManager.resetSearch();
window.prevIndustryNewsPage = () => newsListManager.prevPage();
window.nextIndustryNewsPage = () => newsListManager.nextPage();
window.loadNewsList = () => newsListManager.loadNews();
