import React from 'react'
import { NavLink } from 'react-router-dom'
import CustomerProfile from './CustomerProfile.jsx'
import { Card, CardContent } from './ui/Card.jsx'

export default function Sidebar() {
	return (
		<aside className="sidebar">
			<div className="brand">Breeze</div>
			<nav>
				<NavLink to="/home" className={({isActive}) => 'nav-item' + (isActive ? ' active' : '')}>Home</NavLink>
				<NavLink to="/backtest" className={({isActive}) => 'nav-item' + (isActive ? ' active' : '')}>Backtest</NavLink>
				<NavLink to="/builder" className={({isActive}) => 'nav-item' + (isActive ? ' active' : '')}>Strategy Builder</NavLink>
				<NavLink to="/results" className={({isActive}) => 'nav-item' + (isActive ? ' active' : '')}>Results</NavLink>
			</nav>
			<div className="sidebar-footer">
				<Card>
					<CardContent>
						<CustomerProfile layout="sidebar" />
					</CardContent>
				</Card>
			</div>
		</aside>
	)
}


