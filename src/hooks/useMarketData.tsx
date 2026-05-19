import { useState, useEffect, useRef, useCallback } from 'react'

const POLL_INTERVAL = 60000 // 60秒
const STALE_THRESHOLD = 120000 // 2分钟

export interface MarketDataRaw {
  timestamp: string
  data: Record<string, any>
  indicators: Record<string, any>
  meta: Record<string, any>
}

export interface UseMarketDataResult {
  data: MarketDataRaw | null
  isLoading: boolean
  isStale: boolean
  error: string | null
  lastUpdate: Date | null
  refetch: () => void
}

export function useMarketData(): UseMarketDataResult {
  const [data, setData] = useState<MarketDataRaw | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const [isStale, setIsStale] = useState(false)
  
  const staleTimerRef = useRef<number | null>(null)
  const pollTimerRef = useRef<number | null>(null)

  const fetchData = useCallback(async (isInitial = false) => {
    try {
      const response = await fetch('/data/market-data.json')
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      const newData = await response.json()
      
      setData(newData)
      setLastUpdate(new Date())
      setError(null)
      setIsLoading(false)
      setIsStale(false)
      
      // 重置 stale 计时器
      if (staleTimerRef.current) {
        clearTimeout(staleTimerRef.current)
      }
      staleTimerRef.current = window.setTimeout(() => {
        setIsStale(true)
      }, STALE_THRESHOLD)
      
    } catch (err) {
      // 网络错误时保留旧数据，不更新 isLoading
      if (!isInitial) {
        setError(err instanceof Error ? err.message : '获取数据失败')
      }
      // 首次加载失败才设置 loading 为 false（避免一直 loading）
      if (isInitial) {
        setIsLoading(false)
      }
    }
  }, [])

  // 初始化获取数据
  useEffect(() => {
    fetchData(true)
  }, [fetchData])

  // 设置轮询
  useEffect(() => {
    pollTimerRef.current = window.setInterval(() => {
      fetchData(false)
    }, POLL_INTERVAL)

    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
      }
      if (staleTimerRef.current) {
        clearTimeout(staleTimerRef.current)
      }
    }
  }, [fetchData])

  const refetch = useCallback(() => {
    fetchData(false)
  }, [fetchData])

  return {
    data,
    isLoading,
    isStale,
    error,
    lastUpdate,
    refetch
  }
}

// 骨架屏组件
export function MarketDataSkeleton() {
  return (
    <div className="min-h-screen bg-gray-900 text-white p-4">
      {/* Header skeleton */}
      <div className="text-center mb-6">
        <div className="h-10 w-64 bg-gray-800 rounded mx-auto mb-2 animate-pulse"></div>
        <div className="h-4 w-48 bg-gray-800 rounded mx-auto animate-pulse"></div>
      </div>

      {/* Warning Summary skeleton */}
      <div className="flex justify-center gap-8 mb-6">
        {[1, 2, 3].map(i => (
          <div key={i} className="flex items-center gap-2">
            <div className={`w-4 h-4 rounded-full bg-gray-700`}></div>
            <div className="h-4 w-20 bg-gray-800 rounded animate-pulse"></div>
          </div>
        ))}
      </div>

      {/* Grid skeleton */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
        {[1, 2, 3, 4, 5, 6].map(i => (
          <div key={i} className="bg-gray-800 rounded-lg p-4 border border-gray-700">
            <div className="h-6 w-32 bg-gray-700 rounded mb-3 animate-pulse"></div>
            <div className="space-y-2">
              {[1, 2, 3, 4].map(j => (
                <div key={j} className="flex justify-between">
                  <div className="h-4 w-24 bg-gray-700/50 rounded animate-pulse"></div>
                  <div className="h-4 w-16 bg-gray-700/50 rounded animate-pulse"></div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Decision skeleton */}
      <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
        <div className="h-6 w-40 bg-gray-700 rounded mb-4 animate-pulse"></div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="bg-gray-700/50 rounded p-3">
              <div className="h-4 w-16 bg-gray-600 rounded mx-auto mb-1 animate-pulse"></div>
              <div className="h-5 w-20 bg-gray-600 rounded mx-auto animate-pulse"></div>
            </div>
          ))}
        </div>
        <div className="space-y-2">
          <div className="h-5 w-48 bg-gray-700/50 rounded animate-pulse"></div>
          <div className="h-5 w-56 bg-gray-700/50 rounded animate-pulse"></div>
          <div className="h-5 w-44 bg-gray-700/50 rounded animate-pulse"></div>
        </div>
      </div>
    </div>
  )
}