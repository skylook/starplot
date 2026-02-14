# Plotly Backend 实验文件夹

本文件夹包含了 starplot plotly 后端的实验和开发文件。

## 📁 文件说明

### 核心文件
- `plotly_backend.py` - Plotly 后端实现
- `backend_*.py` - 后端对比测试脚本

### 实验文件
- `star_chart_*_plotly.py` - 星图测试脚本
- `test_*_plotly.py` - 单元测试文件
- `debug_*.py` - 调试脚本

### 结果文件
- `*.html` - Plotly 生成的交互式图表
- `*.png` - 对比测试生成的图像
- `*.json` - 调试数据

## 🎯 实验结论

通过这些实验，我们验证了：
- ✅ Plotly 后端的技术可行性
- ✅ 深度集成架构的有效性
- ❌ Plotly 在复杂天文计算场景下的性能限制

## 💡 最终方案

基于实验结果，最终选择了 **mpld3** 作为 web 交互解决方案：
- 保持 100% matplotlib 兼容性
- 自动获得 web 交互功能
- 无需额外的后端复杂度

这些 plotly 实验文件作为技术探索的记录保留，为未来可能的需求提供参考。