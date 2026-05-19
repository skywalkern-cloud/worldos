import { useState, useEffect } from 'react'
import { useMarketData, MarketDataSkeleton } from './hooks/useMarketData'
import './index.css'

// ====== V3.0 类型定义 ======
interface IndicatorScore {
  id: string
  name: string
  value: string
  score: number  // +1, 0, -1
  reason: string
  region: string
}

interface DimensionScore {
  id: string
  name: string
  icon: string
  score: number  // F_维度 = 正分 - 负分
  indicators: IndicatorScore[]
}

interface IASResult {
  totalScore: number  // IAS = sum(F_维度)
  signal: string      // 强烈买入/买入/持有/减仓/清仓
  position: string   // 仓位建议
  dimensions: DimensionScore[]
}

// ====== V3.0 数据转换 ======
function transformDataV3(raw: any): IASResult {
  const data = raw.data || {}
  const meta = raw.meta || {}

  // 6大维度20指标 V3.0 配置（匹配后端20个实际字段）
  // AI/技术指标暂无数据，默认0分
  const dimensionConfigs = [
    {
      id: 'economic',
      name: '经济产出',
      icon: '📈',
      fields: [
        { key: 'chinaGdp', name: '中国GDP增速', region: '🇨🇳', getScore: (v: number) => v > 5 ? 1 : (v < 4 ? -1 : 0) },
        { key: 'chinaPmi', name: '中国PMI', region: '🇨🇳', getScore: (v: number) => v > 50 ? 1 : -1 },
        { key: 'usGdp', name: '美国GDP增速', region: '🇺🇸', getScore: (v: number) => v > 2 ? 1 : (v < 0 ? -1 : 0) },
        { key: 'servicePmi', name: '中国服务业PMI', region: '🇨🇳', getScore: (v: number) => v > 50 ? 1 : -1 }
      ]
    },
    {
      id: 'inflation',
      name: '通胀与价格',
      icon: '💰',
      fields: [
        { key: 'cpi', name: '中国CPI', region: '🇨🇳', getScore: (v: number) => v > 0 && v < 3 ? 1 : (v > 5 ? -1 : 0) },
        { key: 'ppi', name: '中国PPI', region: '🇨🇳', getScore: (v: number) => v > 0 ? 1 : (v < -3 ? -1 : 0) },
        { key: 'usCpi', name: '美国CPI', region: '🇺🇸', getScore: (v: number) => v > 0 && v < 3 ? 1 : (v > 5 ? -1 : 0) },
        { key: 'corePce', name: '美国核心PCE', region: '🇺🇸', getScore: (v: number) => v < 2 ? 1 : (v > 3 ? -1 : 0) }
      ]
    },
    {
      id: 'money',
      name: '货币与信用',
      icon: '🏦',
      fields: [
        { key: 'lpr', name: 'LPR利率', region: '🇨🇳', getScore: (v: number) => v < 4 ? 1 : (v > 5 ? -1 : 0) },
        { key: 'dr007', name: 'DR007', region: '🇨🇳', getScore: (v: number) => v < 2 ? 1 : (v > 3 ? -1 : 0) },
        { key: 'm2', name: 'M2货币供应', region: '🇨🇳', getScore: (v: number) => v > 10 ? 1 : (v < 8 ? -1 : 0) },
        { key: 'fedRate', name: '美联储利率', region: '🇺🇸', getScore: (v: number) => v < 3 ? 1 : (v > 5 ? -1 : 0) }
      ]
    },
    {
      id: 'risk',
      name: '风险与不确定性',
      icon: '⚠️',
      fields: [
        { key: 'vix', name: 'VIX恐慌指数', region: '🇺🇸', getScore: (v: number) => v < 20 ? 1 : (v > 30 ? -1 : 0) },
        { key: 'epu', name: '经济政策不确定性', region: '🌐', getScore: (v: number) => v < 100 ? 1 : (v > 200 ? -1 : 0) },
        { key: 'dollarIndex', name: '美元指数', region: '🇺🇸', getScore: (v: number) => v < 100 ? 1 : (v > 110 ? -1 : 0) },
        { key: 'geoRisk', name: '地缘风险指数', region: '🌐', getScore: (v: number) => v < 50 ? 1 : (v > 100 ? -1 : 0) }
      ]
    },
    {
      id: 'tech',
      name: '技术与生产力',
      icon: '🔬',
      fields: [
        { key: 'aiRdRatio', name: 'AI研发投入比', region: '🌐', getScore: () => 0 },
        { key: 'aiPatentCount', name: 'AI专利数量', region: '🌐', getScore: () => 0 },
        { key: 'robotInstallBase', name: '机器人装机量', region: '🌐', getScore: () => 0 },
        { key: 'quantumComputingBudget', name: '量子计算预算', region: '🌐', getScore: () => 0 }
      ]
    },
    {
      id: 'commodity',
      name: '气候与资源',
      icon: '🌍',
      fields: [
        { key: 'oilPrice', name: '原油价格', region: '🌐', getScore: (v: number) => v < 80 ? 1 : (v > 100 ? -1 : 0) },
        { key: 'naturalGas', name: '天然气价格', region: '🌐', getScore: (v: number) => v < 3 ? 1 : (v > 6 ? -1 : 0) },
        { key: 'carbonPrice', name: '碳排放价格', region: '🌐', getScore: (v: number) => v > 30 ? 1 : (v < 15 ? -1 : 0) },
        { key: 'electricity', name: '电力价格', region: '🌐', getScore: (v: number) => v < 0.1 ? 1 : (v > 0.2 ? -1 : 0) }
      ]
    }
  ]

  const dimensions: DimensionScore[] = dimensionConfigs.map(dim => {
    let positiveCount = 0
    let negativeCount = 0
    
    const indicators: IndicatorScore[] = dim.fields.map(field => {
      const rawValue = data[field.key]
      const fieldMeta = meta[field.key] || {}
      
  // 计算得分
      let score = 0
      if (rawValue !== undefined && rawValue !== 'NA') {
        if (typeof field.getScore === 'function') {
          // 处理字符串类型和数字类型
          if (typeof rawValue === 'string') {
            score = (field.getScore as unknown as (v: string) => number)(rawValue)
          } else {
            score = (field.getScore as unknown as (v: number) => number)(rawValue as number)
          }
        }
      }
      
      if (score > 0) positiveCount++
      if (score < 0) negativeCount++
      
      // 格式化显示值
      let displayValue = '-'
      if (rawValue !== undefined && rawValue !== 'NA') {
        if (typeof rawValue === 'number') {
          if (rawValue >= 1e11) displayValue = (rawValue / 1e8).toFixed(0) + '亿'
          else if (rawValue >= 1e9) displayValue = (rawValue / 1e8).toFixed(1) + '亿'
          else if (rawValue >= 1e6) displayValue = (rawValue / 1e4).toFixed(0) + '万'
          else displayValue = typeof rawValue === 'number' ? rawValue.toFixed(2) : String(rawValue)
        } else {
          displayValue = String(rawValue)
        }
      }
      
      return {
        id: field.key,
        name: field.name,
        value: displayValue,
        score,
        reason: fieldMeta.reason || (score === 1 ? '+1' : score === -1 ? '-1' : '0'),
        region: field.region
      }
    })
    
    return {
      id: dim.id,
      name: dim.name,
      icon: dim.icon,
      score: positiveCount - negativeCount,
      indicators
    }
  })

  // 计算 IAS 总分
  const totalScore = dimensions.reduce((sum: number, dim: DimensionScore) => sum + dim.score, 0)
  
  // 投资建议
  let signal = '持有'
  let position = '40-60%'
  if (totalScore >= 6) {
    signal = '强烈买入'
    position = '80-100%'
  } else if (totalScore >= 3) {
    signal = '买入'
    position = '60-80%'
  } else if (totalScore >= 0) {
    signal = '持有'
    position = '40-60%'
  } else if (totalScore >= -3) {
    signal = '减仓'
    position = '20-40%'
  } else {
    signal = '清仓'
    position = '0-20%'
  }

  return {
    totalScore,
    signal,
    position,
    dimensions
  }
}

// ====== 主组件 ======
function App() {
  const { data: rawData, isLoading, isStale, refetch } = useMarketData()
  const [iasResult, setIasResult] = useState<IASResult | null>(null)

  useEffect(() => {
    if (rawData) {
      setIasResult(transformDataV3(rawData))
    }
  }, [rawData])

  if (isLoading || !iasResult) {
    return <MarketDataSkeleton />
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white p-4">
      {/* Header */}
      <header className="text-center mb-6">
        <h1 className="text-3xl font-bold mb-2">📊 WorldOS V3.0 投资评分系统</h1>
        <div className="flex items-center justify-center gap-4">
          <p className="text-gray-400">更新时间：{rawData?.timestamp || '-'}</p>
          {isStale && (
            <span className="px-2 py-1 text-xs bg-yellow-500/20 text-yellow-400 rounded">
              ⚠️ 数据超时
            </span>
          )}
        </div>
        <button onClick={refetch} className="mt-2 text-xs text-gray-500 hover:text-gray-300 underline">
          手动刷新
        </button>
      </header>

      {/* IAS 卡片 */}
      <IASCard score={iasResult.totalScore} signal={iasResult.signal} position={iasResult.position} />

      {/* 维度条 */}
      <DimensionBar dimensions={iasResult.dimensions} />

      {/* 6-Grid Layout */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        {iasResult.dimensions.map(dim => (
          <DimensionCardV3 key={dim.id} dimension={dim} />
        ))}
      </div>
    </div>
  )
}

// ====== IAS 卡片 ======
function IASCard({ score, signal, position }: { score: number, signal: string, position: string }) {
  const getColor = () => {
    if (score >= 6) return 'from-green-600 to-green-500'
    if (score >= 3) return 'from-green-500 to-emerald-400'
    if (score >= 0) return 'from-yellow-500 to-orange-400'
    if (score >= -3) return 'from-orange-500 to-red-400'
    return 'from-red-600 to-red-500'
  }

  const getSignalIcon = () => {
    if (score >= 6) return '🚀'
    if (score >= 3) return '✅'
    if (score >= 0) return '➖'
    if (score >= -3) return '⚠️'
    return '🛑'
  }

  return (
    <div className={`bg-gradient-to-r ${getColor()} rounded-xl p-6 mb-6 text-center shadow-lg`}>
      <div className="text-sm text-white/80 mb-1">IAS 综合评分</div>
      <div className="text-5xl font-bold text-white mb-2">{score > 0 ? '+' : ''}{score}</div>
      <div className="text-2xl font-semibold text-white flex items-center justify-center gap-2">
        <span>{getSignalIcon()}</span>
        <span>{signal}</span>
      </div>
      <div className="text-white/80 mt-1">建议仓位: {position}</div>
    </div>
  )
}

// ====== 维度条 ======
function DimensionBar({ dimensions }: { dimensions: DimensionScore[] }) {
  return (
    <div className="flex flex-wrap justify-center gap-2 mb-6">
      {dimensions.map(dim => (
        <div 
          key={dim.id}
          className={`px-3 py-1 rounded-full text-sm ${
            dim.score > 0 ? 'bg-green-500/20 text-green-400' :
            dim.score < 0 ? 'bg-red-500/20 text-red-400' :
            'bg-gray-500/20 text-gray-400'
          }`}
        >
          {dim.icon} {dim.name} {dim.score > 0 ? '+' : ''}{dim.score}
        </div>
      ))}
    </div>
  )
}

// ====== 维度卡片 V3 ======
function DimensionCardV3({ dimension }: { dimension: DimensionScore }) {
  const scoreColor = dimension.score > 0 ? 'text-green-400' : dimension.score < 0 ? 'text-red-400' : 'text-gray-400'
  
  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <span>{dimension.icon}</span>
          <span>【{dimension.name}】</span>
        </h2>
        <span className={`text-xl font-bold ${scoreColor}`}>
          {dimension.score > 0 ? '+' : ''}{dimension.score}
        </span>
      </div>
      <div className="space-y-2">
        {dimension.indicators.map(ind => (
          <IndicatorRowV3 key={ind.id} indicator={ind} />
        ))}
      </div>
    </div>
  )
}

// ====== 指标行 V3 ======
function IndicatorRowV3({ indicator }: { indicator: IndicatorScore }) {
  const scoreClass = indicator.score > 0 ? 'text-green-400' : indicator.score < 0 ? 'text-red-400' : 'text-gray-500'
  const scoreIcon = indicator.score > 0 ? '↑' : indicator.score < 0 ? '↓' : '→'
  
  return (
    <div className="flex items-center justify-between py-2 border-b border-gray-700/30 text-sm">
      <div className="flex items-center gap-2">
        <span className="text-xs">{indicator.region}</span>
        <span>{indicator.name}</span>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-gray-400 text-xs">{indicator.value}</span>
        <span className={`font-medium ${scoreClass} w-8 text-right`}>
          {scoreIcon} {indicator.score > 0 ? '+' : ''}{indicator.score}
        </span>
      </div>
    </div>
  )
}

export default App