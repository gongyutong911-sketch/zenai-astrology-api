import os
import google.generativeai as genai

# 配置 Gemini API 密钥
GEMINI_API_KEY = os.getenv("OPENAI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def get_astrology_energy_guidance(birth_date: str, birth_time: str = "12:00", gender: str = "female", question: str = "今日能量指引"):
    """
    核心能量命理计算与 Gemini AI 指引生成函数
    """
    try:
        # 使用配置好的 Gemini 模型生成能量指引
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = f"""
        你是一位专业的能量命理导师。请根据以下用户信息提供一份详细的能量指引报告：
        - 出生日期: {birth_date}
        - 出生时间: {birth_time}
        - 性别: {gender}
        - 咨询问题/主题: {question}
        
        请从今日能量场、运势走向以及实用建议三个方面进行深度解析，语言温暖、富有洞察力。
        """
        
        response = model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        # 如果 API 调用失败，返回友好的降级提示或错误信息
        return f"【能量指引生成提示】生日: {birth_date} {birth_time}，问题: {question。当前 AI 模块返回异常: {str(e)}"