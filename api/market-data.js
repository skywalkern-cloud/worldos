// 投资监控仪表盘 - 市场数据API
// 使用JS直接调用外部API，无需Python

export default async function handler(req, res) {
  try {
    const PROXY = 'http://127.0.0.1:7890';
    
    // 辅助函数：获取腾讯实时数据
    async function fetchWithProxy(url) {
      try {
        const response = await fetch(url, { 
          timeout: 5000,
          headers: { 'Referer': 'https://finance.qq.com/' }
        });
        return await response.text();
      } catch (e) {
        console.log('fetch error:', e.message);
        return null;
      }
    }
    
    // 获取大盘指数
    const data = {
      timestamp: new Date().toISOString(),
      data: {},
      source: '腾讯财经API'
    };
    
    // 尝试获取上证指数
    const shText = await fetchWithProxy('https://qt.gtimg.cn/q=s_sh000001');
    if (shText && shText.includes('~')) {
      const shParts = shText.split('~');
      data.data.shanghai = parseFloat(shParts[3]) || 0;
      data.data.shanghaiChange = parseFloat(shParts[4]) || 0;
    }
    
    // 深证成指
    const szText = await fetchWithProxy('https://qt.gtimg.cn/q=s_sz399001');
    if (szText && szText.includes('~')) {
      const szParts = szText.split('~');
      data.data.szindex = parseFloat(szParts[3]) || 0;
      data.data.szindexChange = parseFloat(szParts[4]) || 0;
    }
    
    // 创业板
    const cyText = await fetchWithProxy('https://qt.gtimg.cn/q=s_sz399006');
    if (cyText && cyText.includes('~')) {
      const cyParts = cyText.split('~');
      data.data.chinese = parseFloat(cyParts[3]) || 0;
      data.data.chineseChange = parseFloat(cyParts[4]) || 0;
    }
    
    // 设置CORS
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.status(200).json(data);
    
  } catch (error) {
    console.error('Error:', error);
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.status(200).json({
      timestamp: new Date().toISOString(),
      data: {},
      source: 'error'
    });
  }
}