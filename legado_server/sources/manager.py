# -*- coding: utf-8 -*-
"""
apigw-mock-helper - 多源调度管理器 (sources.manager)
"""

import logging
import re
from typing import Dict, Any, List
from sources import bqg78, shuba69, ibiquges, xbiquge
from sources.utils import get_secure_session, clean_content_text

logger = logging.getLogger(__name__)

# 注册源前缀映射关系
SOURCES_MAP = {
    "bqg78_": bqg78,
    "69_": shuba69,
    "xs_": ibiquges,
    "bq_": xbiquge
}


def search_books(keyword: str) -> List[Dict[str, Any]]:
    """
    全网实时并发去重搜索 API
    """
    keyword = keyword.strip()
    if not keyword:
        return []

    # 1. 实时爬取两大有搜索功能的站
    books_bqg78 = bqg78.crawl_search(keyword)
    books_69 = shuba69.crawl_search(keyword)

    # 2. 合并搜索结果
    merged_books = books_69 + books_bqg78

    # 3. 去重过滤 (根据书籍名称和作者进行简单合并去重)
    seen = set()
    unique_books = []
    for book in merged_books:
        # 去除名字中的空格进行唯一判定
        key = (book["book_name"].replace(" ", ""), book["book_author"].replace(" ", ""))
        if key not in seen:
            seen.add(key)
            unique_books.append(book)

    return unique_books


def get_book_info(book_id: str) -> Dict[str, Any]:
    """
    书籍详情 API：识别书籍前缀并指派对应的子源进行实时爬取
    """
    book_id = str(book_id).strip()
    
    # 查找匹配的子源
    for prefix, module in SOURCES_MAP.items():
        if book_id.startswith(prefix):
            try:
                return module.crawl_info(book_id)
            except Exception as e:
                logger.error(f"❌ 调度 {prefix} 详情解析异常: {str(e)}")
                break

    # 默认值保护
    return {
        "book_id": book_id,
        "book_name": "未知书籍",
        "book_author": "自建聚合",
        "book_pic": "https://api.mwm.moe/ycy",
        "book_intro": "暂无简介，该书籍来源前缀暂不支持详情抓取。",
        "latest_ch": "点击开始阅读"
    }


def get_chapters(book_id: str) -> List[Dict[str, Any]]:
    """
    获取书籍的实时目录并对其下发 AES-128-CBC 加密包
    """
    book_id = str(book_id).strip()

    # 查找匹配的子源
    for prefix, module in SOURCES_MAP.items():
        if book_id.startswith(prefix):
            try:
                return module.crawl_toc(book_id)
            except Exception as e:
                logger.error(f"❌ 调度 {prefix} 目录解析异常: {str(e)}")
                break

    return []


def get_content(url: str) -> str:
    """
    四、核心正文实时抓取、广告智能净化清洗
    """
    url = url.strip()
    if not url:
        return "未指定正文链接参数"

    # A. 针对 69书吧的正文并净化
    if "69shuba" in url:
        try:
            return shuba69.crawl_content(url)
        except Exception as e:
            logger.error(f"调度 69书吧 正文抓取失败: {str(e)}")

    # B. 针对香书小说的正文并净化
    elif "ibiquges.org" in url:
        try:
            return ibiquges.crawl_content(url)
        except Exception as e:
            logger.error(f"调度香书小说正文抓取失败: {str(e)}")

    # C. 针对新笔趣阁的正文并净化
    elif "xbiquge.la" in url:
        try:
            return xbiquge.crawl_content(url)
        except Exception as e:
            logger.error(f"调度新笔趣阁正文抓取失败: {str(e)}")

    # D. 针对笔趣阁阁的正文并净化
    elif "bqg78.com" in url or "bqg78" in url:
        try:
            return bqg78.crawl_content(url)
        except Exception as e:
            logger.error(f"调度笔趣阁阁正文抓取失败: {str(e)}")

    # E. 万能保底直连引擎 (Robustness - 健壮性防线)
    # 若未来引入其他来源的 URL，可自动以 Chrome120 TLS 指纹直连获取，并通用解析 #content 区块
    try:
        logger.info(f"🕸️ [manager] 正在使用保底直连引擎抓取未知源正文: {url}")
        session = get_secure_session()
        response = session.get(url, timeout=8)
        if response.status_code == 200:
            # 自动解码 (支持 utf-8 和 gbk 混合自动识别)
            content_type = response.headers.get("Content-Type", "").lower()
            if "gb2312" in content_type or "gbk" in content_type:
                response.encoding = 'gbk'
            else:
                response.encoding = 'utf-8'
            
            html = response.text
            # 匹配最经典的 #content 或 id="content" 区块
            content_block = re.search(r'<div\s+id\s*=\s*"content">(.*?)</div>', html, re.S)
            if not content_block:
                content_block = re.search(r'<div\s+class\s*=\s*"content">(.*?)</div>', html, re.S)
            
            if content_block:
                return clean_content_text(content_block.group(1))
    except Exception as e:
        logger.error(f"❌ [manager] 保底直连引擎抓取异常: {str(e)}")

    return "抓取章节正文内容失败，请稍后刷新重试"
