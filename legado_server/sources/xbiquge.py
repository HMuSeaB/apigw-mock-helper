# -*- coding: utf-8 -*-
"""
apigw-mock-helper - 新笔趣阁 (xbiquge.la) 爬虫解析模块
"""

import re
import logging
from typing import Dict, Any, List
from sources.utils import get_secure_session, clean_content_text, aes_encrypt_base64

logger = logging.getLogger(__name__)

def crawl_search(keyword: str) -> List[Dict[str, Any]]:
    """
    实时去新笔趣阁（xbiquge.la）独立书库搜索书籍
    """
    keyword = keyword.strip()
    if not keyword:
        return []
        
    session = get_secure_session()
    search_url = "https://www.xbiquge.la/modules/article/search.php"
    try:
        encoded_keyword = keyword.encode('gbk')
    except Exception:
        encoded_keyword = keyword
        
    params = {"searchkey": encoded_keyword}
    
    books = []
    try:
        logger.info(f"🕸️ [xbiquge] 正在独立书库中检索: '{keyword}'")
        response = session.post(search_url, data=params, timeout=8, verify=False)
        response.encoding = 'gbk'
        html = response.text
        
        final_url = str(response.url)
        if "/modules/article/search.php" not in final_url:
            match = re.search(r'https?://[^/]+/(\d+)/(\d+)/?$', final_url)
            if match:
                raw_id = f"{match.group(1)}_{match.group(2)}"
                detail = crawl_info(f"bq_{raw_id}")
                detail["categoryName"] = "新笔趣阁"
                books.append(detail)
                return books
                
        tr_tags = re.findall(r'<tr[^>]*>.*?<td class="odd"><a href="[^"]*/(\d+)/(\d+)/?">(.*?)</a></td>.*?<td class="even">(.*?)</td>', html, re.S)
        for pref, num_id, name, author in tr_tags:
            book_id = f"bq_{pref}_{num_id}"
            books.append({
                "book_id": book_id,
                "book_name": name.strip(),
                "book_author": author.strip(),
                "book_pic": "https://api.mwm.moe/ycy",
                "book_intro": "📂 新笔趣阁源站实时检索书籍。",
                "book_lastchapter": "点击换源阅读",
                "categoryName": "新笔趣阁"
            })
    except Exception as e:
        logger.error(f"❌ [xbiquge] 独立书库检索异常: {str(e)}")
        
    return books


def crawl_info(book_id: str) -> Dict[str, Any]:
    """
    实时去新笔趣阁抓取书籍详情
    """
    raw_id = book_id.replace("bq_", "")
    path_part = raw_id.replace("_", "/")
    book_url = f"https://www.xbiquge.la/{path_part}/"
    session = get_secure_session()
    
    # 默认值
    detail = {
        "book_id": book_id,
        "book_name": "未知书籍",
        "book_author": "未知作者",
        "book_pic": "https://api.mwm.moe/ycy",
        "book_intro": "暂无简介",
        "latest_ch": "点击开始阅读"
    }
    
    try:
        logger.info(f"🕸️ [xbiquge] 正在实时抓取详情: {book_url}")
        response = session.get(book_url, timeout=8, verify=False)
        response.encoding = 'gbk'
        html = response.text
        
        name_match = re.search(r'<div id="info">.*?<h1>(.*?)</h1>', html, re.S)
        author_match = re.search(r'<div id="info">.*?作\s*者：(.*?)<', html, re.S)
        if not author_match:
            author_match = re.search(r'<div id="info">.*?<p>作\s*者：(.*?)</p>', html, re.S)
            
        cover_match = re.search(r'<div id="fmimg">.*?<img.*?src="(.*?)"', html, re.S)
        intro_match = re.search(r'<div id="intro">(.*?)</div>', html, re.S)
        latest_match = re.search(r'最新章节：.*?<a[^>]*>(.*?)</a>', html, re.S)
        if not latest_match:
            latest_match = re.search(r'property="og:novel:latest_chapter_name"\s+content="(.*?)"', html)
        
        if name_match:
            detail["book_name"] = name_match.group(1).strip()
        if author_match:
            detail["book_author"] = re.sub(r'<.*?>', '', author_match.group(1)).strip()
        if cover_match:
            cover_url = cover_match.group(1).strip()
            if not cover_url.startswith("http"):
                cover_url = f"https://www.xbiquge.la{cover_url}"
            detail["book_pic"] = cover_url
        if intro_match:
            detail["book_intro"] = clean_content_text(intro_match.group(1))
        if latest_match:
            detail["latest_ch"] = latest_match.group(1).strip()
    except Exception as e:
        logger.error(f"❌ [xbiquge] 抓取新笔趣阁详情异常: {str(e)}")
        
    return detail


def crawl_toc(book_id: str) -> List[Dict[str, Any]]:
    """
    解析新笔趣阁目录结构
    """
    chapters = []
    raw_id = book_id.replace("bq_", "")
    path_part = raw_id.replace("_", "/")
    book_url = f"https://www.xbiquge.la/{path_part}/"
    session = get_secure_session()
    
    try:
        logger.info(f"🕸️ [xbiquge] 正在抓取目录: {book_url}")
        response = session.get(book_url, timeout=8, verify=False)
        response.encoding = 'gbk'
        html = response.text
        
        catalog_block = re.search(r'<div id="list">.*?<dl>(.*?)</dl>', html, re.S)
        if catalog_block:
            dd_tags = re.findall(r'<dd><a href="(.*?)">(.*?)</a></dd>', catalog_block.group(1), re.S)
            for href, name in dd_tags:
                clean_name = name.strip()
                encrypted_name = aes_encrypt_base64(clean_name)
                # 拼接新笔趣阁的章节完整 URL
                full_href = href
                if not href.startswith("http"):
                    full_href = f"https://www.xbiquge.la{href}"
                chapters.append({
                    "name": encrypted_name,
                    "path": full_href
                })
    except Exception as e:
        logger.error(f"❌ [xbiquge] 抓取新笔趣阁目录异常: {str(e)}")
        
    return chapters


def crawl_content(url: str) -> str:
    """
    实时拉取正文并清洗净化
    """
    clean_text = "抓取章节正文内容失败，请稍后刷新重试"
    session = get_secure_session()
    try:
        logger.info(f"🕸️ [xbiquge] 正在抓取正文: {url}")
        response = session.get(url, timeout=8, verify=False)
        response.encoding = 'gbk'
        html = response.text
        
        content_block = re.search(r'<div id="content">(.*?)</div>', html, re.S)
        if content_block:
            clean_text = clean_content_text(content_block.group(1))
    except Exception as e:
        logger.error(f"❌ [xbiquge] 抓取新笔趣阁正文出错: {str(e)}")
        
    return clean_text
