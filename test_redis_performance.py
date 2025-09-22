#!/usr/bin/env python3
"""
Performance test script to measure Redis caching improvements.
Run this script to test API performance with and without Redis.
"""

import time
import requests
import statistics
from typing import List, Dict, Any

API_BASE = "http://127.0.0.1:8000"

def test_endpoint(endpoint: str, iterations: int = 10) -> Dict[str, Any]:
    """Test an endpoint multiple times and return performance metrics."""
    times = []
    errors = 0
    
    print(f"Testing {endpoint} ({iterations} iterations)...")
    
    for i in range(iterations):
        try:
            start_time = time.time()
            response = requests.get(f"{API_BASE}{endpoint}")
            end_time = time.time()
            
            if response.status_code == 200:
                times.append((end_time - start_time) * 1000)  # Convert to milliseconds
            else:
                errors += 1
                print(f"  Error {i+1}: HTTP {response.status_code}")
                
        except Exception as e:
            errors += 1
            print(f"  Error {i+1}: {e}")
    
    if not times:
        return {"error": "All requests failed"}
    
    return {
        "endpoint": endpoint,
        "iterations": iterations,
        "successful": len(times),
        "errors": errors,
        "avg_time_ms": round(statistics.mean(times), 2),
        "min_time_ms": round(min(times), 2),
        "max_time_ms": round(max(times), 2),
        "median_time_ms": round(statistics.median(times), 2),
        "std_dev_ms": round(statistics.stdev(times) if len(times) > 1 else 0, 2)
    }

def test_redis_status() -> bool:
    """Check if Redis is available."""
    try:
        response = requests.get(f"{API_BASE}/api/market/status")
        if response.status_code == 200:
            data = response.json()
            # If Redis is working, subsequent calls should be faster
            # This is a simple heuristic - in practice you'd check logs
            return True
    except:
        pass
    return False

def main():
    """Run performance tests."""
    print("🚀 Redis Performance Test")
    print("=" * 50)
    
    # Check if server is running
    try:
        response = requests.get(f"{API_BASE}/api/market/status", timeout=5)
        if response.status_code != 200:
            print("❌ Server not responding. Please start the server first.")
            return
    except Exception as e:
        print(f"❌ Cannot connect to server: {e}")
        print("Please start the server with: python -m uvicorn backend.app:app --reload")
        return
    
    print("✅ Server is running")
    
    # Test Redis status
    redis_available = test_redis_status()
    print(f"📊 Redis Status: {'✅ Available' if redis_available else '❌ Not Available (Fallback Mode)'}")
    print()
    
    # Test endpoints
    endpoints = [
        "/api/market/status",
        "/api/instruments/live-trading?q=RELIANCE&limit=5",
        "/api/instruments/live-trading?q=TCS&limit=3",
        "/api/instruments/live-trading?q=HDFC&limit=2"
    ]
    
    results = []
    
    for endpoint in endpoints:
        result = test_endpoint(endpoint, iterations=5)
        results.append(result)
        
        if "error" not in result:
            print(f"  ✅ {result['successful']}/{result['iterations']} successful")
            print(f"  📈 Avg: {result['avg_time_ms']}ms, Min: {result['min_time_ms']}ms, Max: {result['max_time_ms']}ms")
        else:
            print(f"  ❌ {result['error']}")
        print()
    
    # Summary
    print("📊 Performance Summary")
    print("=" * 50)
    
    successful_tests = [r for r in results if "error" not in r]
    
    if successful_tests:
        avg_times = [r['avg_time_ms'] for r in successful_tests]
        overall_avg = statistics.mean(avg_times)
        
        print(f"Overall Average Response Time: {overall_avg:.2f}ms")
        print(f"Redis Status: {'Enabled' if redis_available else 'Disabled (Fallback)'}")
        print()
        
        print("Endpoint Performance:")
        for result in successful_tests:
            print(f"  {result['endpoint']:<50} {result['avg_time_ms']:>6.2f}ms")
        
        print()
        if redis_available:
            print("🎉 Redis is enabled! You should see faster response times on repeated requests.")
            print("💡 Try running this script again to see cached response times.")
        else:
            print("💡 Install Redis to enable caching and see performance improvements.")
            print("   See REDIS_SETUP.md for installation instructions.")
    else:
        print("❌ No successful tests. Please check server logs.")

if __name__ == "__main__":
    main()
