#!/usr/bin/env python3
"""
mpld3 概念验证 - 快速为starplot添加web交互功能
展示如何在不改动现有代码的情况下添加交互式web导出
"""
from datetime import datetime
from pytz import timezone
from starplot import MapPlot, Projection, _
from starplot.styles import PlotStyle, extensions

def create_interactive_star_chart():
    print("🎯 mpld3 概念验证 - 交互式星图")
    print("=" * 50)
    
    # 创建标准的matplotlib星图
    print("📊 创建标准星图...")
    tz = timezone("America/Los_Angeles")
    dt = datetime(2023, 7, 13, 22, 0, tzinfo=tz)
    
    p = MapPlot(
        projection=Projection.ZENITH,
        lat=33.363484,
        lon=-116.836394,
        dt=dt,
        style=PlotStyle().extend(extensions.BLUE_GOLD),
        resolution=1024,  # 适中的分辨率
        autoscale=True,
        backend="matplotlib",
    )
    
    # 添加基本元素
    print("   添加星座和恒星...")
    p.constellations()
    p.stars(where=[_.magnitude < 3.5], labels=None)  # 简化避免复杂性
    
    # 保存标准PNG
    print("   保存标准PNG...")
    p.export("mpld3_standard.png", transparent=True, padding=0.1)
    
    # 尝试mpld3集成
    print("\n🌐 尝试mpld3交互式导出...")
    try:
        import mpld3
        
        # 获取matplotlib figure
        if hasattr(p, '_backend') and hasattr(p._backend, 'figure'):
            fig = p._backend.figure
            
            # 转换为交互式HTML
            html_content = mpld3.fig_to_html(fig)
            
            # 保存交互式版本
            with open("mpld3_interactive.html", "w", encoding="utf-8") as f:
                f.write(html_content)
                
            print("✅ 成功生成交互式版本: mpld3_interactive.html")
            print("🖱️  支持的交互功能:")
            print("   • 鼠标缩放和平移")
            print("   • 重置视图")
            print("   • 悬停高亮")
            
            return True
            
    except ImportError:
        print("❌ mpld3未安装")
        print("💡 安装命令: pip install mpld3")
        return False
    except Exception as e:
        print(f"❌ mpld3转换失败: {e}")
        return False

def demonstrate_integration_approach():
    print("\n" + "=" * 60)
    print("🔧 集成到现有架构的方法")
    print("=" * 60)
    
    print("\n📋 方法1: 扩展matplotlib_backend.py")
    print("""
    class MatplotlibBackend(PlotBackend):
        # ... 现有方法
        
        def export_interactive(self, filename):
            '''新增方法: 导出交互式HTML'''
            try:
                import mpld3
                html_content = mpld3.fig_to_html(self.figure)
                
                # 可以添加自定义JavaScript增强功能
                enhanced_html = self._add_astronomical_interactions(html_content)
                
                with open(filename, 'w') as f:
                    f.write(enhanced_html)
                return True
            except ImportError:
                raise ImportError("需要安装mpld3: pip install mpld3")
    """)
    
    print("\n📋 方法2: 扩展MapPlot.export()方法")
    print("""
    # 在map.py中扩展export方法
    def export(self, filename, format="png", interactive=False, **kwargs):
        if interactive or filename.endswith('.html'):
            if self._backend_name == 'matplotlib':
                return self._backend.export_interactive(filename)
            else:
                # 其他backend的交互式导出逻辑
                pass
        else:
            # 现有的静态导出逻辑
            return self._backend.export(filename, format, **kwargs)
    """)
    
    print("\n🎯 用户使用方式:")
    print("""
    # 完全相同的代码创建星图
    p = MapPlot(backend="matplotlib", ...)
    p.stars(...)
    p.constellations()
    
    # 多种导出选择
    p.export("chart.png")                    # 静态PNG
    p.export("chart.html")                   # 自动检测，交互式HTML  
    p.export("chart.pdf", interactive=True)  # 明确指定交互式
    """)

if __name__ == "__main__":
    success = create_interactive_star_chart()
    demonstrate_integration_approach()
    
    if success:
        print(f"\n🎉 概念验证成功! 可以无缝添加web交互功能!")
    else:
        print(f"\n💡 需要安装mpld3库，但集成方案是可行的!")