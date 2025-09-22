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
			action: () => navigate('/backtest')
		},
		{
			title: 'Strategy Builder',
			action: () => navigate('/builder')
		},
		{
			title: 'View Results',
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
		<div className="home-layout">
			<div className="home-main">
				<div className="features-grid">
					{mainFeatures.map((feature, index) => (
						<Card
							key={index}
							variant="elevated"
							className="feature-card"
							style={{
								cursor: 'pointer',
								// Keep consistent minimum height; avoids overly tall cards
								minHeight: '50px',
								border: '1px solid rgba(255, 255, 255, 0.1)',
								background: 'rgba(255, 255, 255, 0.02)',
								transition: 'all 0.3s ease',
								backdropFilter: 'blur(10px)'
							}}
							onClick={feature.action}
						>
							<CardContent>
								<div style={{
									display: 'flex',
									flexDirection: 'column',
									// Remove forced stretch inside cards
									// height: '100%',
									gap: 'var(--space-3)',
									alignItems: 'center',
									textAlign: 'center'
								}}>
									<div style={{
										fontSize: '32px',
										lineHeight: 1
									}}>
										{feature.icon}
									</div>
									<Typography variant="h3" style={{ margin: 0, fontSize: '16px', color: '#ffffff' }}>
										{feature.title}
									</Typography>
									<Typography variant="caption" color="secondary" style={{ margin: 0, fontSize: '12px', color: 'rgba(255, 255, 255, 0.7)' }}>
										{feature.description}
									</Typography>
								</div>
							</CardContent>
						</Card>
					))}
				</div>
			</div>
			<div className="home-sidebar">
				<WatchlistPanel />
			</div>
		</div>
	)
}
