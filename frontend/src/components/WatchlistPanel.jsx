import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { Card, CardHeader, CardContent } from './ui/Card'
import Button from './ui/Button'
import Typography from './ui/Typography'

export default function WatchlistPanel() {
	const [watchlist, setWatchlist] = useState([])
	const [searchQuery, setSearchQuery] = useState('')
	const [searchResults, setSearchResults] = useState([])
	const [livePrices, setLivePrices] = useState({})
	const [marketStatus, setMarketStatus] = useState(null)
	const [isCollapsed, setIsCollapsed] = useState(false)
	const [pollingInterval, setPollingInterval] = useState(null)
	const [searchLoading, setSearchLoading] = useState(false)
	const [wsConnection, setWsConnection] = useState(null)
	const searchTimeoutRef = useRef(null)

	const apiBase = import.meta.env.VITE_API_BASE_URL || ''
	const httpBase = useMemo(() => (apiBase || '').replace(/\/$/, ''), [apiBase])
	const wsBase = useMemo(() => (apiBase || '').replace('http', 'ws'), [apiBase])

	// Load watchlist from localStorage on component mount
	useEffect(() => {
		try {
			const saved = localStorage.getItem('watchlist')
			if (saved) {
				const parsed = JSON.parse(saved)
				if (Array.isArray(parsed)) {
					setWatchlist(parsed)
				}
			}
		} catch (_) {}
	}, [])

	// Load market status
	useEffect(() => {
		const fetchMarketStatus = async () => {
			try {
				const response = await fetch(`${httpBase}/api/market/status`)
				const data = await response.json()
				setMarketStatus(data)
			} catch (err) {
				console.error('Failed to fetch market status:', err)
			}
		}
		fetchMarketStatus()
	}, [httpBase])

	// WebSocket connection for live prices
	useEffect(() => {
		if (marketStatus?.is_open && watchlist.length > 0) {
			connectWebSocket()
		} else {
			disconnectWebSocket()
		}

		return () => {
			disconnectWebSocket()
		}
	}, [marketStatus?.is_open, watchlist.length])

	// Subscribe to new stocks when they're added
	useEffect(() => {
		if (wsConnection && wsConnection.readyState === WebSocket.OPEN && watchlist.length > 0) {
			// Subscribe to all watchlist stocks
			watchlist.forEach(stock => {
				wsConnection.send(JSON.stringify({
					action: 'subscribe',
					symbol: stock.symbol || '',
					exchange_code: stock.exchange || 'NSE',
					product_type: 'cash'
				}))
			})
		}
	}, [watchlist.length, wsConnection])

	// Seed cached prices from localStorage
	useEffect(() => {
		try {
			if (!Array.isArray(watchlist) || watchlist.length === 0) return
			const seeded = {}
			watchlist.forEach(item => {
				const cache = JSON.parse(localStorage.getItem(`ltp:${item.symbol}`) || 'null')
				if (cache && typeof cache === 'object') {
					seeded[item.symbol] = cache
				}
			})
			if (Object.keys(seeded).length > 0) {
				setLivePrices(prev => ({ ...seeded, ...prev }))
			}
		} catch (_) {}
	}, [watchlist])

	// Search for stocks using the live trading endpoint
	const searchStocks = useCallback(async (query) => {
		if (!query.trim() || query.length < 2) {
			setSearchResults([])
			setSearchLoading(false)
			return
		}

		setSearchLoading(true)
		try {
			const response = await fetch(`${httpBase}/api/instruments/live-trading?q=${encodeURIComponent(query)}&limit=10`)
			const data = await response.json()
			
			if (data.success && Array.isArray(data.items)) {
				setSearchResults(data.items)
			} else {
				setSearchResults([])
			}
		} catch (err) {
			console.error('Search failed:', err)
			setSearchResults([])
		} finally {
			setSearchLoading(false)
		}
	}, [httpBase])

	// WebSocket connection functions
	const connectWebSocket = () => {
		if (wsConnection) {
			wsConnection.close()
		}

		const ws = new WebSocket(`${wsBase}/ws/stocks`)
		setWsConnection(ws)

		ws.onopen = () => {
			console.log('WebSocket connected for watchlist panel')
			// Subscribe to all watchlist stocks
			watchlist.forEach(stock => {
				ws.send(JSON.stringify({
					action: 'subscribe',
					symbol: stock.symbol || '',
					exchange_code: stock.exchange || 'NSE',
					product_type: 'cash'
				}))
			})
		}

		ws.onmessage = (event) => {
			try {
				const data = JSON.parse(event.data)
				if (data.type === 'tick' && data.symbol) {
					setLivePrices(prev => ({
						...prev,
						[data.symbol]: {
							ltp: data.ltp,
							close: data.close,
							change_pct: data.change_pct,
							bid: data.bid,
							ask: data.ask,
							volume: data.volume,
							timestamp: data.timestamp,
							status: 'live'
						}
					}))

					// Persist last-known values so they are available when market is closed
					try {
						localStorage.setItem(`ltp:${data.symbol}`, JSON.stringify({
							ltp: data.ltp,
							close: data.close,
							change_pct: data.change_pct,
							bid: data.bid,
							ask: data.ask,
							volume: data.volume,
							timestamp: data.timestamp,
							status: 'live'
						}))
					} catch (_) {}
				}
			} catch (err) {
				console.error('Failed to parse WebSocket message:', err)
			}
		}

		ws.onerror = (error) => {
			console.error('WebSocket error:', error)
		}

		ws.onclose = () => {
			console.log('WebSocket disconnected')
		}
	}

	const disconnectWebSocket = () => {
		if (wsConnection) {
			wsConnection.close()
			setWsConnection(null)
		}
	}

	// Debounced search
	useEffect(() => {
		if (searchTimeoutRef.current) {
			clearTimeout(searchTimeoutRef.current)
		}

		searchTimeoutRef.current = setTimeout(() => {
			searchStocks(searchQuery)
		}, 300)

		return () => {
			if (searchTimeoutRef.current) {
				clearTimeout(searchTimeoutRef.current)
			}
		}
	}, [searchQuery, searchStocks])

	// Handle search input
	const handleSearchChange = (e) => {
		const query = e.target.value
		setSearchQuery(query)
	}

	// Add stock to watchlist
	const addToWatchlist = async (stock) => {
		if (!watchlist.find(s => s.symbol === stock.symbol)) {
			const newStock = {
				...stock,
				id: `${stock.symbol}_${Date.now()}`,
				addedAt: new Date().toISOString()
			}
			const newWatchlist = [...watchlist, newStock]
			setWatchlist(newWatchlist)
			saveWatchlist(newWatchlist)
			setSearchQuery('')
			setSearchResults([])

			// Subscribe to WebSocket if market is open and WebSocket is connected
			if (marketStatus?.is_open && wsConnection && wsConnection.readyState === WebSocket.OPEN) {
				wsConnection.send(JSON.stringify({
					action: 'subscribe',
					symbol: stock.symbol || '',
					exchange_code: stock.exchange || 'NSE',
					product_type: 'cash'
				}))
			}

			// Fetch price immediately if market is closed
			if (!marketStatus?.is_open) {
				try {
					const response = await fetch(`${httpBase}/api/quotes/stock?symbol=${encodeURIComponent(stock.symbol)}&exchange=${stock.exchange || 'NSE'}`)
					const data = await response.json()
					
					if (data && data.symbol && (data.ltp || data.close)) {
						const priceData = {
							symbol: data.symbol,
							ltp: data.ltp,
							close: data.close,
							change_pct: data.change_pct,
							bid: data.bid,
							ask: data.ask,
							volume: data.volume,
							timestamp: data.timestamp,
							status: 'closed'
						}
						setLivePrices(prev => ({ ...prev, [stock.symbol]: priceData }))
					}
				} catch (err) {
					console.error(`Failed to fetch price for ${stock.symbol}:`, err)
				}
			}
		}
	}

	// Remove stock from watchlist
	const removeFromWatchlist = (symbol) => {
		const newWatchlist = watchlist.filter(stock => stock.symbol !== symbol)
		setWatchlist(newWatchlist)
		saveWatchlist(newWatchlist)
		
		// Remove from live prices
		setLivePrices(prev => {
			const updated = { ...prev }
			delete updated[symbol]
			return updated
		})
	}

	// Save watchlist to localStorage
	const saveWatchlist = (newWatchlist) => {
		try {
			localStorage.setItem('watchlist', JSON.stringify(newWatchlist))
		} catch (_) {}
	}

	// Poll watchlist prices when market is closed
	const pollWatchlistPrices = async () => {
		if (!marketStatus || marketStatus.is_open || watchlist.length === 0) return

		try {
			const promises = watchlist.map(async (stock) => {
				try {
					const response = await fetch(`${httpBase}/api/quotes/stock?symbol=${encodeURIComponent(stock.symbol)}&exchange=${stock.exchange || 'NSE'}`)
					const data = await response.json()
					
					if (data && data.symbol && (data.ltp || data.close)) {
						return {
							symbol: stock.symbol,
							ltp: data.ltp,
							close: data.close,
							change_pct: data.change_pct,
							bid: data.bid,
							ask: data.ask,
							volume: data.volume,
							timestamp: data.timestamp,
							status: 'closed'
						}
					}
				} catch (err) {
					console.error(`Failed to fetch price for ${stock.symbol}:`, err)
				}
				return null
			})

			const results = await Promise.all(promises)
			const validResults = results.filter(result => result !== null)
			
			if (validResults.length > 0) {
				const newPrices = {}
				validResults.forEach(result => {
					newPrices[result.symbol] = result
				})
				setLivePrices(prev => ({ ...prev, ...newPrices }))
			}
		} catch (err) {
			console.error('Failed to poll watchlist prices:', err)
		}
	}

	// Start/stop polling based on market status (only when market is closed)
	useEffect(() => {
		if (!marketStatus?.is_open && watchlist.length > 0 && !wsConnection) {
			// Poll immediately
			pollWatchlistPrices()
			
			// Set up interval polling every 30 seconds
			const interval = setInterval(pollWatchlistPrices, 30000)
			setPollingInterval(interval)
		} else {
			if (pollingInterval) {
				clearInterval(pollingInterval)
				setPollingInterval(null)
			}
		}

		return () => {
			if (pollingInterval) {
				clearInterval(pollingInterval)
			}
		}
	}, [marketStatus?.is_open, watchlist.length, wsConnection])

	// Format price display
	const formatPrice = (price) => {
		if (price === null || price === undefined) return 'N/A'
		return typeof price === 'number' ? price.toFixed(2) : price
	}

	// Format percentage display
	const formatPercentage = (pct) => {
		if (pct === null || pct === undefined) return 'N/A'
		const num = typeof pct === 'number' ? pct : parseFloat(pct)
		return isNaN(num) ? 'N/A' : `${num >= 0 ? '+' : ''}${num.toFixed(2)}%`
	}

	// Get price color based on change
	const getPriceColor = (changePct) => {
		if (changePct === null || changePct === undefined) return 'var(--text-muted)'
		const num = typeof changePct === 'number' ? changePct : parseFloat(changePct)
		if (isNaN(num)) return 'var(--text-muted)'
		return num >= 0 ? '#22c55e' : '#ef4444'
	}

	return (
		<div className="watchlist-panel">
			<Card variant="elevated" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
				<CardHeader style={{ padding: '16px', borderBottom: '1px solid var(--border-color)' }}>
					<div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
						<Typography variant="h3" style={{ margin: 0, fontSize: '16px', color: '#ffffff' }}>
							Watchlist
						</Typography>
						<Button
							variant="ghost"
							size="sm"
							onClick={() => setIsCollapsed(!isCollapsed)}
							style={{ padding: '4px 8px', minWidth: 'auto' }}
						>
							{isCollapsed ? '▼' : '▲'}
						</Button>
					</div>
				</CardHeader>

				{!isCollapsed && (
					<CardContent style={{ padding: '16px', flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
						{/* Search Bar */}
						<div style={{ marginBottom: '16px', position: 'relative' }}>
							<div style={{ position: 'relative' }}>
								<input
									type="text"
									placeholder="Search stocks..."
									value={searchQuery}
									onChange={handleSearchChange}
									style={{
										width: '100%',
										padding: '8px 12px',
										paddingRight: searchLoading ? '32px' : '12px',
										backgroundColor: 'var(--bg-tertiary)',
										border: '1px solid var(--border-color)',
										borderRadius: '6px',
										color: 'var(--text-color)',
										fontSize: '14px',
										outline: 'none'
									}}
								/>
								{searchLoading && (
									<div style={{
										position: 'absolute',
										right: '8px',
										top: '50%',
										transform: 'translateY(-50%)',
										width: '16px',
										height: '16px',
										border: '2px solid var(--border-color)',
										borderTop: '2px solid var(--accent-color)',
										borderRadius: '50%',
										animation: 'spin 1s linear infinite'
									}} />
								)}
							</div>
							
							{/* Search Results */}
							{searchResults.length > 0 && (
								<div className="search-results">
									{searchResults.map((stock, index) => (
										<div
											key={index}
											onClick={() => addToWatchlist(stock)}
											style={{
												padding: '8px 12px',
												cursor: 'pointer',
												borderBottom: index < searchResults.length - 1 ? '1px solid var(--border-color)' : 'none',
												display: 'flex',
												justifyContent: 'space-between',
												alignItems: 'center'
											}}
											onMouseEnter={(e) => e.target.style.backgroundColor = 'var(--bg-tertiary)'}
											onMouseLeave={(e) => e.target.style.backgroundColor = 'transparent'}
										>
											<div>
												<div style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-color)' }}>
													{stock.symbol}
												</div>
												<div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
													{stock.company_name}
												</div>
											</div>
											<div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
												{stock.exchange}
											</div>
										</div>
									))}
								</div>
							)}
						</div>

						{/* Watchlist Stocks */}
						<div style={{ flex: 1, overflowY: 'auto' }}>
							{watchlist.length === 0 ? (
								<div style={{
									textAlign: 'center',
									padding: '32px 16px',
									color: 'var(--text-muted)',
									fontSize: '14px'
								}}>
									No stocks in watchlist
									<br />
									<small>Search and add stocks above</small>
								</div>
							) : (
								<div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
									{watchlist.map((stock) => {
										const priceData = livePrices[stock.symbol]
										return (
											<div
												key={stock.id}
												style={{
													padding: '12px',
													backgroundColor: 'var(--bg-tertiary)',
													borderRadius: '6px',
													border: '1px solid var(--border-color)',
													display: 'flex',
													justifyContent: 'space-between',
													alignItems: 'center'
												}}
											>
												<div style={{ flex: 1 }}>
								<div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
									<div style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-color)' }}>
										{stock.company_name}
									</div>
									<Button
															variant="ghost"
															size="sm"
															onClick={() => removeFromWatchlist(stock.symbol)}
															style={{ padding: '2px 6px', minWidth: 'auto', fontSize: '12px' }}
														>
															×
														</Button>
								</div>
													{priceData ? (
									<div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
										<div style={{ fontSize: '12px', color: getPriceColor(priceData.change_pct) }}>
											{formatPrice(priceData.ltp || priceData.close)}
										</div>
									</div>
													) : (
														<div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
															{marketStatus?.is_open ? 'Loading...' : 'No data'}
														</div>
													)}
													{priceData?.change_pct && (
														<div style={{ fontSize: '11px', color: getPriceColor(priceData.change_pct), textAlign: 'right' }}>
															{formatPercentage(priceData.change_pct)}
														</div>
													)}
												</div>
											</div>
										)
									})}
								</div>
							)}
						</div>
					</CardContent>
				)}
			</Card>
		</div>
	)
}
