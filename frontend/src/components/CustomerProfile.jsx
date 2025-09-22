import React, { useEffect, useState, useMemo, useRef } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Dropdown, DropdownItem } from './ui/Dropdown.jsx'
import Button from './ui/Button.jsx'

// No longer needed - using inline styles to match Edit Columns modal

export default function CustomerProfile({ layout = 'sidebar' }) {
	const [customerData, setCustomerData] = useState(null)
	const [loading, setLoading] = useState(true)
	const [showDropdown, setShowDropdown] = useState(false)
	const navigate = useNavigate()
	const dropdownRef = useRef(null)
	
	const apiBase = import.meta.env.VITE_API_BASE_URL || ''
	const api = useMemo(() => (apiBase || '').replace(/\/$/, ''), [apiBase])

	function makeUrl(path) {
		try {
			const base = api || window.location.origin
			return new URL(path, base).toString()
		} catch {
			return path
		}
	}

	useEffect(() => {
		let cancelled = false
		async function fetchProfile() {
			setLoading(true)
			try {
				const sess = sessionStorage.getItem('api_session') || ''
				// Prefer the dedicated account details endpoint
				let detailsUrl = makeUrl('/api/account/details')
				if (sess) {
					const u = new URL(detailsUrl)
					u.searchParams.set('api_session', sess)
					detailsUrl = u.toString()
				}
				let res = await fetch(detailsUrl)
				let data = await res.json().catch(() => ({}))
				if (!data?.success || !data?.customer) {
					// Fallback to /profile if needed
					let profileUrl = makeUrl('/api/profile')
					if (sess) {
						const u2 = new URL(profileUrl)
						u2.searchParams.set('api_session', sess)
						profileUrl = u2.toString()
					}
					res = await fetch(profileUrl)
					data = await res.json().catch(() => ({}))
				}
				if (!cancelled && data?.success) {
					const payload = data.customer || data.profile || null
					const profileData = payload?.Success || payload
					if (profileData) setCustomerData(profileData)
				}
			} catch (error) {
				console.error('Failed to fetch customer profile:', error)
			} finally {
				if (!cancelled) setLoading(false)
			}
		}
		
		fetchProfile()
		return () => { cancelled = true }
	}, [api])

	// Handle click outside to close dropdown
	useEffect(() => {
		function handleClickOutside(event) {
			if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
				setShowDropdown(false)
			}
		}

		if (showDropdown) {
			document.addEventListener('mousedown', handleClickOutside)
			return () => document.removeEventListener('mousedown', handleClickOutside)
		}
	}, [showDropdown])

	const handleLogout = () => {
		sessionStorage.removeItem('api_session')
		navigate('/', { replace: true })
	}

	// Extract display name from customer data
	const getDisplayName = () => {
		if (!customerData) return 'User'
		
		// Extract first name from idirect_user_name or user_name
		const fullName = customerData.idirect_user_name || customerData.user_name || ''
		const first = String(fullName).trim().split(/\s+/)[0] || ''
		if (first) return first
		
		// Fallback to email or user ID
		return customerData.email_id || customerData.user_id || 'User'
	}

	const getUserInitials = () => {
		const name = getDisplayName()
		const parts = name.split(' ').filter(p => p.length > 0)
		if (parts.length >= 2) {
			return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
		}
		return name.substring(0, 2).toUpperCase()
	}

	if (loading) {
		return (
			<div className={layout === 'sidebar' ? 'sidebar-profile loading' : 'customer-profile'}>
				<div className="profile-spinner"></div>
			</div>
		)
	}

	if (layout === 'sidebar') {
		return (
			<div className="sidebar-profile" ref={dropdownRef}>
				<Dropdown
					trigger={<div className="sidebar-profile-item"><svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M12 12c2.761 0 5-2.239 5-5s-2.239-5-5-5-5 2.239-5 5 2.239 5 5 5zm0 2c-4.418 0-8 2.239-8 5v1h16v-1c0-2.761-3.582-5-8-5z" stroke="currentColor" strokeWidth="1"/></svg></div>}
					position="top"
				>
					{() => (
						<div className="profile-info">
							{customerData && (
								<>
									<div className="info-item"><span className="info-label">User ID:</span><span className="info-value">{customerData.idirect_userid || customerData.user_id || 'N/A'}</span></div>
									<div className="info-item"><span className="info-label">Name:</span><span className="info-value">{getDisplayName()}</span></div>
								</>
							)}
							<Link to="/holidays" className="sidebar-profile-item">
								<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M3 5h18M8 5v14m8-14v14M3 19h18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
								<span>Holidays</span>
							</Link>
							<DropdownItem onClick={handleLogout}>Logout</DropdownItem>
						</div>
					)}
				</Dropdown>
			</div>
		)
	}

	// Top-right profile button for main layout
	return (
		<div style={{ position: 'relative', display: 'inline-block', zIndex: 10000 }}>
			<button 
				style={{
					width: '40px',
					height: '40px',
					padding: '0',
					background: 'rgba(255, 255, 255, 0.05)',
					border: '1px solid rgba(255, 255, 255, 0.1)',
					borderRadius: '50%',
					color: '#ffffff',
					cursor: 'pointer',
					transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center'
				}}
				onClick={() => {
					console.log('Profile button clicked, current dropdown state:', showDropdown);
					console.log('Customer data:', customerData);
					setShowDropdown(!showDropdown);
				}}
				onMouseEnter={(e) => {
					e.target.style.background = 'rgba(255, 255, 255, 0.1)';
					e.target.style.borderColor = 'rgba(255, 255, 255, 0.2)';
					e.target.style.transform = 'translateY(-2px)';
				}}
				onMouseLeave={(e) => {
					e.target.style.background = 'rgba(255, 255, 255, 0.05)';
					e.target.style.borderColor = 'rgba(255, 255, 255, 0.1)';
					e.target.style.transform = 'translateY(0)';
				}}
			>
				<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
					<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
					<circle cx="12" cy="7" r="4"/>
				</svg>
			</button>
			
			{showDropdown && (
				<div
					ref={dropdownRef}
					style={{
						position: 'absolute',
						top: '100%',
						right: '0',
						marginTop: '8px',
						background: '#1a1a1a',
						border: '1px solid #333',
						borderRadius: '8px',
						padding: '16px',
						minWidth: '280px',
						width: '280px',
						zIndex: 99999,
						boxShadow: '0 4px 12px rgba(0, 0, 0, 0.3)',
						color: '#fff',
						fontFamily: 'inherit'
					}}
					onClick={(e) => e.stopPropagation()}
				>
					{/* Header */}
					<div style={{ marginBottom: '12px', fontSize: '14px', fontWeight: '600', color: '#fff' }}>
						Profile
					</div>
					
					{/* User Info Section */}
					{customerData && (
						<div style={{ marginBottom: '16px', padding: '12px', background: 'rgba(255,255,255,0.05)', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.1)' }}>
							<div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '8px' }}>
								<span style={{ color: 'rgba(255,255,255,0.6)' }}>User ID:</span>
								<span style={{ color: '#fff', fontWeight: '500' }}>{customerData.idirect_userid || customerData.user_id || 'N/A'}</span>
							</div>
							<div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
								<span style={{ color: 'rgba(255,255,255,0.6)' }}>Name:</span>
								<span style={{ color: '#fff', fontWeight: '500' }}>{getDisplayName()}</span>
							</div>
						</div>
					)}

					{/* Menu Items */}
					<div style={{ marginBottom: '16px' }}>
						<div 
							style={{
								display: 'flex',
								alignItems: 'center',
								gap: '8px',
								padding: '10px 12px',
								cursor: 'pointer',
								borderRadius: '6px',
								transition: 'background 0.2s ease',
								color: '#fff'
							}}
							onClick={() => {
								navigate('/holidays');
								setShowDropdown(false);
							}}
							onMouseEnter={(e) => {
								e.target.style.background = 'rgba(255,255,255,0.1)';
							}}
							onMouseLeave={(e) => {
								e.target.style.background = 'transparent';
							}}
						>
							<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
								<path d="M3 5h18M8 5v14m8-14v14M3 19h18" strokeLinecap="round"/>
							</svg>
							<span style={{ fontSize: '13px', fontWeight: '500' }}>Holidays</span>
						</div>
					</div>

					{/* Logout Button */}
					<button
						onClick={handleLogout}
						style={{
							width: '100%',
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							gap: '8px',
							background: 'rgba(248, 113, 113, 0.1)',
							border: '1px solid rgba(248, 113, 113, 0.3)',
							borderRadius: '6px',
							padding: '10px 12px',
							cursor: 'pointer',
							fontSize: '13px',
							fontWeight: '500',
							color: '#f87171',
							transition: 'all 0.2s ease'
						}}
						onMouseEnter={(e) => {
							e.target.style.background = 'rgba(248, 113, 113, 0.2)';
							e.target.style.borderColor = 'rgba(248, 113, 113, 0.5)';
						}}
						onMouseLeave={(e) => {
							e.target.style.background = 'rgba(248, 113, 113, 0.1)';
							e.target.style.borderColor = 'rgba(248, 113, 113, 0.3)';
						}}
					>
						<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
							<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" 
								strokeLinecap="round" strokeLinejoin="round"/>
						</svg>
						Logout
					</button>
				</div>
			)}
		</div>
	)

	return null
}

