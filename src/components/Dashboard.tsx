// 投资监控仪表盘 - 主面板组件 v6
// 龙六负责 - 按国家分类显示 + NA正确显示 + 表头+横向滚动龙七修改

import React from 'react';
import { motion } from 'framer-motion';
import { 
  DimensionCard, 
  ProgressBar, 
  StatusBadge,
  LabeledMetricRow 
} from './DimensionCard';
import { type MetricData, calculateAlertStatus, getDimensionStatus } from '../data/marketData';
import { getDashboardSummary } from '../data/alerts';

interface DashboardProps {
  data: MetricData;
  lastUpdate?: string;
}

// 格式化数值为显示字符串，NA正确显示
// 正确处理：数字→显示数值, "NA"→"NA", undefined/null→"NA"
const formatValue = (value: number | string | "NA" | undefined | null): string => {
  if (value === undefined || value === null) return "NA";
  if (value === "NA") return "NA";
  if (typeof value === 'string') return value;
  return String(value);
};

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.05 }
  }
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0 }
};

// 表头组件 - 龙七添加
const TableHeader: React.FC = () => (
  <div className="flex items-center justify-between py-1 px-2 text-xs text-[#484F58] border-b border-[#21262D] min-w-[404px]">
    <span className="w-[100px] flex-shrink-0">指标</span>
    <span className="w-[70px] text-right flex-shrink-0">数值</span>
    <span className="w-[90px] text-center flex-shrink-0">日期</span>
    <span className="w-[60px] text-center flex-shrink-0">同比</span>
    <span className="w-[60px] text-center flex-shrink-0">环比</span>
    <span className="w-[24px] text-center flex-shrink-0">?</span>
  </div>
);

// 国家分组包装组件 - 龙七添加
const CountrySection: React.FC<{
  flag: string;
  label: string;
  children: React.ReactNode;
}> = ({ flag, label, children }) => (
  <div className="ml-2 mb-2">
    <div className="text-xs text-[#8B949E] mb-1 font-medium">{flag} {label}</div>
    <div className="overflow-x-auto">
      <div className="min-w-[404px]">
        <TableHeader />
        {children}
      </div>
    </div>
  </div>
);

export const Dashboard: React.FC<DashboardProps> = ({ data, lastUpdate }) => {
  const overallStatus = calculateAlertStatus(data);

  // 辅助函数：获取数值，处理undefined/null情况
  const getNum = (metric: { value: number | string | "NA" | undefined | null }): number => {
    const v = metric.value;
    if (v === undefined || v === null) return 0;
    return typeof v === 'number' ? v : 0;
  };

  return (
    <div className="min-h-screen bg-[#0D1117] p-6">
      {/* 头部 */}
      <motion.header 
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-8"
      >
        <h1 className="text-3xl font-bold text-[#E6EDF3] mb-2">
          <motion.span 
            className="text-[#00D4FF]"
            animate={{ textShadow: ['0 0 10px #00D4FF', '0 0 20px #00D4FF', '0 0 10px #00D4FF'] }}
            transition={{ duration: 2, repeat: Infinity }}
          >
            投资监控
          </motion.span>
          {' '}仪表盘 <span className="text-lg text-[#8B949E]">v2.0</span>
        </h1>
        <div className="flex items-center gap-4 text-[#8B949E] text-sm">
          <span>更新时间: {lastUpdate || new Date().toLocaleString()}</span>
          <StatusBadge status={overallStatus} />
        </div>
      </motion.header>

      {/* 10维度卡片网格 */}
      <motion.div 
        variants={containerVariants}
        initial="hidden"
        animate="visible"
        className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"
      >
        
        <motion.div variants={itemVariants}>
          <DimensionCard title="宏观经济" icon="📈" alertStatus={getDimensionStatus(data, 'macro')}>
            {/* 🇨🇳 中国指标 */}
            <CountrySection flag="🇨🇳" label="中国">
              <LabeledMetricRow label="GDP增速"
                  dateLabel={data.gdp.dateLabel}
                  yoy={data.gdp.yoy}
                  yoyLabel={data.gdp.yoyLabel}
                  mom={data.gdp.mom}
                  momLabel={data.gdp.momLabel}
                  definition={metricDefinitions["gdp"]?.definition} source={metricDefinitions["gdp"]?.source} frequency={metricDefinitions["gdp"]?.frequency} value={formatValue(data.gdp.value)} country={data.gdp.country} unit="%" trend={getNum(data.gdp) > 5 ? 'up' : 'down'} />
              <LabeledMetricRow label="制造业PMI"
                  dateLabel={data.pmi.dateLabel}
                  yoy={data.pmi.yoy}
                  yoyLabel={data.pmi.yoyLabel}
                  mom={data.pmi.mom}
                  momLabel={data.pmi.momLabel}
                  definition={metricDefinitions["pmi"]?.definition} source={metricDefinitions["pmi"]?.source} frequency={metricDefinitions["pmi"]?.frequency} value={formatValue(data.pmi.value)} country={data.pmi.country} trend={getNum(data.pmi) > 50 ? 'up' : 'down'} />
              <LabeledMetricRow label="服务业PMI"
                  dateLabel={data.servicePmi.dateLabel}
                  yoy={data.servicePmi.yoy}
                  yoyLabel={data.servicePmi.yoyLabel}
                  mom={data.servicePmi.mom}
                  momLabel={data.servicePmi.momLabel}
                  definition={metricDefinitions["servicePmi"]?.definition} source={metricDefinitions["servicePmi"]?.source} frequency={metricDefinitions["servicePmi"]?.frequency} value={formatValue(data.servicePmi.value)} country={data.servicePmi.country} trend={getNum(data.servicePmi) > 50 ? 'up' : 'down'} />
              <LabeledMetricRow label="CPI同比"
                  dateLabel={data.cpi.dateLabel}
                  yoy={data.cpi.yoy}
                  yoyLabel={data.cpi.yoyLabel}
                  mom={data.cpi.mom}
                  momLabel={data.cpi.momLabel}
                  definition={metricDefinitions["cpi"]?.definition} source={metricDefinitions["cpi"]?.source} frequency={metricDefinitions["cpi"]?.frequency} value={formatValue(data.cpi.value)} country={data.cpi.country} unit="%" trend="neutral" />
              <LabeledMetricRow label="PPI"
                  dateLabel={data.ppi.dateLabel}
                  yoy={data.ppi.yoy}
                  yoyLabel={data.ppi.yoyLabel}
                  mom={data.ppi.mom}
                  momLabel={data.ppi.momLabel}
                  definition={metricDefinitions["ppi"]?.definition} source={metricDefinitions["ppi"]?.source} frequency={metricDefinitions["ppi"]?.frequency} value={formatValue(data.ppi.value)} country={data.ppi.country} unit="%" trend={getNum(data.ppi) > 0 ? 'up' : 'down'} />
              <LabeledMetricRow label="失业率"
                  dateLabel={data.unemployment.dateLabel}
                  yoy={data.unemployment.yoy}
                  yoyLabel={data.unemployment.yoyLabel}
                  mom={data.unemployment.mom}
                  momLabel={data.unemployment.momLabel}
                  definition={metricDefinitions["unemployment"]?.definition} source={metricDefinitions["unemployment"]?.source} frequency={metricDefinitions["unemployment"]?.frequency} value={formatValue(data.unemployment.value)} country={data.unemployment.country} unit="%" trend={getNum(data.unemployment) > 6 ? 'down' : 'up'} />
              <LabeledMetricRow label="M2增速"
                  dateLabel={data.m2.dateLabel}
                  yoy={data.m2.yoy}
                  yoyLabel={data.m2.yoyLabel}
                  mom={data.m2.mom}
                  momLabel={data.m2.momLabel}
                  definition={metricDefinitions["m2"]?.definition} source={metricDefinitions["m2"]?.source} frequency={metricDefinitions["m2"]?.frequency} value={formatValue(data.m2.value)} country={data.m2.country} unit="%" trend={getNum(data.m2) > 8 ? 'up' : 'down'} />
              <LabeledMetricRow label="社融增速"
                  dateLabel={data.socialFinance.dateLabel}
                  yoy={data.socialFinance.yoy}
                  yoyLabel={data.socialFinance.yoyLabel}
                  mom={data.socialFinance.mom}
                  momLabel={data.socialFinance.momLabel}
                  definition={metricDefinitions["socialFinance"]?.definition} source={metricDefinitions["socialFinance"]?.source} frequency={metricDefinitions["socialFinance"]?.frequency} value={formatValue(data.socialFinance.value)} country={data.socialFinance.country} unit="%" trend={getNum(data.socialFinance) > 10 ? 'up' : 'down'} />
              <LabeledMetricRow label="LPR利率"
                  dateLabel={data.interest.dateLabel}
                  yoy={data.interest.yoy}
                  yoyLabel={data.interest.yoyLabel}
                  mom={data.interest.mom}
                  momLabel={data.interest.momLabel}
                  definition={metricDefinitions["interest"]?.definition} source={metricDefinitions["interest"]?.source} frequency={metricDefinitions["interest"]?.frequency} value={formatValue(data.interest.value)} country={data.interest.country} unit="%" trend="neutral" />
            </CountrySection>
            {/* 🇺🇸 美国指标 */}
            <CountrySection flag="🇺🇸" label="美国">
              <LabeledMetricRow label="非农就业"
                  dateLabel={data.nonfarm.dateLabel}
                  yoy={data.nonfarm.yoy}
                  yoyLabel={data.nonfarm.yoyLabel}
                  mom={data.nonfarm.mom}
                  momLabel={data.nonfarm.momLabel}
                  definition={metricDefinitions["nonfarm"]?.definition} source={metricDefinitions["nonfarm"]?.source} frequency={metricDefinitions["nonfarm"]?.frequency} value={formatValue(data.nonfarm.value)} country={data.nonfarm.country} unit="万" trend={getNum(data.nonfarm) > 0 ? 'up' : 'down'} />
              <LabeledMetricRow label="核心PCE"
                  dateLabel={data.corePCE.dateLabel}
                  yoy={data.corePCE.yoy}
                  yoyLabel={data.corePCE.yoyLabel}
                  mom={data.corePCE.mom}
                  momLabel={data.corePCE.momLabel}
                  definition={metricDefinitions["corePCE"]?.definition} source={metricDefinitions["corePCE"]?.source} frequency={metricDefinitions["corePCE"]?.frequency} value={formatValue(data.corePCE.value)} country={data.corePCE.country} unit="%" trend={getNum(data.corePCE) > 2 ? 'down' : 'up'} />
            </CountrySection>
          </DimensionCard>
        </motion.div>

        {/* 维度2: 地缘政治（1个）🌐 */}
        <motion.div variants={itemVariants}>
          <DimensionCard title="地缘政治" icon="🌍" alertStatus={getDimensionStatus(data, 'geo')}>
            <CountrySection flag="🌐" label="全球">
              <LabeledMetricRow label="EPU指数" value={formatValue(data.epu.value)} country={data.epu.country} trend="neutral" />
              <ProgressBar value={getNum(data.epu)} max={400} status={getDimensionStatus(data, 'geo')} />
            </CountrySection>
          </DimensionCard>
        </motion.div>

        {/* 维度3: 生产生活（3个）🇨🇳 */}
        <motion.div variants={itemVariants}>
          <DimensionCard title="生产生活" icon="🏭" alertStatus={getDimensionStatus(data, 'production')}>
            <CountrySection flag="🇨🇳" label="中国">
              <LabeledMetricRow label="工业用电量" value={formatValue(data.electricity.value)} country={data.electricity.country} unit="%" trend={getNum(data.electricity) > 0 ? 'up' : 'down'} />
              <LabeledMetricRow label="社会零售" value={formatValue(data.retail.value)} country={data.retail.country} unit="%" trend={getNum(data.retail) > 0 ? 'up' : 'down'} />
              <LabeledMetricRow label="房地产销售" value={formatValue(data.property.value)} country={data.property.country} unit="%" trend={getNum(data.property) > 0 ? 'up' : 'down'} />
            </CountrySection>
          </DimensionCard>
        </motion.div>

        {/* 维度4: 流动性（6个）💰 */}
        <motion.div variants={itemVariants}>
          <DimensionCard title="全球流动性" icon="💰" alertStatus={getDimensionStatus(data, 'liquidity')}>
            {/* 🇨🇳 中国 */}
            <CountrySection flag="🇨🇳" label="中国">
              <LabeledMetricRow label="北向资金"
                  dateLabel={data.northbound.dateLabel}
                  yoy={data.northbound.yoy}
                  yoyLabel={data.northbound.yoyLabel}
                  mom={data.northbound.mom}
                  momLabel={data.northbound.momLabel}
                  definition={metricDefinitions["northbound"]?.definition} source={metricDefinitions["northbound"]?.source} frequency={metricDefinitions["northbound"]?.frequency} value={formatValue(data.northbound.value)} country={data.northbound.country} unit="亿" trend={getNum(data.northbound) > 0 ? 'up' : 'down'} />
              <LabeledMetricRow label="南向资金" value={formatValue(data.southbound.value)} country={data.southbound.country} unit="亿" trend={getNum(data.southbound) > 0 ? 'up' : 'down'} />
              <LabeledMetricRow label="离岸人民币" value={formatValue(data.cny.value)} country={data.cny.country} trend="neutral" />
            </CountrySection>
            {/* 🇺🇸 美国 */}
            <CountrySection flag="🇺🇸" label="美国">
              <LabeledMetricRow label="美联储资产负债表" value={formatValue(data.fedBalance.value)} country={data.fedBalance.country} unit="万亿$" trend="neutral" />
              <LabeledMetricRow label="10年美债"
                  dateLabel={data.us10y.dateLabel}
                  yoy={data.us10y.yoy}
                  yoyLabel={data.us10y.yoyLabel}
                  mom={data.us10y.mom}
                  momLabel={data.us10y.momLabel}
                  definition={metricDefinitions["us10y"]?.definition} source={metricDefinitions["us10y"]?.source} frequency={metricDefinitions["us10y"]?.frequency} value={formatValue(data.us10y.value)} country={data.us10y.country} unit="%" trend="neutral" />
            </CountrySection>
            {/* 🌐 全球 */}
            <CountrySection flag="🌐" label="全球">
              <LabeledMetricRow label="美元指数" value={formatValue(data.dollarIndex.value)} country={data.dollarIndex.country} trend="neutral" />
            </CountrySection>
          </DimensionCard>
        </motion.div>

        {/* 维度5: 情绪（5个）😤 */}
        <motion.div variants={itemVariants}>
          <DimensionCard title="市场情绪" icon="😤" alertStatus={getDimensionStatus(data, 'sentiment')}>
            {/* 🇨🇳 中国 */}
            <CountrySection flag="🇨🇳" label="中国">
              <LabeledMetricRow label="融资余额"
                  dateLabel={data.margin.dateLabel}
                  yoy={data.margin.yoy}
                  yoyLabel={data.margin.yoyLabel}
                  mom={data.margin.mom}
                  momLabel={data.margin.momLabel}
                  definition={metricDefinitions["margin"]?.definition} source={metricDefinitions["margin"]?.source} frequency={metricDefinitions["margin"]?.frequency} value={formatValue(data.margin.value)} country={data.margin.country} unit="亿" trend="neutral" />
              <LabeledMetricRow label="两市成交额" value={formatValue(data.turnover.value)} country={data.turnover.country} unit="亿" trend="neutral" />
              <LabeledMetricRow label="机构仓位" value={formatValue(data.fundPosition.value)} country={data.fundPosition.country} unit="%" trend="neutral" />
              <LabeledMetricRow label="ETF申赎" value={formatValue(data.etfFlow.value)} country={data.etfFlow.country} unit="亿" trend={getNum(data.etfFlow) > 0 ? 'up' : 'down'} />
            </CountrySection>
            {/* 🇺🇸 美国 */}
            <CountrySection flag="🇺🇸" label="美国">
              <LabeledMetricRow label="VIX恐慌指数" value={formatValue(data.vix.value)} country={data.vix.country} trend="neutral" />
              <ProgressBar value={getNum(data.vix)} max={40} status={getDimensionStatus(data, 'sentiment')} />
            </CountrySection>
          </DimensionCard>
        </motion.div>

        {/* 维度6: 供应链（3个）🚢 */}
        <motion.div variants={itemVariants}>
          <DimensionCard title="供应链" icon="🚢" alertStatus={getDimensionStatus(data, 'supply')}>
            {/* 🇨🇳 中国 */}
            <CountrySection flag="🇨🇳" label="中国">
              <LabeledMetricRow label="中国出口" value={formatValue(data.export.value)} country={data.export.country} unit="%" trend={getNum(data.export) > 0 ? 'up' : 'down'} />
            </CountrySection>
            {/* 🌐 全球 */}
            <CountrySection flag="🌐" label="全球">
              <LabeledMetricRow label="BDI指数"
                  dateLabel={data.bdi.dateLabel}
                  yoy={data.bdi.yoy}
                  yoyLabel={data.bdi.yoyLabel}
                  mom={data.bdi.mom}
                  momLabel={data.bdi.momLabel}
                  definition={metricDefinitions["bdi"]?.definition} source={metricDefinitions["bdi"]?.source} frequency={metricDefinitions["bdi"]?.frequency} value={formatValue(data.bdi.value)} country={data.bdi.country} trend="neutral" />
              <ProgressBar value={getNum(data.bdi)} max={3000} status={getDimensionStatus(data, 'supply')} />
              <LabeledMetricRow label="原油价格" value={formatValue(data.oil.value)} country={data.oil.country} unit="$" trend="neutral" />
              <ProgressBar value={getNum(data.oil)} max={150} status={getDimensionStatus(data, 'supply')} />
            </CountrySection>
          </DimensionCard>
        </motion.div>

        {/* 维度7: 人口结构（1个）👥 */}
        <motion.div variants={itemVariants}>
          <DimensionCard title="人口结构" icon="👥" alertStatus={getDimensionStatus(data, 'population')}>
            <CountrySection flag="🇨🇳" label="中国">
              <LabeledMetricRow label="居民杠杆率" value={formatValue(data.leverageRate.value)} country={data.leverageRate.country} unit="%" trend="neutral" />
            </CountrySection>
          </DimensionCard>
        </motion.div>

        {/* 维度8: 尾部风险（1个）⚠️ */}
        <motion.div variants={itemVariants}>
          <DimensionCard title="尾部风险" icon="⚠️" alertStatus={getDimensionStatus(data, 'tail')}>
            <CountrySection flag="🌐" label="全球">
              <LabeledMetricRow label="粮食价格指数" value={formatValue(data.foodIndex.value)} country={data.foodIndex.country} trend="neutral" />
              <ProgressBar value={getNum(data.foodIndex)} max={150} status={getDimensionStatus(data, 'tail')} />
            </CountrySection>
          </DimensionCard>
        </motion.div>
      </motion.div>

      {/* 投资建议面板 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5 }}
        className="mt-6 bg-[#161B22] border border-[#30363D] rounded-lg p-6"
      >
        <h2 className="text-xl font-bold text-[#E6EDF3] mb-4">📊 投资建议</h2>
        {(() => {
          const summary = getDashboardSummary(data);
          return (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-[#0D1117] p-4 rounded-lg">
                <div className="text-[#8B949E] text-sm mb-2">当前周期</div>
                <div className={`text-2xl font-bold ${
                  summary.cycle === '复苏' ? 'text-green-400' :
                  summary.cycle === '过热' ? 'text-red-400' :
                  summary.cycle === '滞胀' ? 'text-orange-400' :
                  summary.cycle === '衰退' ? 'text-red-400' :
                  'text-yellow-400'
                }`}>{summary.cycle}</div>
              </div>
              <div className="bg-[#0D1117] p-4 rounded-lg">
                <div className="text-[#8B949E] text-sm mb-2">资产配置</div>
                <div className="text-[#E6EDF3]">
                  <div>股票 {summary.advice.stockRatio}% / 债券 {summary.advice.bondRatio}% / 现金 {summary.advice.cashRatio}%</div>
                </div>
              </div>
              <div className="bg-[#0D1117] p-4 rounded-lg">
                <div className="text-[#8B949E] text-sm mb-2">推荐行业</div>
                <div className="text-[#E6EDF3] text-sm">
                  {summary.advice.recommendedSectors.join('、')}
                </div>
              </div>
            </div>
          );
        })()}
      </motion.div>
    </div>
  );
};

export default Dashboard;
// 指标说明定义
const metricDefinitions: Record<string, { definition: string; source: string; frequency: string }> = {
  gdp: { definition: '国内生产总值同比增长率，反映经济增长状况', source: '国家统计局（AKShare-macro_china_gdp）', frequency: '季度更新' },
  pmi: { definition: '采购经理指数，50以上表示经济扩张，50以下表示收缩', source: '国家统计局（AKShare-macro_china_pmi）', frequency: '月度更新' },
  servicePmi: { definition: '非制造业商务活动指数，反映服务业景气程度', source: '国家统计局（AKShare-macro_china_pmi）', frequency: '月度更新' },
  cpi: { definition: '居民消费价格指数，反映通货膨胀水平', source: '国家统计局（AKShare-macro_china_cpi）', frequency: '月度更新' },
  ppi: { definition: '工业生产者出厂价格指数，反映工业品价格变动', source: '国家统计局（AKShare-macro_china_ppi）', frequency: '月度更新' },
  unemployment: { definition: '失业率，反映劳动力市场状况', source: '国家统计局/美国劳工部（AKShare）', frequency: '月度更新' },
  m2: { definition: '广义货币供应量，反映货币政策松紧程度', source: '中国人民银行（AKShare-macro_china_m2_yearly）', frequency: '月度更新' },
  socialFinance: { definition: '社会融资规模存量同比增速，反映金融对实体支持', source: '中国人民银行（AKShare-macro_china_new_financial_credit）', frequency: '月度更新' },
  interest: { definition: '贷款市场报价利率，反映银行信贷成本', source: '中国人民银行（AKShare-macro_china_lpr）', frequency: '月度更新' },
  export: { definition: '以美元计价的出口金额同比增速', source: '海关总署（AKShare-macro_china_exports_yoy）', frequency: '月度更新' },
  retail: { definition: '社会消费品零售总额同比增速，反映消费需求', source: '国家统计局（AKShare-macro_china_consumer_goods_retail）', frequency: '月度更新' },
  property: { definition: '商品房销售面积累计同比，反映房地产市场', source: '国家统计局（AKShare-macro_china_real_estate）', frequency: '月度更新' },
  bdi: { definition: '波罗的海干散货指数，反映全球贸易航运需求', source: '伦敦波罗的海交易所（AKShare-macro_shipping_bdi）', frequency: '日度更新' },
  nonfarm: { definition: '美国非农就业人数变化，反映就业市场状况', source: '美国劳工部（AKShare-macro_usa_non_farm）', frequency: '月度更新' },
  corePCE: { definition: '核心PCE物价指数年率，联储关注通胀指标', source: '美国商务部（AKShare-macro_usa_core_pce_price）', frequency: '月度更新' },
  us10y: { definition: '美国10年期国债收益率，反映市场对美国经济预期', source: 'FactSet/AKShare（ak.bond_zh_us_rate）', frequency: '日度更新' },
  northbound: { definition: '北向资金净流入，反映外资配置A股意愿', source: '东方财富（AKShare-stock_hsgt_fund_flow_summary_em）', frequency: '日度更新' },
  margin: { definition: '融资余额，反映杠杆资金情绪', source: '上交所（AKShare-stock_margin_sse）', frequency: '日度更新' },
};

