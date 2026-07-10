import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 10000
})

// 请求拦截器：添加 token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：处理 401
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export const authAPI = {
  login: (email, password) => api.post('/auth/login', { email, password }),
  getMe: () => api.get('/auth/me')
}

export const appsAPI = {
  list: () => api.get('/apps'),
  switch: (appId) => api.post(`/apps/${appId}/switch`)
}

export const intentAPI = {
  parse: (text, appId) => api.post('/intent/parse', { text, app_id: appId }),
  execute: (text, appId) => api.post('/intent/execute', { text, app_id: appId }),
  approve: (executionId, approved, reason) => 
    api.post('/intent/approve', { execution_id: executionId, approved, reason })
}

export const dataAPI = {
  getDashboard: (appId, params) => api.get('/data/dashboard', { params: { app_id: appId, ...params } }),
  getCampaignHealth: (appId) => api.get('/data/campaign-health', { params: { app_id: appId } }),
  getAlerts: (appId) => api.get('/data/alerts', { params: { app_id: appId } })
}

export const llmAPI = {
  getStatus: () => api.get('/llm/status'),
  testRoute: (intentType, sensitivity) =>
    api.post('/llm/test-route', null, { params: { intent_type: intentType, data_sensitivity: sensitivity } })
}

// Agent Loop API（Phase 1~3：多轮对话 / 记忆 / 策略自演化）
export const agentAPI = {
  // 创建会话并启动 ReAct 循环（首个 L1/L2 动作会停在 awaiting_approval）
  createSession: (text, appId) => api.post('/agent/sessions', { text, app_id: appId }),
  // 本 app 的会话列表
  listSessions: (appId) => api.get('/agent/sessions', { params: { app_id: appId } }),
  // 会话详情
  getSession: (id) => api.get(`/agent/sessions/${id}`),
  // 人在环审批：批准→续跑，驳回→重新规划
  approve: (id, stepId, approved, reason) =>
    api.post(`/agent/sessions/${id}/approve`, { step_id: stepId, approved, reason }),
  // 多轮追问 / 追加指令
  sendMessage: (id, text) => api.post(`/agent/sessions/${id}/message`, { text }),
  // 全局复盘（基于沉淀的 Episode 记忆）
  reflect: () => api.post('/agent/reflect'),
  // 按会话复盘
  reflectSession: (id) => api.post(`/agent/sessions/${id}/reflect`),
  // 策略自演化：记忆 → 可复用策略参数并落盘
  learnStrategy: () => api.post('/agent/strategy/learn'),
  // 查看已学策略
  getStrategy: () => api.get('/agent/strategy'),
  // 重置策略为硬编码默认
  resetStrategy: () => api.post('/agent/strategy/reset'),
  // 主动自治状态
  autonomyStatus: () => api.get('/agent/autonomy/status'),
  // 主动自治告警流
  autonomyAlerts: (appId) => api.get('/agent/autonomy/alerts', { params: { app_id: appId } }),
  // 手动触发一次主动巡检
  autonomyScan: (appId) => api.post('/agent/autonomy/scan', null, { params: { app_id: appId } }),
  // 启停主动自治调度
  autonomyToggle: (enabled) => api.post('/agent/autonomy/toggle', null, { params: { enabled } }),
}

// Campaign / AdGroup / Ad / Creative API
export const campaignAPI = {
  list: (params) => api.get('/campaigns', { params }),
  get: (id) => api.get(`/campaigns/${id}`),
  create: (data) => api.post('/campaigns', data),
  update: (id, data) => api.put(`/campaigns/${id}`, data),
  delete: (id) => api.delete(`/campaigns/${id}`),
  getAdGroups: (campaignId) => api.get(`/campaigns/${campaignId}/adgroups`),
  getAds: (adGroupId) => api.get(`/adgroups/${adGroupId}/ads`),
  getCreatives: (params) => api.get('/creatives', { params }),
  getCreative: (id) => api.get(`/creatives/${id}`),
  getCampaignCreatives: (campaignId) => api.get(`/campaigns/${campaignId}/creatives`),
  getDashboardData: (appId) => api.get('/dashboard/campaigns', { params: { app_id: appId } }),
}

export default api
