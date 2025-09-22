import React, { useEffect, useMemo, useState } from 'react'
import { Card, CardHeader, CardContent } from '../components/ui/Card'
import Button from '../components/ui/Button'
import Typography from '../components/ui/Typography'
import { useNavigate } from 'react-router-dom'
import WatchlistPanel from '../components/WatchlistPanel'

export default function HomePage() {
	const [firstName, setFirstName] = useState('')
	const [loading, setLoading] = useState(true)
	const [error, setError] = useState('')
	const navigate = useNavigate()
	const apiBase = import.meta.env.VITE_API_BASE_URL || ''
	const api = useMemo(() => (apiBase || '').replace(/\/$/, ''), [apiBase])

	useEffect(() => {
		let cancelled = false
		async function load() {
			setLoading(true)
			setError('')
			try {
				const sess = sessionStorage.getItem('api_session') || ''
				const url = new URL(`${api}/api/profile`)
				if (sess) url.searchParams.set('api_session', sess)
				const res = await fetch(url.toString())
				const j = await res.json().catch(() => ({}))
				if (!cancelled && j?.success) {
					setFirstName(j?.first_name || '')
				}
			} catch (e) {
				if (!cancelled) setError('')
			} finally {
				if (!cancelled) setLoading(false)
			}
		}
		// Add a timeout to prevent infinite loading
		const timeout = setTimeout(() => {
			if (!cancelled) setLoading(false)
		}, 3000)
		load()
		return () => { 
			cancelled = true
			clearTimeout(timeout)
		}
	}, [api])

	const mainFeatures = [
		{
			title: 'Backtest Strategy',
			icon: '📊',
			description: 'Test your strategies',
			action: () => navigate('/backtest')
		},
		{
			title: 'Strategy Builder',
			icon: '🔧',
			description: 'Build custom strategies',
			action: () => navigate('/builder')
		},
		{
			title: 'View Results',
			icon: '📋',
			description: 'Analyze performance',
			action: () => navigate('/results')
		}
	]

	const quickLinks = []

	if (loading) {
		return (
			<div style={{ width: '100%', maxWidth: '1200px', margin: '0 auto', padding: 'var(--space-8)' }}>
				<Card variant="elevated">
					<CardContent>
						<div style={{
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							padding: 'var(--space-12)'
						}}>
							<div className="spinner" style={{ width: '32px', height: '32px' }}></div>
						</div>
					</CardContent>
				</Card>
			</div>
		)
	}

	return (
		<div style={{ 
			display: 'grid', 
			gridTemplateColumns: '1fr 400px', 
			gap: '24px', 
			height: '100%',
			minHeight: '600px'
		}}>
			{/* Left Column - Main Features */}
			<div style={{ display: 'flex', flexDirection: 'column' }}>
				{/* Welcome Header */}
				<div style={{ marginBottom: '24px' }}>
					<h1 style={{ 
						color: 'var(--text)', 
						margin: '0 0 8px 0', 
						fontSize: '28px',
						fontWeight: 'bold'
					}}>
						Welcome{firstName ? `, ${firstName}` : ''}! 👋
					</h1>
					<p style={{ 
						color: 'var(--muted)', 
						margin: '0', 
						fontSize: '16px' 
					}}>
						Choose a feature to get started with your trading journey
					</p>
				</div>

				{/* Features Grid */}
				<div className="features-grid" style={{
					display: 'grid',
					gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))',
					gap: '16px',
					flex: 1
				}}>
					{mainFeatures.map((feature, index) => (
						<Card
							key={index}
							variant="elevated"
							className="feature-card"
							style={{
								cursor: 'pointer',
								minHeight: '120px',
								border: '1px solid rgba(255, 255, 255, 0.1)',
								background: 'rgba(255, 255, 255, 0.02)',
								transition: 'all 0.3s ease',
								backdropFilter: 'blur(10px)',
								display: 'flex',
								flexDirection: 'column'
							}}
							onClick={feature.action}
							onMouseEnter={(e) => {
								e.currentTarget.style.transform = 'translateY(-2px)'
								e.currentTarget.style.boxShadow = '0 8px 25px rgba(0,0,0,0.15)'
								e.currentTarget.style.borderColor = 'rgba(79, 156, 255, 0.3)'
							}}
							onMouseLeave={(e) => {
								e.currentTarget.style.transform = 'translateY(0)'
								e.currentTarget.style.boxShadow = 'none'
								e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.1)'
							}}
						>
							<CardContent style={{ 
								display: 'flex', 
								flexDirection: 'column', 
								height: '100%',
								padding: '20px'
							}}>
								<div style={{
									display: 'flex',
									flexDirection: 'column',
									height: '100%',
									gap: '12px',
									alignItems: 'center',
									textAlign: 'center'
								}}>
									<div style={{
										fontSize: '36px',
										lineHeight: 1,
										marginBottom: '4px'
									}}>
										{feature.icon}
									</div>
									<Typography variant="h3" style={{ 
										margin: '0 0 4px 0', 
										fontSize: '18px', 
										color: '#ffffff',
										fontWeight: 'bold'
									}}>
										{feature.title}
									</Typography>
									<Typography variant="caption" color="secondary" style={{ 
										margin: '0', 
										fontSize: '13px', 
										color: 'rgba(255, 255, 255, 0.7)',
										lineHeight: 1.4
									}}>
										{feature.description}
									</Typography>
								</div>
							</CardContent>
						</Card>
					))}
				</div>
			</div>

			{/* Right Column - Watchlist Panel */}
			<div style={{ 
				display: 'flex', 
				flexDirection: 'column',
				height: '100%'
			}}>
				<WatchlistPanel />
			</div>
		</div>
	)
}
