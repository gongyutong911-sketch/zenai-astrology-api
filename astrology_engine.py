import os
from openai import OpenAI

# 从环境变量中读取密钥和可选的自定义 Base URL（兼容标准 OpenAI 协议及中转网关）
api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL")  # 如果你有自定义的中转地址，会自动读取；没有则留空访问默认

# 初始化 OpenAI 客户端
client = OpenAI(
    api_key=api_key,
    base_url=base_url if base_url else None
)

def get_astrology_energy_guidance(birth_date: str, birth_time: str = "12:00", gender: str = "female", question: str = "今日能量指引"):
    """
    核心能量命理计算与 AI 指引生成函数（标准 OpenAI 协议适配版）
    """
    try:
        prompt = f"""
        你是一位专业的能量命理导师。请根据以下用户信息提供一份详细的能量指引报告：
        - 出生日期: {birth_date}
        - 出生时间: {birth_time}
        - 性别: {gender}
        - 咨询问题/主题: {question}
        
        请从今日能量场、运势走向以及实用建议三个方面进行深度解析，语言温暖、富有洞察力。
        """
        
        # 使用标准 Chat Completions 接口调用
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # 或者根据你当前中转服务所支持的模型名称调整（如 gpt-4o 等）
            messages=[
                {"role": "system", "content": "你是一位专业的能量命理导师。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        # 如果 API 调用失败，返回友好的降级提示或错误信息
        return f"【能量指引生成提示】生日: {birth_date} {birth_time}，问题: {question}. 当前 AI 模块返回异常: {str(e)}"