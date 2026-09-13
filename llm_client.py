import os
from openai import OpenAI
from openai import APIConnectionError, RateLimitError, APIStatusError
import json
import time 
from datetime import datetime
import httpx
import socket

# --- 配置区域 (修改这里即可全局生效) ---
DEFAULT_API_KEY = "sk-6874e578bf2f49e38f8dbbccc333f87d"  # 建议使用 os.getenv("DEEPSEEK_API_KEY") 获取
DEFAULT_BASE_URL = "https://api.deepseek.com"
# DEFAULT_API_KEY = "sk-b54b7d16afcf46499c2dac95b7a04d00"
# DEFAULT_BASE_URL = "https://e.cnpc.com.cn/klzm-ai-proxy"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_TEMPERATURE = 0
DEFAULT_MAX_TOKENS = 5000

# DEFAULT_PROXY_URL = 'http://10.22.98.21:8080'
DEFAULT_PROXY_URL = None

# --- 豆包模型配置 ---
DOUBAO_API_KEY = "3966fdf0-8f7d-4e83-8366-eea4a41db3a7"
DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DOUBAO_MODEL = "doubao-seed-2-0-pro-260215"



class LLMClient:
    def __init__(self, api_key=None, base_url=None, model=None, proxy_url=None, verify_ssl=True):
        self._log_info("[初始化] LLMClient 开始创建")

        # 配置 HTTP 客户端
        http_client = None

        # 创建 HTTP 客户端配置
        http_client_kwargs = {
            "timeout": 300,
        }

        # 配置代理（如果提供了代理URL）
        if proxy_url:
            # httpx 0.28.1 使用 'proxy' 参数（单数）
            http_client_kwargs["proxy"] = proxy_url
            print(f"[配置] 使用代理: {proxy_url}")
            self._log_info(f"[配置] 使用代理: {proxy_url}")

        # 配置 SSL 验证
        if not verify_ssl:
            http_client_kwargs["verify"] = False
            print("[配置] SSL 验证已禁用")
            self._log_info("[配置] SSL 验证已禁用")
        else:
            http_client_kwargs["verify"] = True

        # 创建 HTTP 客户端
        http_client = httpx.Client(**http_client_kwargs)

        self.client = OpenAI(
            api_key=api_key or DEFAULT_API_KEY,
            base_url=base_url or DEFAULT_BASE_URL,
            http_client=http_client,
            timeout=300
        )
        self.model = model or DEFAULT_MODEL
        self.proxy_url = proxy_url

        self._log_info(f"[初始化] LLMClient 创建完成，模型: {self.model}，Base URL: {base_url or DEFAULT_BASE_URL}")

    def query(self, user_prompt: str, system_prompt: str = None,
              save_path: str = None,
              temperature: float = DEFAULT_TEMPERATURE,
              max_tokens: int = DEFAULT_MAX_TOKENS,
              reasoning_effort="high",
              extra_body={"thinking": {"type": "enabled"}},
              extra_log_info: str = None) -> str:
        """
        通用的 LLM 调用函数

        :param system_prompt: 系统提示词
        :param user_prompt: 用户提示词
        :param save_path: (可选) 如果提供路径，将结果保存到该文件
        :param temperature: 温度参数
        :param max_tokens: 最大 token 数
        :param extra_log_info: (可选) 用户需要记录的额外日志信息
        :return: 模型返回的文本内容 (如果出错返回 None)
        """
        start_time = time.time()
        error_msg = None

        # 豆包模型不支持 reasoning_effort 参数，但支持深度思考（thinking: enabled）
        is_doubao = "doubao" in self.model.lower()
        if is_doubao:
            reasoning_effort = None
            extra_body = {"thinking": {"type": "enabled"}}

        try:
            print(f"[启动] 正在调用模型: {self.model} ...")
            self._log_info(f"[启动] 正在调用模型: {self.model}，temperature={temperature}，max_tokens={max_tokens}，extra_log={extra_log_info or '无'}")
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
                # 添加用户提示词
            messages.append({"role": "user", "content": user_prompt})

            # 构建请求参数（豆包不传 reasoning_effort）
            create_kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "extra_body": extra_body
            }
            if reasoning_effort is not None:
                create_kwargs["reasoning_effort"] = reasoning_effort

            response = self.client.chat.completions.create(**create_kwargs)

            content = response.choices[0].message.content
            # 记录 token 用量
            usage = getattr(response, "usage", None)
            usage_info = ""
            if usage:
                usage_info = f"，prompt_tokens={usage.prompt_tokens}，completion_tokens={usage.completion_tokens}，total_tokens={usage.total_tokens}"

            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000

            print(f"[成功] 模型调用成功，耗时 {duration_ms:.2f} ms")
            self._log_info(f"[成功] 模型调用成功，耗时 {duration_ms:.2f} ms{usage_info}")
            # 如果指定了保存路径，则写入文件
            if save_path:
                self._save_to_file(content, save_path)

            return content

        except APIConnectionError as e:
            error_msg = f"连接服务器失败: {str(e)}"
            print(f"[错误] {error_msg}")
            self._log_info(f"[错误] {error_msg}")
        except RateLimitError:
            error_msg = "请求过于频繁 (Rate Limit)"
            print("[错误] 请求过于频繁 (Rate Limit)，请稍后再试。")
            self._log_info(f"[错误] {error_msg}")
        except APIStatusError as e:
            error_msg = f"API 状态错误: {e.status_code} - {e.response}"
            print(f"[错误] API 状态错误: {e.status_code} - {e.response}")
            self._log_info(f"[错误] {error_msg}")
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            print(f"[错误] 未知错误: {str(e)}")
            self._log_info(f"[错误] 未知错误: {str(e)}")
        finally:
            # 总是记录日志
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000
            self._log_info(f"[结束] 模型: {self.model}，耗时: {duration_ms:.2f} ms，结果: {'失败' if error_msg else '成功'}，额外信息: {extra_log_info or '无'}")

        return None

    def _save_to_file(self, content: str, filepath: str):
        """内部辅助函数：保存文件"""
        try:
            # 自动创建父目录（如果不存在）
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[成功] 内容已保存至: {os.path.abspath(filepath)}")
            self._log_info(f"[成功] 内容已保存至: {os.path.abspath(filepath)}")
        except IOError as e:
            print(f"[错误] 文件写入失败: {e}")
            self._log_info(f"[错误] 文件写入失败: {e}")
            
    def _log_info(self, info=None):
        """
        记录日志（纯文本格式），同时输出到控制台和日志文件
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        log_message = f"{timestamp}"

        # 添加额外信息（如果有）
        if info:
            log_message += f" | {info}"

        # 输出到控制台
        print(log_message)

        # 同时写入日志文件
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        log_file = os.path.join(log_dir, "llm.log")

        try:
            # 确保日志目录存在
            os.makedirs(log_dir, exist_ok=True)

            # 写入日志文件
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(log_message + "\n")
        except Exception as e:
            print(f"[警告] 无法写入日志文件: {e}")

# --- 单例模式 (可选) ---
# 实例化一个默认客户端，方便外部直接导入使用
# from llm_client import llm
llm = LLMClient(verify_ssl=False, proxy_url=DEFAULT_PROXY_URL)

# 豆包模型客户端单例
# from llm_client import doubao_llm
# llm = LLMClient(
#     api_key=DOUBAO_API_KEY,
#     base_url=DOUBAO_BASE_URL,
#     model=DOUBAO_MODEL,
#     verify_ssl=False,
#     proxy_url=DEFAULT_PROXY_URL
# )
