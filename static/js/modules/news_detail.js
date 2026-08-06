// 资讯详情模块 - 处理资讯详情页面相关逻辑

// 复用公司页面的资讯详情API调用函数
async function fetchNewsDetail(newsId) {
    console.log('获取资讯详情，ID:', newsId);
    
    try {
        // 获取当前行业
        const currentIndustry = window.currentIndustry || 'ai';
        console.log('当前行业:', currentIndustry);
        
        // 根据行业选择不同的数据获取方式
        if (currentIndustry === 'ai') {
            // 人工智能产业 - 使用原API
            let apiUrl = `https://sasac-rc.com/api/sdServerUrl/channel/datapull/column/queryById?id=${encodeURIComponent(newsId)}`;
            console.log('使用原资讯详情接口:', apiUrl);
            
            let requestOptions = {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            };
            
            // 调用API
            const response = await fetch(apiUrl, requestOptions);
            
            if (response.ok) {
                try {
                    const responseText = await response.text();
                    console.log('API响应文本长度:', responseText.length);
                    console.log('API响应文本前200字符:', responseText.substring(0, 200));
                    
                    if (!responseText || responseText.trim() === '') {
                        console.warn('API返回空响应');
                        return null;
                    }
                    
                    const data = JSON.parse(responseText);
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
                } catch (jsonError) {
                    console.error('解析API响应JSON失败:', jsonError);
                    console.error('响应内容可能不是有效的JSON格式');
                    return null;
                }
            } else {
                console.error('资讯详情API请求失败:', response.status, response.statusText);
                try {
                    const errorText = await response.text();
                    console.error('错误响应内容:', errorText.substring(0, 500));
                } catch (e) {
                    console.error('无法读取错误响应内容:', e);
                }
                return null;
            }
        } else {
            // 其他产业（具身智能或低空经济）- 不使用API，只使用sessionStorage
            console.log('其他产业，使用sessionStorage数据');
            
            // 从sessionStorage获取原始新闻数据
            const newsData = sessionStorage.getItem('currentNewsDetail');
            if (newsData) {
                try {
                    const news = JSON.parse(newsData);
                    console.log('从sessionStorage获取的新闻数据:', news);
                    
                    // 检查新闻ID是否匹配
                    if (news.id === newsId || news.articleId === newsId || news.infoId === newsId) {
                        // 返回sessionStorage中的数据
                        return news;
                    } else {
                        console.warn('sessionStorage中的新闻ID不匹配:', news.id, '期望:', newsId);
                        return null;
                    }
                } catch (error) {
                    console.error('解析sessionStorage数据失败:', error);
                    return null;
                }
            } else {
                console.warn('sessionStorage中没有找到新闻数据');
                return null;
            }
        }
    } catch (error) {
        console.error('获取资讯详情失败:', error);
        return null;
    }
}

class NewsDetailManager {
    constructor() {
        this.currentNews = null;
        this.newsId = null;
    }

    // 初始化资讯详情页面
    init() {
        console.log('初始化资讯详情页面');
        
        // 优先尝试从 sessionStorage 获取新闻ID
        const newsData = sessionStorage.getItem('currentNewsDetail');
        if (newsData) {
            try {
                const news = JSON.parse(newsData);
                this.newsId = news.id;
                if (this.newsId) {
                    // 通过接口查询资讯详情
                    this.loadNewsDetailFromAPI(this.newsId);
                } else {
                    // 如果没有ID，直接使用缓存的数据
                    this.currentNews = news;
                    this.renderDetail();
                }
            } catch (error) {
                console.error('解析新闻数据失败:', error);
                this.showErrorMessage('资讯数据加载失败');
            }
        } else {
            console.warn('没有找到资讯数据');
            this.showErrorMessage('未找到资讯数据，请返回列表页重新选择');
        }
    }

    // 通过API加载资讯详情
    async loadNewsDetailFromAPI(newsId) {
        this.showLoadingState();
        
        try {
            const newsDetail = await fetchNewsDetail(newsId);
            if (newsDetail) {
                // 获取当前行业
                const currentIndustry = window.currentIndustry || 'ai';
                
                if (currentIndustry === 'ai') {
                    // AI产业 - 需要合并API返回的数据和sessionStorage中的原始数据
                    const originalNewsData = sessionStorage.getItem('currentNewsDetail');
                    let originalNews = {};
                    if (originalNewsData) {
                        try {
                            originalNews = JSON.parse(originalNewsData);
                        } catch (e) {
                            console.warn('解析原始新闻数据失败:', e);
                        }
                    }
                    
                    // 合并数据：优先使用API返回的详细数据，保留原始数据中的必要字段
                    const mergedNews = {
                        ...originalNews,
                        ...newsDetail,
                        id: newsId,
                        title: newsDetail.title || newsDetail.articleTitle || originalNews.title || '无标题',
                        date: newsDetail.publishDate || newsDetail.createTime || newsDetail.date || originalNews.date || '未知日期',
                        source: newsDetail.origin || newsDetail.mediaName || newsDetail.source || originalNews.source || '未知来源',
                        author: newsDetail.author || newsDetail.creator || newsDetail.author || originalNews.author || '未知作者',
                        summary: newsDetail.summary || newsDetail.brief || originalNews.summary || '暂无摘要',
                        content: newsDetail.content || newsDetail.infoContent || newsDetail.fullContent || newsDetail.articleContent || originalNews.content || originalNews.summary || '暂无内容',
                        tags: newsDetail.tags ? (Array.isArray(newsDetail.tags) ? newsDetail.tags : 
                               (typeof newsDetail.tags === 'string' ? newsDetail.tags.split(',') : [])) : 
                               (originalNews.tags || []),
                        links: newsDetail.links || newsDetail.relatedLinks || 
                               (newsDetail.url ? [{ title: '原文链接', url: newsDetail.url }] : []) ||
                               (originalNews.links || []),
                        attachments: newsDetail.attachments || newsDetail.files || (originalNews.attachments || [])
                    };
                    
                    this.currentNews = mergedNews;
                } else {
                    // 其他产业 - newsDetail已经是完整的新闻对象（从sessionStorage获取）
                    this.currentNews = newsDetail;
                }
                
                this.renderDetail();
            } else {
                // API调用失败，回退到缓存数据
                const newsData = sessionStorage.getItem('currentNewsDetail');
                if (newsData) {
                    try {
                        this.currentNews = JSON.parse(newsData);
                        this.renderDetail();
                    } catch (error) {
                        console.error('回退到缓存数据失败:', error);
                        this.showErrorMessage('资讯详情加载失败，请稍后重试');
                    }
                } else {
                    this.showErrorMessage('资讯详情加载失败，请稍后重试');
                }
            }
        } catch (error) {
            console.error('加载资讯详情失败:', error);
            // 回退到缓存数据
            const newsData = sessionStorage.getItem('currentNewsDetail');
            if (newsData) {
                try {
                    this.currentNews = JSON.parse(newsData);
                    this.renderDetail();
                } catch (error) {
                    console.error('回退到缓存数据失败:', error);
                    this.showErrorMessage('资讯详情加载失败，请稍后重试');
                }
            } else {
                this.showErrorMessage('资讯详情加载失败，请稍后重试');
            }
        }
    }

    // 显示加载状态
    showLoadingState() {
        const content = document.getElementById('news-detail-content');
        if (content) {
            content.innerHTML = `
                <div class="text-center py-12">
                    <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
                    <p class="text-lg text-gray-700">正在加载资讯详情...</p>
                </div>
            `;
        }
    }

    // 渲染详情内容
    renderDetail() {
        const content = document.getElementById('news-detail-content');
        if (!content || !this.currentNews) {
            return;
        }

        const news = this.currentNews;
        
        content.innerHTML = `
            <div class="space-y-6">
                <!-- 标题和元信息 -->
                <div class="border-b border-gray-200 pb-4">
                    <h2 class="text-2xl font-bold text-gray-800 mb-3">${this.escapeHtml(news.title || '无标题')}</h2>
                    <div class="flex flex-wrap gap-4 text-sm text-gray-600">
                        <div class="flex items-center gap-1">
                            <i class="far fa-calendar-alt"></i>
                            <span>发布日期: ${this.escapeHtml(news.date || '未知日期')}</span>
                        </div>
                        ${news.source && news.source !== '未知来源' ? `
                        <div class="flex items-center gap-1">
                            <i class="fas fa-newspaper"></i>
                            <span>来源: ${this.escapeHtml(news.source)}</span>
                        </div>
                        ` : ''}
                        ${news.author && news.author !== '未知作者' ? `
                        <div class="flex items-center gap-1">
                            <i class="fas fa-user"></i>
                            <span>作者: ${this.escapeHtml(news.author)}</span>
                        </div>
                        ` : ''}
                    </div>
                </div>
                
                <!-- 标签 -->
                ${news.tags && news.tags.length > 0 ? `
                <div class="flex flex-wrap gap-2">
                    ${news.tags.map(tag => `<span class="px-3 py-1 bg-blue-100 text-blue-800 text-sm rounded-full">${this.escapeHtml(tag)}</span>`).join('')}
                </div>
                ` : ''}
                
                <!-- 内容 -->
                <div class="prose max-w-none">
                    <div class="text-gray-700 leading-relaxed">${this.renderSafeHtml(news.content || news.summary || '暂无内容')}</div>
                </div>
                
                <!-- 相关链接 -->
                ${news.links && news.links.length > 0 ? `
                <div class="border-t border-gray-200 pt-4">
                    <h3 class="text-lg font-semibold text-gray-700 mb-3">相关链接</h3>
                    <div class="space-y-2">
                        ${news.links.map(link => `
                        <a href="${this.escapeHtml(link.url)}" target="_blank" class="flex items-center gap-2 text-blue-600 hover:text-blue-800">
                            <i class="fas fa-external-link-alt text-sm"></i>
                            <span class="truncate">${this.escapeHtml(link.title || link.url)}</span>
                        </a>
                        `).join('')}
                    </div>
                </div>
                ` : ''}
                
                <!-- 附件 -->
                ${news.attachments && news.attachments.length > 0 ? `
                <div class="border-t border-gray-200 pt-4">
                    <h3 class="text-lg font-semibold text-gray-700 mb-3">附件</h3>
                    <div class="space-y-2">
                        ${news.attachments.map(attachment => `
                        <div class="flex items-center gap-2 p-3 bg-gray-50 rounded-lg">
                            <i class="fas fa-paperclip text-gray-400"></i>
                            <span class="flex-1 text-gray-700">${this.escapeHtml(attachment.name || '未命名文件')}</span>
                            <a href="${this.escapeHtml(attachment.url)}" class="text-blue-600 hover:text-blue-800 text-sm font-medium">
                                <i class="fas fa-download mr-1"></i>下载
                            </a>
                        </div>
                        `).join('')}
                    </div>
                </div>
                ` : ''}
            </div>
        `;
    }

    // 显示错误信息
    showErrorMessage(message) {
        const content = document.getElementById('news-detail-content');
        if (content) {
            content.innerHTML = `
                <div class="text-center py-12">
                    <i class="fas fa-exclamation-triangle text-4xl text-yellow-500 mb-4"></i>
                    <p class="text-lg text-gray-700">${message}</p>
                    <button onclick="switchView('news-list')" class="mt-4 px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg text-sm font-medium transition">
                        返回资讯列表
                    </button>
                </div>
            `;
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

    // 安全渲染HTML内容（用于API返回的富文本内容）
    renderSafeHtml(htmlContent) {
        if (typeof htmlContent !== 'string') {
            return this.escapeHtml(htmlContent);
        }
        
        // 如果内容包含HTML标签，直接返回（假设API返回的内容是安全的）
        if (htmlContent.trim().startsWith('<') && htmlContent.includes('>')) {
            return htmlContent;
        }
        
        // 否则进行HTML转义
        return this.escapeHtml(htmlContent);
    }
}

// 全局实例
const newsDetailManager = new NewsDetailManager();

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    document.addEventListener('viewChanged', function(e) {
        if (e.detail.viewName === 'news-detail') {
            console.log('初始化资讯详情视图');
            newsDetailManager.init();
        }
    });
});

// 导出函数供全局使用
window.loadNewsDetail = () => newsDetailManager.init();