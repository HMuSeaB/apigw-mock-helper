# -*- coding: utf-8 -*-
"""
apigw-mock-helper - 通用爬虫工具与加密解密辅助模块
"""

import re
import ssl
import base64
import logging
import urllib.parse
from typing import Dict, Any
from curl_cffi import requests

# 基础日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# AES 密钥与向量配置 (与阅读客户端 Java.aesBase64Decode 完美匹配)
AES_KEY = b"Pxga!h*e4@T8xfOm"
AES_IV = b"E&z!EHGLd$fli*8R"

# 尝试引入 AES 加密套件
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    logger.warning("⚠️ 未检测到 pycryptodome 库，请使用 pip install pycryptodome 安装以激活加密分发！")


def get_secure_session() -> requests.Session:
    """
    获取一个基于 curl_cffi 的 Pro 级破盾 Session，完美模拟 Chrome 120 浏览器 TLS JA3 指纹。
    """
    session = requests.Session(impersonate="chrome120")
    session.headers.update({
        "Accept-Language": "zh-CN,zh;q=0.9,en-GB;q=0.8,en;q=0.7,en-US;q=0.6",
        "Cache-Control": "max-age=0",
        "Upgrade-Insecure-Requests": "1"
    })
    return session


def aes_encrypt_base64(text: str) -> str:
    """
    使用 AES-128-CBC PKCS7(PKCS5Padding) 算法对数据进行云端加密
    """
    if not text:
        return ""
    if not HAS_CRYPTO:
        # 若未安装 pycryptodome 依赖，友好降级为明文 Base64 以保证系统的强壮性
        return base64.b64encode(text.encode('utf-8')).decode('utf-8')
    try:
        raw_bytes = text.encode('utf-8')
        cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        padded_bytes = pad(raw_bytes, 16, style='pkcs7')
        encrypted_bytes = cipher.encrypt(padded_bytes)
        return base64.b64encode(encrypted_bytes).decode('utf-8')
    except Exception as e:
        logger.error(f"AES 加密发生异常: {str(e)}")
        return text


def clean_content_text(html_text: str) -> str:
    """
    智能正文提取与网页垃圾/广告牛皮癣智能净化排版算法
    """
    if not html_text:
        return ""
    # 1. 过滤 script, style, iframe 等无用交互标签
    html_text = re.sub(r'<script.*?>.*?</script>', '', html_text, flags=re.S | re.I)
    html_text = re.sub(r'<style.*?>.*?</style>', '', html_text, flags=re.S | re.I)
    html_text = re.sub(r'<iframe.*?>.*?</iframe>', '', html_text, flags=re.S | re.I)
    
    # 2. 将换行和段落标签转换为标准换行
    html_text = re.sub(r'<br\s*/?>', '\n', html_text, flags=re.I)
    html_text = re.sub(r'<p>', '\n', html_text, flags=re.I)
    html_text = re.sub(r'</p>', '', html_text, flags=re.I)
    
    # 3. 剥离剩余所有残余网页 HTML 标签
    html_text = re.sub(r'<.*?>', '', html_text, flags=re.S)
    
    # 4. 清理牛皮癣文字广告 (增强版正则，覆盖更多常见盗版垃圾内容)
    html_text = re.sub(r'(?i)一秒记住.*|请收藏本站.*|本章未完.*|记住网址.*|为您提供.*|最新最快更新.*|无广告.*', '', html_text)
    
    # 5. 排版美化：去除首尾空白字符，规范化空行，添加优美的段落缩进
    lines = html_text.split('\n')
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) > 2:  # 过滤掉极短的网页碎片噪音
            clean_lines.append(f"　　{stripped}")  # 加上两个全角空格的首行缩进
            
    return "\n\n".join(clean_lines)


def get_relative_time(time_str: str) -> str:
    """
    将绝对时间字符串 (如 2023-10-21 23:53:14) 动态转换为人性化相对时间差 (如 9个月前, 3天前)
    """
    from datetime import datetime
    time_str = str(time_str).strip()
    if not time_str:
        return "未知时间"
    
    # 如果本身就是相对时间描述（比如包含"前"、"刚刚"、"天"），直接原样返回
    if any(x in time_str for x in ["前", "刚刚", "小时", "天", "月", "年"]):
        return time_str
        
    # 定义常见的日期格式模板
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    ]
    
    dt = None
    for fmt in formats:
        try:
            dt = datetime.strptime(time_str, fmt)
            break
        except ValueError:
            continue
            
    if not dt:
        # 兜底：如果完全不是标准日期（如 "实时同步"），直接安全返回原样
        return time_str
        
    # 计算时间差
    now = datetime.now()
    diff = now - dt
    
    # 差值为负数（比如网页更新时间写成了未来的时间，或是本地时区误差），防错处理返回“刚刚”
    if diff.total_seconds() < 0:
        return "刚刚"
        
    days = diff.days
    if days >= 365:
        return f"{days // 365}年前"
    elif days >= 30:
        return f"{days // 30}个月前"
    elif days >= 1:
        return f"{days}天前"
        
    seconds = diff.seconds
    if seconds >= 3600:
        return f"{seconds // 3600}小时前"
    elif seconds >= 60:
        return f"{seconds // 60}分钟前"
    
    return "刚刚"

