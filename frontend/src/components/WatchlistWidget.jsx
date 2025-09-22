import React, { useState, useEffect, useRef, useCallback } from 'react'

export default function WatchlistWidget() {
	const [searchQuery, setSearchQuery] = useState('')
	const [searchResults, setSearchResults] = useState([])
	const [watchlist, setWatchlist] = useState([])
	const [marketStatus, setMarketStatus] = useState(null)
	const [loading, setLoading] = useState(false)
	const [error, setError] = useState('')
	const [wsConnection, setWsConnection] = useState(null)
	const [livePrices, setLivePrices] = useState({})
	const [draggedItem, setDraggedItem] = useState(null)
	const [draggedOverItem, setDraggedOverItem] = useState(null)
	const searchTimeoutRef = useRef(null)
	const searchContainerRef = useRef(null)

	const apiBase = import.meta.env.VITE_API_BASE_URL || ''
	const wsBase = apiBase.replace('http', 'ws')

	// Check market status on component mount
	useEffect(() => {
		checkMarketStatus()
		loadWatchlist()
		// Seed cached prices for any previously saved symbols
		try {
			const saved = JSON.parse(localStorage.getItem('trading_watchlist') || '[]')
			if (Array.isArray(saved) && saved.length > 0) {
				const seeded = {}
				saved.forEach(item => {
					const cache = JSON.parse(localStorage.getItem(`ltp:${item.symbol}`) || 'null')
					if (cache && typeof cache === 'object') {
						seeded[item.symbol] = cache
					}
				})
				if (Object.keys(seeded).length > 0) {
					setLivePrices(prev => ({ ...seeded, ...prev }))
				}
			}
		} catch (_) {}
	}, [])

	// Click outside handler for search results
	useEffect(() => {
		const handleClickOutside = (event) => {
			if (searchContainerRef.current && !searchContainerRef.current.contains(event.target)) {
				setSearchResults([])
			}
		}

		document.addEventListener('mousedown', handleClickOutside)
		return () => {
			document.removeEventListener('mousedown', handleClickOutside)
		}
	}, [])

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
	}, [marketStatus?.is_open, watchlist])

	// Subscribe to new stocks when they're added
	useEffect(() => {
		if (wsConnection && wsConnection.readyState === WebSocket.OPEN && watchlist.length > 0) {
			// Subscribe to all watchlist stocks
			watchlist.forEach(stock => {
				const subscriptionData = {
					action: 'subscribe',
					symbol: stock.symbol || stock.token || '',
					exchange_code: stock.exchange || stock.exchange_code || 'NSE',
					product_type: 'cash'
				}
				console.log('Re-subscribing to stock:', subscriptionData)
				wsConnection.send(JSON.stringify(subscriptionData))
			})
		}
	}, [watchlist.length, wsConnection])

	// Whenever the watchlist changes, seed price cache for newly added symbols
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

	const checkMarketStatus = async () => {
		try {
			const response = await fetch(`${apiBase}/api/market/status`)
			const data = await response.json()
			if (data.success) {
				setMarketStatus(data)
			}
		} catch (err) {
			console.error('Failed to check market status:', err)
		}
	}

	const loadWatchlist = () => {
		try {
			const saved = localStorage.getItem('trading_watchlist')
			if (saved) {
				setWatchlist(JSON.parse(saved))
			}
		} catch (err) {
			console.error('Failed to load watchlist:', err)
		}
	}

	const saveWatchlist = (newWatchlist) => {
		try {
			localStorage.setItem('trading_watchlist', JSON.stringify(newWatchlist))
		} catch (err) {
			console.error('Failed to save watchlist:', err)
		}
	}

	const searchStocks = useCallback(async (query) => {
		if (!query || query.length < 2) {
			setSearchResults([])
			return
		}

		setLoading(true)
		setError('')
		
		try {
			const response = await fetch(`${apiBase}/api/instruments/live-trading?q=${encodeURIComponent(query)}&limit=20`)
			const data = await response.json()
			
			if (data.success) {
				setSearchResults(data.items || [])
			} else {
				setError(data.error || 'Search failed')
				setSearchResults([])
			}
		} catch (err) {
			setError('Failed to search stocks')
			setSearchResults([])
		} finally {
			setLoading(false)
		}
	}, [apiBase])

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

	const connectWebSocket = () => {
		if (wsConnection) {
			wsConnection.close()
		}

		const ws = new WebSocket(`${wsBase}/ws/stocks`)
		setWsConnection(ws)

		ws.onopen = () => {
			console.log('WebSocket connected for watchlist')
			// Subscribe to all watchlist stocks
			watchlist.forEach(stock => {
				const subscriptionData = {
					action: 'subscribe',
					symbol: stock.symbol || stock.token || '',
					exchange_code: stock.exchange || stock.exchange_code || 'NSE',
					product_type: 'cash'
				}
				console.log('Subscribing to stock:', subscriptionData)
				ws.send(JSON.stringify(subscriptionData))
			})
		}

		ws.onmessage = (event) => {
			try {
				const data = JSON.parse(event.data)
				console.log('WebSocket received data:', data)
				if (data.type === 'tick' && data.symbol) {
					console.log('Updating live price for symbol:', data.symbol, 'with data:', data)
					setLivePrices(prev => ({
						...prev,
						[data.symbol]: {
							ltp: data.ltp,
							change_pct: data.change_pct,
							bid: data.bid,
							ask: data.ask,
							timestamp: data.timestamp,
							status: 'live'
						}
					}))

					// Persist last-known values so they are available when market is closed
					try {
						localStorage.setItem(`ltp:${data.symbol}`, JSON.stringify({
							ltp: data.ltp,
							change_pct: data.change_pct,
							bid: data.bid,
							ask: data.ask,
							timestamp: data.timestamp
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

	const addToWatchlist = (stock) => {
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
		}
	}

	const removeFromWatchlist = (stockId) => {
		const newWatchlist = watchlist.filter(s => s.id !== stockId)
		setWatchlist(newWatchlist)
		saveWatchlist(newWatchlist)
	}

	const handleDragStart = (e, stock) => {
		setDraggedItem(stock)
		e.dataTransfer.effectAllowed = 'move'
		e.dataTransfer.setData('text/html', e.target.outerHTML)
	}

	const handleDragOver = (e, stock) => {
		e.preventDefault()
		e.dataTransfer.dropEffect = 'move'
		setDraggedOverItem(stock)
	}

	const handleDragLeave = () => {
		setDraggedOverItem(null)
	}

	const handleDrop = (e, targetStock) => {
		e.preventDefault()
		if (draggedItem && targetStock && draggedItem.id !== targetStock.id) {
			const draggedIndex = watchlist.findIndex(item => item.id === draggedItem.id)
			const targetIndex = watchlist.findIndex(item => item.id === targetStock.id)
			
			const newWatchlist = [...watchlist]
			const [draggedStock] = newWatchlist.splice(draggedIndex, 1)
			newWatchlist.splice(targetIndex, 0, draggedStock)
			
			setWatchlist(newWatchlist)
			saveWatchlist(newWatchlist)
		}
		setDraggedItem(null)
		setDraggedOverItem(null)
	}

	const handleDragEnd = () => {
		setDraggedItem(null)
		setDraggedOverItem(null)
	}

	const formatPrice = (price) => {
		if (typeof price !== 'number') return '--'
		return price.toFixed(2)
	}

	const formatChange = (change) => {
		if (typeof change !== 'number') return '--'
		const sign = change >= 0 ? '+' : ''
		return `${sign}${change.toFixed(2)}%`
	}

	const getChangeColor = (change) => {
		if (typeof change !== 'number') return 'var(--muted)'
		return change >= 0 ? '#57d38c' : '#ff5c5c'
	}

	return (
		<div className="watchlist-widget" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
			{/* Header */}
			<div style={{ marginBottom: '16px' }}>
				<h3 style={{ 
					color: 'var(--text)', 
					margin: '0 0 8px 0', 
					fontSize: '18px',
					fontWeight: 'bold'
				}}>
					📋 My Watchlist
				</h3>
				<p style={{ 
					color: 'var(--muted)', 
					margin: '0 0 12px 0', 
					fontSize: '12px' 
				}}>
					Search and manage your stocks
				</p>
			</div>

			{/* Search Bar */}
			<div 
				ref={searchContainerRef}
				className="watchlist-search"
				style={{
					marginBottom: '16px',
					position: 'relative',
					zIndex: 1000
				}}
			>
				<div 
					className="search-container"
					style={{
						position: 'relative',
						display: 'flex',
						alignItems: 'center',
						backgroundColor: 'var(--panel)',
						border: '1px solid rgba(255,255,255,0.08)',
						borderRadius: '6px',
						padding: '8px 12px',
						transition: 'border-color 0.2s'
					}}
				>
					<div 
						className="search-icon"
						style={{
							color: 'var(--muted)',
							marginRight: '8px',
							fontSize: '14px'
						}}
					>
						🔍
					</div>
					<input
						type="text"
						placeholder="Search & add items"
						value={searchQuery}
						onChange={(e) => setSearchQuery(e.target.value)}
						style={{
							flex: 1,
							background: 'transparent',
							border: 'none',
							outline: 'none',
							color: 'var(--text)',
							fontSize: '13px',
							'::placeholder': {
								color: 'var(--muted)'
							}
						}}
					/>
					{searchQuery && (
						<button
							onClick={() => setSearchQuery('')}
							style={{
								background: 'transparent',
								border: 'none',
								color: 'var(--muted)',
								cursor: 'pointer',
								padding: '2px',
								marginRight: '6px',
								borderRadius: '3px',
								opacity: 0.7,
								transition: 'opacity 0.2s',
								fontSize: '12px'
							}}
							onMouseEnter={(e) => e.target.style.opacity = '1'}
							onMouseLeave={(e) => e.target.style.opacity = '0.7'}
							title="Clear search"
						>
							×
						</button>
					)}
				</div>

				{/* Search Results */}
				{searchResults.length > 0 && (
					<div 
						className="search-results-dropdown"
						style={{
							position: 'absolute',
							top: '100%',
							left: 0,
							right: 0,
							backgroundColor: '#1a1a1a',
							border: '1px solid #333',
							borderRadius: '6px',
							marginTop: '4px',
							boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
							zIndex: 1001,
							maxHeight: '200px',
							overflowY: 'auto',
							overflow: 'hidden'
						}}
					>
						{searchResults.slice(0, 5).map((stock, index) => {
							// Extract clean symbol
							const getDisplaySymbol = (stock) => {
								const companyName = stock.company_name || stock.short_name || ''
								const patterns = [
									/^([A-Z]{2,6})\s/,
									/^([A-Z]+)\s/,
									/([A-Z]{2,6})\s+LTD/i,
									/([A-Z]{2,6})\s+LIMITED/i
								]
								
								for (const pattern of patterns) {
									const match = companyName.match(pattern)
									if (match && match[1]) {
										return match[1]
									}
								}
								
								const firstWord = companyName.split(' ')[0]
								if (firstWord && firstWord.length <= 8) {
									return firstWord
								}
								
								return stock.token || stock.symbol
							}
							
							const displaySymbol = getDisplaySymbol(stock)
							const isAlreadyInWatchlist = watchlist.some(w => w.symbol === stock.symbol)
							
							return (
								<div
									key={`${stock.symbol}_${stock.exchange}`}
									className="search-result-item"
									style={{
										display: 'flex',
										alignItems: 'center',
										padding: '8px 12px',
										borderBottom: index < Math.min(searchResults.length, 5) - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
										cursor: 'pointer',
										transition: 'background-color 0.2s',
										backgroundColor: 'transparent'
									}}
									onMouseEnter={(e) => {
										e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'
									}}
									onMouseLeave={(e) => {
										e.currentTarget.style.backgroundColor = 'transparent'
									}}
								>
									<div 
										className="search-icon"
										style={{
											color: 'var(--muted)',
											marginRight: '8px',
											fontSize: '12px'
										}}
									>
										🔍
									</div>
									<div 
										className="stock-info"
										style={{
											flex: 1,
											display: 'flex',
											flexDirection: 'column',
											gap: '1px'
										}}
									>
										<div 
											className="stock-name"
											style={{
												fontWeight: 'bold',
												fontSize: '12px',
												color: 'var(--text)',
												overflow: 'hidden',
												textOverflow: 'ellipsis',
												whiteSpace: 'nowrap'
											}}
										>
											{stock.company_name || stock.short_name}
										</div>
									</div>
									<button
										onClick={(e) => {
											e.stopPropagation()
											if (!isAlreadyInWatchlist) {
												addToWatchlist(stock)
											}
										}}
										disabled={isAlreadyInWatchlist}
										style={{
											background: isAlreadyInWatchlist ? 'var(--muted)' : 'var(--accent)',
											color: 'white',
											border: 'none',
											borderRadius: '3px',
											padding: '4px 8px',
											fontSize: '10px',
											fontWeight: 'bold',
											cursor: isAlreadyInWatchlist ? 'not-allowed' : 'pointer',
											opacity: isAlreadyInWatchlist ? 0.5 : 1,
											transition: 'all 0.2s'
										}}
										title={isAlreadyInWatchlist ? 'Already in watchlist' : 'Add to watchlist'}
									>
										{isAlreadyInWatchlist ? '✓' : '+'}
									</button>
								</div>
							)
						})}
					</div>
				)}
			</div>

			{/* Watchlist Table */}
			<div style={{ flex: 1, overflow: 'hidden' }}>
				{watchlist.length === 0 ? (
					<div 
						className="empty-watchlist"
						style={{
							textAlign: 'center',
							padding: '20px',
							color: 'var(--muted)',
							backgroundColor: 'rgba(255,255,255,0.03)',
							borderRadius: '6px',
							border: '1px dashed rgba(255,255,255,0.1)',
							fontSize: '12px'
						}}
					>
						<div style={{ marginBottom: '8px' }}>📋</div>
						<div>Your watchlist is empty</div>
						<div style={{ fontSize: '10px', marginTop: '4px' }}>
							Search above to add stocks
						</div>
					</div>
				) : (
					<div 
						className="watchlist-table"
						style={{
							backgroundColor: 'var(--panel)',
							borderRadius: '6px',
							border: '1px solid rgba(255,255,255,0.08)',
							overflow: 'hidden',
							height: '100%',
							display: 'flex',
							flexDirection: 'column',
							position: 'relative',
							zIndex: 1
						}}
					>
						{/* Table Header */}
						<div 
							className="table-header"
							style={{
								display: 'grid',
								gridTemplateColumns: '1fr auto auto',
								gap: '12px',
								padding: '8px 12px',
								backgroundColor: 'rgba(255,255,255,0.05)',
								borderBottom: '1px solid rgba(255,255,255,0.08)',
								fontWeight: 'bold',
								fontSize: '11px',
								color: 'var(--text)'
							}}
						>
							<div>Name</div>
							<div style={{ textAlign: 'right' }}>Price</div>
							<div style={{ textAlign: 'right' }}>Change</div>
						</div>

						{/* Table Body */}
						<div className="table-body" style={{ flex: 1, overflowY: 'auto' }}>
							{watchlist.map((stock, index) => {
								const liveData = livePrices[stock.symbol] || {}
								const isDragging = draggedItem?.id === stock.id
								const isDragOver = draggedOverItem?.id === stock.id
								
								// Extract clean symbol
								const getDisplaySymbol = (stock) => {
									const companyName = stock.company_name || stock.short_name || ''
									const patterns = [
										/^([A-Z]{2,6})\s/,
										/^([A-Z]+)\s/,
										/([A-Z]{2,6})\s+LTD/i,
										/([A-Z]{2,6})\s+LIMITED/i
									]
									
									for (const pattern of patterns) {
										const match = companyName.match(pattern)
										if (match && match[1]) {
											return match[1]
										}
									}
									
									const firstWord = companyName.split(' ')[0]
									if (firstWord && firstWord.length <= 8) {
										return firstWord
									}
									
									return stock.token || stock.symbol
								}
								
								const displaySymbol = getDisplaySymbol(stock)
								
								return (
									<div
										key={stock.id}
										className="table-row"
										draggable
										onDragStart={(e) => handleDragStart(e, stock)}
										onDragOver={(e) => handleDragOver(e, stock)}
										onDragLeave={handleDragLeave}
										onDrop={(e) => handleDrop(e, stock)}
										onDragEnd={handleDragEnd}
										style={{
											display: 'grid',
											gridTemplateColumns: '1fr auto auto',
											gap: '12px',
											padding: '8px 12px',
											borderBottom: index < watchlist.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
											cursor: 'grab',
											transition: 'all 0.2s ease',
											backgroundColor: isDragOver ? 'rgba(255,255,255,0.05)' : 'transparent',
											opacity: isDragging ? 0.5 : 1,
											transform: isDragging ? 'rotate(1deg)' : 'none'
										}}
										onMouseEnter={(e) => {
											if (!isDragging) {
												e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.03)'
											}
										}}
										onMouseLeave={(e) => {
											if (!isDragging && !isDragOver) {
												e.currentTarget.style.backgroundColor = 'transparent'
											}
										}}
									>
										{/* Stock Name */}
										<div 
											className="stock-info"
											style={{
												display: 'flex',
												alignItems: 'center',
												gap: '8px'
											}}
										>
											<div 
												className="drag-handle"
												style={{
													width: '12px',
													height: '12px',
													display: 'flex',
													alignItems: 'center',
													justifyContent: 'center',
													color: 'var(--muted)',
													cursor: 'grab',
													fontSize: '10px'
												}}
											>
												⋮⋮
											</div>
											<div style={{ flex: 1, minWidth: 0 }}>
												<div 
													className="stock-name"
													style={{
														fontWeight: 'bold',
														fontSize: '12px',
														color: 'var(--text)',
														overflow: 'hidden',
														textOverflow: 'ellipsis',
														whiteSpace: 'nowrap'
													}}
												>
													{stock.company_name || stock.short_name}
												</div>
											</div>
											<button
												onClick={(e) => {
													e.stopPropagation()
													removeFromWatchlist(stock.id)
												}}
												style={{
													background: 'transparent',
													border: 'none',
													color: 'var(--muted)',
													cursor: 'pointer',
													padding: '2px',
													borderRadius: '3px',
													opacity: 0.7,
													transition: 'opacity 0.2s',
													fontSize: '10px'
												}}
												onMouseEnter={(e) => {
													e.target.style.opacity = '1'
													e.target.style.color = 'var(--danger)'
												}}
												onMouseLeave={(e) => {
													e.target.style.opacity = '0.7'
													e.target.style.color = 'var(--muted)'
												}}
												title="Remove from watchlist"
											>
												×
											</button>
										</div>

										{/* Market Price */}
										<div 
											className="market-price"
											style={{
												textAlign: 'right',
												fontWeight: 'bold',
												fontSize: '11px',
												color: 'var(--text)'
											}}
										>
											{marketStatus?.is_open && liveData.ltp ? 
												`₹${formatPrice(liveData.ltp)}` : 
												'--'
											}
										</div>

										{/* Change */}
										<div 
											className="change"
											style={{
												textAlign: 'right',
												fontWeight: 'bold',
												fontSize: '10px',
												color: marketStatus?.is_open && liveData.change_pct ? 
													getChangeColor(liveData.change_pct) : 
													'var(--muted)'
											}}
										>
											{marketStatus?.is_open && liveData.change_pct ? 
												formatChange(liveData.change_pct) : 
												'--'
											}
										</div>
									</div>
								)
							})}
						</div>
					</div>
				)}
			</div>
		</div>
	)
}
