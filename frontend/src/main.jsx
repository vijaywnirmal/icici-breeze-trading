import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import App from './App.jsx'
import ReactLazy from 'react'
const OptionChain = React.lazy(() => import('./pages/OptionChain.jsx'))
import AppLayout from './components/AppLayout.jsx'
import HomePage from './pages/Home.jsx'
import HolidaysPage from './pages/Holidays.jsx'
import BacktestPage from './pages/Backtest.jsx'
import StrategyBuilder from './pages/StrategyBuilder.tsx'
import BacktestResults from './pages/BacktestResults.tsx'
import './styles.css'

// Silence all console output in production and development per request
;(() => {
  const noop = () => {}
  // eslint-disable-next-line no-console
  console.log = noop
  // eslint-disable-next-line no-console
  console.debug = noop
  // eslint-disable-next-line no-console
  console.info = noop
  // eslint-disable-next-line no-console
  console.warn = noop
  // eslint-disable-next-line no-console
  console.error = noop
})()

createRoot(document.getElementById('root')).render(
	<BrowserRouter>
		<Routes>
			<Route path="/" element={<App />} />
			<Route path="/home" element={
				<AppLayout>
					<HomePage />
				</AppLayout>
			} />
			<Route path="/holidays" element={
				<AppLayout>
					<HolidaysPage />
				</AppLayout>
			} />
			<Route path="/backtest" element={
				<AppLayout>
					<BacktestPage />
				</AppLayout>
			} />
			<Route path="/builder" element={
				<AppLayout>
					<StrategyBuilder />
				</AppLayout>
			} />
			<Route path="/results" element={
				<AppLayout>
					<BacktestResults />
				</AppLayout>
			} />
			<Route path="/option-chain" element={
				<AppLayout>
					<React.Suspense fallback={<div style={{padding:12}}>Loading Option Chain...</div>}>
						<OptionChain />
					</React.Suspense>
				</AppLayout>
			} />
			<Route path="*" element={<Navigate to="/" replace />} />
		</Routes>
	</BrowserRouter>
)
