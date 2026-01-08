import streamlit as st
import pandas as pd
import google.generativeai as genai
import time
import io
import os
import requests
import hashlib
import datetime
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor
import matplotlib.pyplot as plt
import seaborn as sns

# ================= 1. 基础配置 =================
st.set_page_config(
    page_title="小红书账号ICU急救站",
    page_icon="🏥",
    layout="wide"
)

# 毒舌专家提示词
SYSTEM_PROMPT = """
# Role: 小红书爆款诊断专家
你是一名拥有百万粉丝操盘经验的小红书运营专家。你说话风格犀利、毒舌、拒绝废话，只看数据和人性。
你的任务是根据用户提供的笔记标题和数据，进行“无情”的诊断，并给出改进方案。

请针对每一条笔记，输出严格的如下格式（不要Markdown，只要纯文本）：
【评分】: <0-100的数字>
【毒舌诊断】: <一句话指出问题，如太学术、无聊、自嗨>
【改写方案A】: <痛点型标题>
【改写方案B】: <利益型标题>
"""

# ================= 2. 安全与授权模块 (核心) =================

def get_daily_token():
    """生成今日动态卡密 (算法：MD5(盐值 + 日期))"""
    if "SECRET_SALT" not in st.secrets:
        st.error("配置错误：请在 Secrets 中设置 SECRET_SALT")
        return None
        
    salt = st.secrets["SECRET_SALT"]
    today = datetime.datetime.now().strftime("%Y%m%d")
    raw = f"{salt}{today}"
    # 取哈希的前6位作为卡密
    return hashlib.md5(raw.encode()).hexdigest()[:6]

def check_auth():
    """处理侧边栏登录逻辑"""
    st.sidebar.header("🔐 会员登录")
    
    # 初始化登录状态
    if "is_logged_in" not in st.session_state:
        st.session_state.is_logged_in = False
    
    # 如果已登录，显示状态和退出按钮
    if st.session_state.is_logged_in:
        st.sidebar.success("✅ 已验证身份")
        if st.sidebar.button("退出登录"):
            st.session_state.is_logged_in = False
            st.rerun()
        return True

    # 如果未登录，显示输入框
    user_input = st.sidebar.text_input("请输入今日卡密", type="password", help="请联系管理员获取")
    btn = st.sidebar.button("验证")
    
    if btn:
        admin_pwd = st.secrets.get("ADMIN_PASSWORD", "admin")
        daily_token = get_daily_token()
        
        # 情况A：管理员登录 (显示今日卡密)
        if user_input == admin_pwd:
            st.sidebar.success("👮 管理员认证成功")
            st.sidebar.markdown("### 🔑 今日卡密 (请复制给用户):")
            st.sidebar.code(daily_token, language="text")
            # 管理员也可以选择直接进入系统
            # st.session_state.is_logged_in = True
            # st.rerun()
            
        # 情况B：用户使用卡密登录
        elif user_input == daily_token:
            st.session_state.is_logged_in = True
            st.sidebar.success("验证成功！")
            st.rerun()
            
        # 情况C：密码错误
        else:
            st.sidebar.error("❌ 卡密无效或已过期")
            
    return False

# ================= 3. 辅助功能 (字体/PDF/AI) =================

@st.cache_resource
def get_chinese_font():
    """下载中文字体防止乱码"""
    font_path = "SimHei.ttf"
    if not os.path.exists(font_path):
        # 使用一个开源字体链接
        url = "https://github.com/StellarCN/scp_zh/raw/master/fonts/SimHei.ttf"
        try:
            r = requests.get(url)
            with open(font_path, "wb") as f:
                f.write(r.content)
        except:
            pass
    return font_path

def analyze_note(model, title, likes, ctr):
    """调用 API 分析"""
    prompt = f"笔记标题：{title}\n数据：点赞 {likes}, 点击率 {ctr}\n请诊断。"
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 响应错误: {str(e)}"

def create_pdf(df, analysis_results, charts_buffer):
    """生成 PDF 报告"""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    font_path = get_chinese_font()
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('SimHei', font_path))
        font_name = 'SimHei'
    else:
        font_name = 'Helvetica'
    
    # 封面
    c.setFillColor(HexColor('#FF2442'))
    c.rect(0, height - 100, width, 100, fill=1, stroke=0)
    c.setFillColor(HexColor('#FFFFFF'))
    c.setFont(font_name, 24)
    c.drawString(30, height - 60, "小红书账号深度诊断报告")
    
    # 插入图表
    if charts_buffer:
        charts_buffer.seek(0)
        with open("temp_chart.png", "wb") as f:
            f.write(charts_buffer.getbuffer())
        c.drawImage("temp_chart.png", 30, height - 450, width=500, height=280)
    
    # 写入文字结果
    c.setFillColor(HexColor('#000000'))
    c.setFont(font_name, 16)
    y = height - 480
    c.drawString(30, y, "二、AI 毒舌急救方案")
    y -= 30
    c.setFont(font_name, 10)
    
    for item in analysis_results:
        if y < 100:
            c.showPage()
            c.setFont(font_name, 10)
            y = height - 50
            
        # 绘制背景块
        c.setFillColor(HexColor('#F5F5F5'))
        c.rect(20, y - 70, width - 40, 80, fill=1, stroke=0)
        
        c.setFillColor(HexColor('#000000'))
        c.drawString(30, y - 15, f"【原标题】: {item['title']}")
        
        current_y = y - 30
        lines = item['result'].split('\n')
        for line in lines:
            if line.strip():
                c.drawString(30, current_y, line.strip())
                current_y -= 12
        y -= 100 # 间隔
        
    c.save()
    buffer.seek(0)
    return buffer

# ================= 4. 主界面逻辑 =================

# 检查登录状态
if check_auth():
    # --- 只有登录后才会执行以下代码 ---
    
    st.title("🏥 小红书账号 ICU 急救站 (专业版)")
    
    # 自动读取 API Key
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        st.error("⚠️ 系统未配置 API Key，请联系管理员")
        st.stop()

    uploaded_file = st.file_uploader("上传 Excel/CSV 数据表", type=['xlsx', 'csv'])

    if uploaded_file:
        try:
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            
            st.success(f"已加载 {len(df)} 条笔记数据")
            with st.expander("预览数据"):
                st.dataframe(df.head())
            
            col1, col2 = st.columns(2)
            with col1:
                title_col = st.selectbox("哪一列是【标题】?", df.columns)
            with col2:
                likes_col = st.selectbox("哪一列是【点赞】?", df.columns)
            
            if st.button("🚀 开始智能诊断"):
                # 配置 AI
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=SYSTEM_PROMPT)
                
                # 进度条
                progress_bar = st.progress(0)
                status_text = st.empty()
                results = []
                
                # 限制演示前5条 (正式版可去掉 .head(5) 跑全量)
                process_df = df.head(5)
                
                for idx, row in process_df.iterrows():
                    status_text.text(f"正在诊断: {row[title_col]}...")
                    res = analyze_note(model, row[title_col], row[likes_col], "未知")
                    results.append({"title": row[title_col], "result": res})
                    progress_bar.progress((idx + 1) / len(process_df))
                    time.sleep(1) # 防止API过载
                    
                status_text.success("诊断完成！")
                
                # 结果展示区
                col_res, col_chart = st.columns([1, 1])
                
                with col_chart:
                    st.subheader("📊 互动趋势")
                    fig, ax = plt.subplots(figsize=(6, 4))
                    sns.barplot(x=process_df[likes_col], y=process_df[title_col].str[:8], ax=ax, palette="viridis")
                    
                    # 尝试设置字体
                    font_path = get_chinese_font()
                    if os.path.exists(font_path):
                        import matplotlib.font_manager as fm
                        prop = fm.FontProperties(fname=font_path)
                        plt.yticks(fontproperties=prop)
                    
                    st.pyplot(fig)
                    # 保存图片供PDF使用
                    img_buffer = io.BytesIO()
                    plt.savefig(img_buffer, format='png', bbox_inches='tight', dpi=150)

                with col_res:
                    st.subheader("💊 诊断详情")
                    for item in results:
                        with st.chat_message("assistant"):
                            st.write(f"**{item['title']}**")
                            st.text(item['result'])
                            
                # PDF 下载
                pdf_bytes = create_pdf(df, results, img_buffer)
                st.download_button(
                    label="📥 下载深度报告 (PDF)",
                    data=pdf_bytes,
                    file_name="诊断报告.pdf",
                    mime="application/pdf"
                )
                
        except Exception as e:
            st.error(f"处理数据时出错: {e}")
            
else:
    # --- 未登录时的显示页面 ---
    st.markdown("# 👋 欢迎来到小红书账号急救站")
    st.info("👈 请在左侧输入今日 **卡密** 解锁使用。")
    st.markdown("---")
    st.markdown("#### 💡 如何获取卡密？")
    st.markdown("1. 填写问卷下单")
    st.markdown("2. 系统自动发货至您的邮箱")
