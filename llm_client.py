import os
from pathlib import Path
from openai import OpenAI
from openai import APIConnectionError, RateLimitError, APIStatusError
import json
import time 
from datetime import datetime
import httpx
import socket
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

# --- 默认配置（可由本地 .env 或环境变量覆盖） ---
DEFAULT_API_KEY = os.getenv("LLM_API_KEY", "").strip()
DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip() or "https://api.deepseek.com"
DEFAULT_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash"
DEFAULT_TEMPERATURE = 0
DEFAULT_MAX_TOKENS = 5000
DEFAULT_PROXY_URL = os.getenv("LLM_PROXY_URL", "").strip() or None


@dataclass(frozen=True)
class LLMQueryResult:
    content: str = ""
    finish_reason: str = ""
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    error_message: str = ""


class LLMClient:
    def __init__(self, api_key=None, base_url=None, model=None, proxy_url=None, verify_ssl=True):
        self._log_info("[初始化] LLMClient 开始创建")

        self.api_key = (api_key if api_key is not None else os.getenv("LLM_API_KEY", DEFAULT_API_KEY) or "").strip()
        self.base_url = (base_url if base_url is not None else os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).strip()
        self.model = (model if model is not None else os.getenv("LLM_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL).strip()
        self.proxy_url = proxy_url if proxy_url is not None else (os.getenv("LLM_PROXY_URL", DEFAULT_PROXY_URL or "").strip() or None)
        self.client = None

        if not self.api_key:
            self._log_info("[初始化] 未配置 LLM_API_KEY；将在调用时返回配置错误")
            return

        # 配置 HTTP 客户端
        http_client = None

        # 创建 HTTP 客户端配置
        http_client_kwargs = {
            "timeout": 300,
        }

        # 配置代理（如果提供了代理URL）
        if self.proxy_url:
            # httpx 0.28.1 使用 'proxy' 参数（单数）
            http_client_kwargs["proxy"] = self.proxy_url
            print("[配置] 代理已配置")
            self._log_info("[配置] 代理已配置")

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
            api_key=self.api_key,
            base_url=self.base_url,
            http_client=http_client,
            timeout=300
        )

        self._log_info(f"[初始化] LLMClient 创建完成，模型: {self.model}，Base URL: {self.base_url}")

    def query_result(self, user_prompt: str, system_prompt: str = None,
                     save_path: str = None,
                     temperature: float = DEFAULT_TEMPERATURE,
                     max_tokens: int = DEFAULT_MAX_TOKENS,
                     reasoning_effort="high",
                     extra_body=None,
                     extra_log_info: str = None) -> LLMQueryResult:
        """
        通用的 LLM 调用函数

        :param system_prompt: 系统提示词
        :param user_prompt: 用户提示词
        :param save_path: (可选) 如果提供路径，将结果保存到该文件
        :param temperature: 温度参数
        :param max_tokens: 最大 token 数
        :param extra_log_info: (可选) 用户需要记录的额外日志信息
        :return: 模型返回的正文、结束原因、token 用量及错误信息
        """
        start_time = time.time()
        error_msg = None

        if hasattr(self, "api_key") and not self.api_key:
            error_msg = "LLM_API_KEY is not configured"
            self._log_info(f"[错误] {error_msg}")
            return LLMQueryResult(error_message=error_msg)

        if extra_body is None:
            extra_body = {"thinking": {"type": "enabled"}}

        # Doubao's compatible endpoint does not accept reasoning_effort.
        if "doubao" in self.model.lower():
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

            choice = response.choices[0]
            content = choice.message.content or ""
            finish_reason = getattr(choice, "finish_reason", "") or ""
            # 记录 token 用量
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
            total_tokens = getattr(usage, "total_tokens", None) if usage else None
            usage_info = (
                f"，finish_reason={finish_reason or 'unknown'}"
                f"，prompt_tokens={prompt_tokens}，completion_tokens={completion_tokens}"
                f"，total_tokens={total_tokens}，visible_chars={len(content)}"
            )

            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000

            print(f"[成功] 模型调用成功，耗时 {duration_ms:.2f} ms")
            self._log_info(f"[成功] 模型调用成功，耗时 {duration_ms:.2f} ms{usage_info}")
            # 如果指定了保存路径，则写入非空内容
            if save_path and content:
                self._save_to_file(content, save_path)

            return LLMQueryResult(
                content=content,
                finish_reason=finish_reason,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

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

        return LLMQueryResult(error_message=error_msg or "未知错误")

    def query(self, user_prompt: str, system_prompt: str = None,
              save_path: str = None,
              temperature: float = DEFAULT_TEMPERATURE,
              max_tokens: int = DEFAULT_MAX_TOKENS,
              reasoning_effort="high",
              extra_body=None,
              extra_log_info: str = None) -> Optional[str]:
        """兼容既有调用：仅在模型返回非空正文时返回字符串。"""
        result = self.query_result(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            save_path=save_path,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            extra_body=extra_body,
            extra_log_info=extra_log_info,
        )
        return result.content or None

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

# 默认客户端在缺少本地密钥时保持可导入；首次调用会返回明确配置错误。
llm = LLMClient()
