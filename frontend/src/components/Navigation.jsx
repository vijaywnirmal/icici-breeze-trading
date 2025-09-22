import React from 'react'
import { useNavigate, useLocation } from 'react-router-dom'

export default function Navigation() {
	const navigate = useNavigate()
	const location = useLocation()
	
	// Get current page name
	const getPageName = (pathname) => {
		switch (pathname) {
			case '/home': return 'Home'
			case '/backtest': return 'Backtest'
			case '/builder': return 'Strategy Builder'
			case '/results': return 'Results'
			case '/holidays': return 'Holidays'
			default: return 'Home'
		}
	}
	
	const currentPage = getPageName(location.pathname)
	const isHomePage = location.pathname === '/home'
	
	return (
		<div style={{
			display: 'flex',
			alignItems: 'center',
			gap: 'var(--space-2)'
		}}>
			{/* Home Button - Only show if not on home page */}
			{!isHomePage && (
				<button
					onClick={() => navigate('/home')}
					style={{
						display: 'flex',
						alignItems: 'center',
						gap: '4px',
						padding: '2px 6px',
						background: 'var(--accent)',
						border: '1px solid var(--accent)',
						borderRadius: 'var(--radius)',
						color: 'white',
						cursor: 'pointer',
						transition: 'all 0.2s ease',
						fontSize: '10px',
						fontWeight: '500',
						minWidth: '50px',
						justifyContent: 'center',
						height: '24px'
					}}
					onMouseEnter={(e) => {
						e.target.style.background = 'var(--accent-hover)'
						e.target.style.borderColor = 'var(--accent-hover)'
					}}
					onMouseLeave={(e) => {
						e.target.style.background = 'var(--accent)'
						e.target.style.borderColor = 'var(--accent)'
					}}
				>
					<svg width="10" height="10" viewBox="0 0 24 24" fill="none">
						<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
						<polyline points="9,22 9,12 15,12 15,22" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
					</svg>
					Home
				</button>
			)}
			
			{/* Current Page Indicator */}
			{!isHomePage && (
				<div style={{
					display: 'flex',
					alignItems: 'center',
					gap: '4px',
					padding: '2px 6px',
					background: 'var(--panel-hover)',
					border: '1px solid var(--border)',
					borderRadius: 'var(--radius)',
					color: 'var(--text-secondary)',
					fontSize: '10px',
					fontWeight: '500',
					minWidth: '60px',
					justifyContent: 'center',
					height: '24px'
				}}>
					<svg width="10" height="10" viewBox="0 0 24 24" fill="none">
						<path d="M9 18l6-6-6-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
					</svg>
					{currentPage}
				</div>
			)}
		</div>
	)
}
