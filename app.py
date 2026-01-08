import streamlit as st
import pandas as pd
import time
import io
import os
import requests # 我们现在主要靠这个库
import json
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor
import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib.font_manager as fm

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

# ================= 2. 验证逻辑 =================

def get_valid_codes():
    """从 Secrets 中读取并清洗卡密列表"""
    if "VALID_CODES" not in st.secrets:
        st.error("⚠️ 配置错误：未找到 VALID_CODES，请检查 Secrets。")
        return []
    raw_str = st.secrets["VALID_CODES"]
    cleaned_str = raw_str.replace('\n', ',')
    code_list = [code.strip() for code in cleaned_str.split(',') if code.strip()]
    return code_list

def check_auth():
    """处理侧边栏登录逻辑"""
    st.sidebar.header("🔐 会员登录")
    if "is_logged_in" not in st.session_state:
        st.session_state.is_logged_in = False
    
    if st.session_state.is_logged_in:
        st.sidebar.success("✅ 已验证身份")
        if st.sidebar.button("退出登录"):
            st.session_state.is_logged_in = False
            st.rerun()
        return True

    user_input = st.sidebar.text_input("请输入卡密 / 激活码", type="password")
    btn = st.sidebar.button("验证")
    
    if btn:
        admin_pwd = st.secrets.get("ADMIN_PASSWORD", "admin888")
        valid_codes = get_valid_codes()
        clean_input = user_input.strip()
        
        if clean_input == admin_pwd:
            st.sidebar.success(f"👮 管理员认证成功 (生效卡密: {len(valid_codes)}个)")
        elif clean_input in valid_codes:
            st.session_state.is_logged_in = True
            st.sidebar.success("验证成功！")
            st.rerun()
        else:
            st.sidebar.error("❌ 无效的卡密")
    return False

# ================= 3. 辅助功能 =================

@st.cache_resource
def get_chinese_font():
    """下载中文字体防止乱码"""
    font_path = "SimHei.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/StellarCN/scp_zh/raw/master/fonts/SimHei.ttf"
        try:
            with st.spinner("正在初始化字体资源..."):
                r = requests.get(url)
                with open(font_path, "wb") as f:
                    f.write(r.content)
        except:
            st.warning("字体下载失败，图表可能显示方框。")
    return font_path

# 🔥🔥🔥 核心修改：使用 Requests 直接调用第三方 API 🔥🔥🔥
def analyze_note(api_key, title, likes, ctr):
    """
    不再使用 google.generativeai 库，
    而是直接向 api.gptsapi.net 发送 HTTP 请求。
    """
    # 你的第三方中转地址 (Gemini 1.5 Flash)
    url = f"https://api.gptsapi.net/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    # 构造请求头
    headers = {'Content-Type': 'application/json'}
    
    # 构造提示词内容
    user_prompt = f"笔记标题：{title}\n数据：点赞 {likes}, 点击率 {ctr}\n请诊断。"
    
    # 构造 JSON 数据包 (完全符合 Gemini 官方格式)
    payload = {
        "system_instruction": {
            "parts": {"text": SYSTEM_PROMPT}
        },
        "contents": [{
            "parts": [{"text": user_prompt}]
        }]
    }

    try:
        # 发送请求
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        # 解析结果
        if response.status_code == 200:
            result_json = response.json()
            # 提取文本内容
            try:
                text = result_json['candidates'][0]['content']['parts'][0]['text']
                return text
            except:
                return f"解析失败: {response.text}"
        else:
            return f"API请求失败 (Code {response.status_code}): {response.text}"
            
    except Exception as e:
        return f"连接错误: {str(e)}"

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
        y -= 100
        
    c.save()
    buffer.seek(0)
    return buffer

# ================= 4. 主程序入口 =================

if check_auth():
    st.title("🏥 小红书账号 ICU 急救站 (第三方API版)")
    
    # 读取 Key
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        st.error("⚠️ 未配置 GOOGLE_API_KEY")
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
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                results = []
                process_df = df.head(5) # 演示前5条
                
                for idx, row in process_df.iterrows():
                    status_text.text(f"正在诊断: {row[title_col]}...")
                    
                    # 🔥 调用修改后的分析函数，传入 api_key
                    res = analyze_note(api_key, row[title_col], row[likes_col], "未知")
                    
                    results.append({"title": row[title_col], "result": res})
                    progress_bar.progress((idx + 1) / len(process_df))
                    # 这里的sleep可以适当减少，因为第三方并发可能高一点，但保险起见留着
                    time.sleep(0.5) 
                    
                status_text.success("诊断完成！")
                
                col_res, col_chart = st.columns([1, 1])
                
                with col_chart:
                    st.subheader("📊 互动趋势")
                    
                    # 字体修复
                    font_path = get_chinese_font()
                    if os.path.exists(font_path):
                        fm.fontManager.addfont(font_path)
                        plt.rcParams['font.family'] = fm.FontProperties(fname=font_path).get_name()
                    plt.rcParams['axes.unicode_minus'] = False 

                    fig, ax = plt.subplots(figsize=(6, 4))
                    sns.barplot(x=process_df[likes_col], y=process_df[title_col].str[:8], ax=ax, palette="viridis")
                    st.pyplot(fig)
                    
                    img_buffer = io.BytesIO()
                    plt.savefig(img_buffer, format='png', bbox_inches='tight', dpi=150)

                with col_res:
                    st.subheader("💊 诊断详情")
                    for item in results:
                        with st.chat_message("assistant"):
                            st.write(f"**{item['title']}**")
                            st.text(item['result'])
                            
                pdf_bytes = create_pdf(df, results, img_buffer)
                st.download_button(
                    label="📥 下载深度报告 (PDF)",
                    data=pdf_bytes,
                    file_name="诊断报告.pdf",
                    mime="application/pdf"
                )
                
        except Exception as e:
            st.error(f"出错: {e}")
else:
    st.markdown("# 👋 欢迎来到小红书账号急救站")
    st.info("👈 请在左侧输入卡密解锁。")
