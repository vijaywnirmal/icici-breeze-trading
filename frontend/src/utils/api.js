/**
 * Centralized API utilities to reduce duplication across components
 */

/**
 * Get the API base URL from environment variables
 * @returns {string} The API base URL
 */
export const getApiBase = () => {
  return import.meta.env.VITE_API_BASE_URL || ''
}

/**
 * Get the WebSocket base URL from environment variables
 * @returns {string} The WebSocket base URL
 */
export const getWsBase = () => {
  return import.meta.env.VITE_API_BASE_WS || ''
}

/**
 * Generate WebSocket URL from API base URL
 * @param {string} apiBase - The API base URL
 * @param {string} wsBase - The WebSocket base URL (optional)
 * @param {string} path - The WebSocket path (default: '/ws/stocks')
 * @returns {string} The complete WebSocket URL
 */
export const getWsUrl = (apiBase = '', wsBase = '', path = '/ws/stocks') => {
  const base = (wsBase || apiBase).replace(/\/$/, '')
  
  if (base.startsWith('ws://') || base.startsWith('wss://')) {
    return `${base}${path}`
  }
  if (base.startsWith('http://')) {
    return `ws://${base.substring('http://'.length)}${path}`
  }
  if (base.startsWith('https://')) {
    return `wss://${base.substring('https://'.length)}${path}`
  }
  
  return `ws://127.0.0.1:8000${path}`
}

/**
 * Get the normalized API URL (removes trailing slash)
 * @returns {string} The normalized API URL
 */
export const getNormalizedApiUrl = () => {
  const apiBase = getApiBase()
  return apiBase.replace(/\/$/, '')
}

/**
 * Create a complete API endpoint URL
 * @param {string} endpoint - The API endpoint path
 * @returns {string} The complete API URL
 */
export const createApiUrl = (endpoint) => {
  const base = getNormalizedApiUrl()
  return `${base}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`
}

/**
 * Create a WebSocket URL for stocks
 * @returns {string} The WebSocket URL for stocks
 */
export const getStocksWsUrl = () => {
  return getWsUrl(getApiBase(), getWsBase(), '/ws/stocks')
}
