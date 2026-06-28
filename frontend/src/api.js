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
