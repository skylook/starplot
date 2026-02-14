#!/usr/bin/env python3
"""
Direct plotly PNG test with simple data
"""
import plotly.graph_objects as go
import numpy as np

print("📊 Testing direct plotly PNG export...")

# Create a simple plotly figure to test PNG export
fig = go.Figure()

# Add simple test data
x = np.array([1, 2, 3, 4, 5])
y = np.array([1, 4, 2, 8, 5])

fig.add_trace(go.Scatter(
    x=x, y=y,
    mode='markers',
    marker=dict(size=10, color='blue'),
    name='Test Points'
))

fig.update_layout(
    title="Test Plotly Figure",
    width=800,
    height=600
)

print("   Created simple plotly figure")

try:
    fig.write_image("test_plotly_direct.png")
    print("✅ Direct plotly PNG export successful!")
    
    # Also test HTML
    fig.write_html("test_plotly_direct.html")
    print("✅ Direct plotly HTML export successful!")
    
except Exception as e:
    print(f"❌ Direct plotly PNG export failed: {e}")

print("✅ Direct plotly test complete")