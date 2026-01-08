import streamlit as st
import pandas as pd
import time
import io
import os
import requests
import json
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor

# ================= 1. 基础配置 =================
st.set_page_config(
    page_title="小红书全能运营台", # 改个名字显得更厉害
    page_icon="🔥",
    layout="centered"
)

# --- 提示词仓库 ---

# 1. 诊断用的提示词 (旧)
DIAGNOSIS_PROMPT = """
# Role: 小红书爆款诊断专家
你是一名拥有百万粉丝操盘经验的小红书运营专家。你说话风格犀利、毒舌、拒绝废话，只看数据和人性。
你的任务是根据用户提供的笔记标题和数据，进行“无情”的诊断，并给出改进方案。

请针对每一条笔记，输出严格的如下格式（不要Markdown，只要纯文本）：
【评分】: <0-100的数字>
【毒舌诊断】: <一句话指出问题，如太学术、无聊、自嗨>
【改写方案A】: <痛点型标题>
【改写方案B】: <利益型标题>
"""

# 2. 生成用的提示词 (新)
GENERATION_PROMPT = """
# Role: 小红书爆款文案官
你精通小红书的点击率算法和用户心理。你的任务是根据用户提供的【视频脚本/文案】，提炼出最具吸引力的元数据。

请输出以下两部分内容：
1. **3个爆款标题**：
   - 必须运用“情绪价值”、“反差感”、“悬念”或“具体数字”技巧。
   - 标题要短小精悍，像钩子一样勾住用户。
   - 风格参考：口语化、感叹号、表情包。

2. **50字简介 (Caption)**：
   - 适合放在视频下方的说明栏。
   - 包含SEO关键词。
   - 结尾必须引导互动（例如：“评论区告诉我...”、“记得点赞收藏...”）。

输出格式要求：
【💥 爆款标题预测】
1. ...
2. ...
3. ...

【📝 50字黄金简介】
...
"""

# ================= 2. 验证逻辑 =================

def get_valid_codes():
    if "VALID_CODES" not in st.secrets:
        st.error("⚠️ 系统配置错误：未找到卡密列表 (VALID_CODES)。")
        return []
    raw_str = st.secrets["VALID_CODES"]
    cleaned_str = raw_str.replace('\n', ',')
    code_list = [code.strip() for code in cleaned_str.split(',') if code.strip()]
    return code_list

def check_auth():
    st.sidebar.header("🔐 会员登录")
    if "is_logged_in" not in st.session_state:
        st.session_state.is_logged_in = False
    
    if st.session_state.is_logged_in:
        st.sidebar.success("✅ 已验证身份")
        if st.sidebar.button("退出登录"):
            st.session_state.is_logged_in = False
            st.rerun()
        return True

    user_input = st.sidebar.text_input("请输入卡密 / 激活码", type="password", help="请填写您购买的卡密")
    btn = st.sidebar.button("验证")
    
    if btn:
        admin_pwd = st.secrets.get("ADMIN_PASSWORD", "admin888")
        valid_codes = get_valid_codes()
        clean_input = user_input.strip()
        
        if clean_input == admin_pwd:
            st.sidebar.success("👮 管理员认证成功")
            st.sidebar.info(f"当前生效卡密: {len(valid_codes)} 个")
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
    font_path = "SimHei.ttf"
    if not os.path.exists(font_path):
        url = "https://github.com/StellarCN/scp_zh/raw/master/fonts/SimHei.ttf"
        try:
            with st.spinner("正在初始化字体资源..."):
                r = requests.get(url)
                with open(font_path, "wb") as f:
                    f.write(r.content)
        except:
            st.warning("字体下载失败，PDF可能显示异常。")
    return font_path

# 通用 API 调用函数 (Gemini 3 Flash Preview)
def call_gemini_api(api_key, user_content, system_prompt):
    url = "https://api.gptsapi.net/v1beta/models/gemini-3-flash-preview:generateContent"
    headers = {
        'x-goog-api-key': api_key, 
        'Content-Type': 'application/json'
    }
    
    # 组合 Prompt
    full_payload_text = f"{system_prompt}\n\n---\n用户输入内容：\n{user_content}"
    
    payload = {
        "contents": [{"role": "user", "parts": [{"text": full_payload_text}]}]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 200:
            result_json = response.json()
            try:
                text = result_json['candidates'][0]['content']['parts'][0]['text']
                return text
            except:
                return f"解析失败: {response.text}"
        elif response.status_code == 404:
            return f"❌ 404 错误: 模型路径不对。"
        elif response.status_code == 400:
            return f"❌ 400 错误: 数据格式不对。"
        else:
            return f"API请求失败 ({response.status_code}): {response.text}"
    except Exception as e:
        return f"连接错误: {str(e)}"

# PDF 生成函数 (仅用于诊断报告)
def create_pdf(df, analysis_results):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    font_path = get_chinese_font()
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('SimHei', font_path))
        font_name = 'SimHei'
    else:
        font_name = 'Helvetica'
    
    c.setFillColor(HexColor('#FF2442'))
    c.rect(0, height - 120, width, 120, fill=1, stroke=0)
    
    c.setFillColor(HexColor('#FFFFFF'))
    c.setFont(font_name, 26)
    c.drawString(40, height - 70, "小红书账号深度诊断报告")
    c.setFont(font_name, 14)
    c.drawString(40, height - 100, "AI Smart Diagnosis Report")
    
    c.setFillColor(HexColor('#000000'))
    c.setFont(font_name, 18)
    y = height - 160 
    c.drawString(40, y, "一、AI 毒舌急救方案")
    y -= 30
    c.setFont(font_name, 10)
    
    for item in analysis_results:
        if y < 100:
            c.showPage()
            c.setFont(font_name, 10)
            y = height - 50
            
        c.setFillColor(HexColor('#F8F8F8'))
        c.rect(30, y - 70, width - 60, 80, fill=1, stroke=0)
        
        c.setFillColor(HexColor('#333333'))
        c.setFont(font_name, 11)
        c.drawString(40, y - 15, f"【原标题】: {item['title']}")
        
        c.setFont(font_name, 10)
        current_y = y - 35
        lines = item['result'].split('\n')
        for line in lines:
            if line.strip():
                c.drawString(40, current_y, line.strip())
                current_y -= 14
        y -= 110
        
    c.save()
    buffer.seek(0)
    return buffer

# ================= 4. 主程序入口 =================

if check_auth():
    st.title("🔥 小红书全能运营台")
    st.caption("Gemini 3 Flash Preview 驱动 | 爆款辅助系统")
    
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
    else:
        st.error("⚠️ 未配置 GOOGLE_API_KEY")
        st.stop()

    # === 创建标签页 ===
    tab1, tab2 = st.tabs(["🏥 账号ICU诊断", "✨ 爆款文案生成"])

    # ------------------ 功能 1：账号诊断 (Excel) ------------------
    with tab1:
        st.markdown("#### 📉 以前发的笔记数据不好？让 AI 帮你找原因")
        uploaded_file = st.file_uploader("上传 Excel/CSV 数据表", type=['xlsx', 'csv'], key="uploader_tab1")

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
                
                if st.button("🚀 开始智能诊断", key="btn_diagnose"):
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    results = []
                    process_df = df.head(5) 
                    
                    result_container = st.container()

                    for idx, row in process_df.iterrows():
                        status_text.text(f"正在诊断: {row[title_col]}...")
                        # 构造诊断内容
                        user_content = f"笔记标题：{row[title_col]}\n数据：点赞 {row[likes_col]}"
                        # 调用 API
                        res = call_gemini_api(api_key, user_content, DIAGNOSIS_PROMPT)
                        results.append({"title": row[title_col], "result": res})
                        
                        with result_container:
                            with st.chat_message("assistant"):
                                st.write(f"**{row[title_col]}**")
                                st.text(res)

                        progress_bar.progress((idx + 1) / len(process_df))
                        time.sleep(0.5) 
                        
                    status_text.success("诊断完成！")
                    pdf_bytes = create_pdf(df, results)
                    st.download_button(
                        label="📥 下载诊断报告 (PDF)",
                        data=pdf_bytes,
                        file_name="小红书账号诊断报告.pdf",
                        mime="application/pdf",
                        type="primary"
                    )
            except Exception as e:
                st.error(f"出错: {e}")

    # ------------------ 功能 2：文案生成 (Text Area) ------------------
    with tab2:
        st.markdown("#### 📝 有了视频脚本，不知道怎么起标题？")
        
        script_input = st.text_area(
            "在此粘贴你的视频脚本或粗糙的文案：", 
            height=200,
            placeholder="例如：今天去吃了一家很隐蔽的火锅店，味道..."
        )
        
        if st.button("✨ 生成爆款标题 + 简介", key="btn_generate"):
            if not script_input.strip():
                st.warning("⚠️ 请先输入一点内容再点击生成哦！")
            else:
                with st.spinner("AI 正在疯狂头脑风暴中..."):
                    # 直接调用通用 API 函数，传入生成专用的 Prompt
                    generated_content = call_gemini_api(api_key, script_input, GENERATION_PROMPT)
                    
                    st.success("生成成功！")
                    st.markdown("---")
                    
                    # 使用卡片展示结果，更美观
                    st.markdown(generated_content)
                    
                    st.markdown("---")
                    st.caption("💡 提示：你可以直接复制上面的内容到小红书发布页面。")

else:
    st.markdown("# 👋 欢迎来到小红书全能运营台")
    st.info("👈 请在左侧输入卡密解锁。")
