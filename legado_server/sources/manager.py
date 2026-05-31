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
    全网实时多线程并发搜索 API (去重合并版，相同书名作者只保留最优质的唯一记录)
    """
    keyword = keyword.strip()
    if not keyword:
        return []

    import concurrent.futures

    # 1. 实时多线程并发检索 4 大独立小说书库站
    funcs = [
        ("bqg78", bqg78.crawl_search),
        ("69shuba", shuba69.crawl_search),
        ("ibiquges", ibiquges.crawl_search),
        ("xbiquge", xbiquge.crawl_search),
    ]

    merged_books = []
    # 使用 ThreadPoolExecutor 并发调度
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        # 提交所有的搜索任务
        future_to_source = {executor.submit(func, keyword): name for name, func in funcs}
        
        # 收集执行结果 (带超时控制，防止某一个源超时拖慢全局)
        try:
            for future in concurrent.futures.as_completed(future_to_source, timeout=8.0):
                source_name = future_to_source[future]
                try:
                    result = future.result()
                    if result:
                        merged_books.extend(result)
                except Exception as exc:
                    logger.error(f"❌ [manager] 源 {source_name} 并发搜索抛出异常: {exc}")
        except concurrent.futures.TimeoutError:
            logger.warning("⚠️ [manager] 部分并发搜索任务超时（已自动截断，保留已返回源的数据）")

    # 3. 智能去重合并：差不多名字和作者相同即可算为同一本书，只保留第一条最优质的检索记录
    seen = set()
    unique_books = []
    for book in merged_books:
        # 统一擦除空格与大小写以进行最精确 of 去重
        name_key = book.get("book_name", "").replace(" ", "").lower()
        author_key = book.get("book_author", "").replace(" ", "").lower()
        key = (name_key, author_key)
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

    # 物理擦除由于欺骗客户端脆弱正则而强行塞入的虚构 `/book/` 前缀，还原为原站真实的物理路径
    if "ddyueshu.com" in url and "/book/" in url:
        url = url.replace("/book/", "/")
        logger.info(f"🛡️ [manager] 已自愈还原顶点改版物理链接: {url}")

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
