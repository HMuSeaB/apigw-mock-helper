# -*- coding: utf-8 -*-
"""
apigw-mock-helper - 笔趣阁阁 (bqg78.com) 爬虫解析模块
"""

import re
import urllib.parse
import logging
from typing import Dict, Any, List
from sources.utils import get_secure_session, clean_content_text, aes_encrypt_base64

logger = logging.getLogger(__name__)

def crawl_search(keyword: str) -> List[Dict[str, Any]]:
    """
    搜索笔趣阁阁，返回符合规范的书籍列表
    """
    books = []
    if not keyword:
        return books
        
    session = get_secure_session()
    # 增加 Referer 伪装
    session.headers.update({
        "Referer": f"https://www.bqg78.com/s?q={urllib.parse.quote(keyword)}"
    })
    
    try:
        logger.info(f"🕸️ [bqg78] 正在激活检索索引: keyword={keyword}")
        # 激活检索 Cookie
        hm_url = f"https://www.bqg78.com/user/hm.html?q={urllib.parse.quote(keyword)}"
        session.get(hm_url, timeout=5)
        
        logger.info(f"🕸️ [bqg78] 正在请求 JSON 数据...")
        search_url = f"https://www.bqg78.com/user/search.html?q={urllib.parse.quote(keyword)}"
        response = session.get(search_url, timeout=6)
        
        if response.status_code == 200:
            results = response.json()
            logger.info(f"🕸️ [bqg78] 成功返回 {len(results)} 条数据")
            for item in results[:30]:
                name = item.get("articlename", "").strip()
                author = item.get("author", "").strip()
                cover = item.get("url_img", "").strip()
                url_path = item.get("url_list", "").strip()  # 例如 /book/1148/
                intro = item.get("intro", "").strip()
                
                # 提取纯数字 ID
                book_id_match = re.search(r'/book/(\d+)/', url_path)
                book_id = book_id_match.group(1) if book_id_match else "673"
                
                if not cover.startswith("http"):
                    cover = "https://www.bqg78.com" + cover
                    
                books.append({
                    "book_id": f"bqg78_{book_id}",
                    "book_name": name,
                    "book_author": author,
                    "book_pic": cover,
                    "book_intro": intro[:150] + "...",
                    "book_lastchapter": "点击进入换源",
                    "categoryName": "笔趣阁阁 (秒级直连)"
                })
        else:
            logger.warning(f"⚠️ [bqg78] 搜索请求失败，状态码: {response.status_code}")
    except Exception as e:
        logger.error(f"❌ [bqg78] 实时搜索发生异常: {str(e)}")
        
    return books


def crawl_info(book_id: str) -> Dict[str, Any]:
    """
    抓取笔趣阁阁书籍详情 (含3次自动重试防线与人性化更新时间转换)
    """
    from sources.utils import get_relative_time
    import time
    clean_id = book_id.replace("bqg78_", "")
    book_url = f"https://www.bqg78.com/book/{clean_id}/"
    session = get_secure_session()
    
    # 默认值
    detail = {
        "book_id": book_id,
        "book_name": "未知书籍",
        "book_author": "未知作者",
        "book_pic": "https://api.mwm.moe/ycy",
        "book_intro": "暂无简介",
        "latest_ch": "点击开始阅读",
        "latest_update": "刚刚"
    }
    
    try:
        logger.info(f"🕸️ [bqg78] 正在抓取书籍详情: {book_url}")
        
        response = None
        for attempt in range(3):
            try:
                response = session.get(book_url, timeout=8)
                if response.status_code == 200:
                    break
                logger.warning(f"⚠️ [bqg78] 尝试获取详情第 {attempt+1} 次失败，状态码: {response.status_code}")
            except Exception as ex:
                if attempt == 2:
                    logger.error(f"❌ [bqg78] 重试 3 次后获取详情依旧失败: {str(ex)}")
                    raise ex
                time.sleep(1.5)
                
        if response and response.status_code == 200:
            html = response.text
            
            # 解析书名、作者、封面、简介、最新章节、最新更新时间
            name_match = re.search(r'<div\s+class\s*=\s*"info">.*?<h1>(.*?)</h1>', html, re.S)
            author_match = re.search(r'<div\s+class\s*=\s*"info">.*?作者：(.*?)</div>', html, re.S)
            cover_match = re.search(r'<div\s+class\s*=\s*"bookimg">.*?<img\s+src\s*=\s*"([^"]+)"', html, re.S)
            intro_match = re.search(r'<div\s+class\s*=\s*"intro">(.*?)</div>', html, re.S)
            if not intro_match:
                intro_match = re.search(r'property="og:description"\s+content="(.*?)"', html, re.S)
                
            latest_match = re.search(r'property="og:novel:latest_chapter_name"\s+content="(.*?)"', html)
            if not latest_match:
                latest_match = re.search(r'最新章节：<a[^>]*>(.*?)</a>', html)
                
            update_match = re.search(r'property="og:novel:update_time"\s+content="(.*?)"', html)
            if not update_match:
                update_match = re.search(r'更新时间：\s*(.*?)(?:<|$)', html)
                
            if name_match:
                detail["book_name"] = name_match.group(1).strip()
            if author_match:
                # 剔除可能的 HTML 标签
                author_text = re.sub(r'<.*?>', '', author_match.group(1)).strip()
                detail["book_author"] = author_text
            if cover_match:
                cover_url = cover_match.group(1).strip()
                if not cover_url.startswith("http"):
                    cover_url = "https://www.bqg78.com" + cover_url
                detail["book_pic"] = cover_url
            if intro_match:
                detail["book_intro"] = clean_content_text(intro_match.group(1))
            if latest_match:
                detail["latest_ch"] = latest_match.group(1).strip()
            if update_match:
                raw_time = update_match.group(1).strip()
                detail["latest_update"] = get_relative_time(raw_time)
        else:
            logger.warning("⚠️ [bqg78] 未能成功获取详情响应")
    except Exception as e:
        logger.error(f"❌ [bqg78] 获取详情异常: {str(e)}")
        
    return detail


def crawl_toc(book_id: str) -> List[Dict[str, Any]]:
    """
    抓取目录结构，并对章节名称进行 AES 动态打包
    """
    chapters = []
    clean_id = book_id.replace("bqg78_", "")
    book_url = f"https://www.bqg78.com/book/{clean_id}/"
    session = get_secure_session()
    
    try:
        logger.info(f"🕸️ [bqg78] 正在抓取章节目录: {book_url}")
        response = session.get(book_url, timeout=8)
        if response.status_code == 200:
            html = response.text
            dd_tags = re.findall(r'<dd><a\s+href\s*=\s*"([^"]+)">(.*?)</a></dd>', html, re.S)
            for href, name in dd_tags:
                clean_name = name.strip()
                encrypted_name = aes_encrypt_base64(clean_name)
                # 章节链接需拼接为绝对路径
                full_href = href
                if not href.startswith("http"):
                    full_href = "https://www.bqg78.com" + href
                chapters.append({
                    "name": encrypted_name,
                    "path": full_href
                })
        else:
            logger.warning(f"⚠️ [bqg78] 获取目录失败，状态码: {response.status_code}")
    except Exception as e:
        logger.error(f"❌ [bqg78] 抓取目录失败: {str(e)}")
        
    return chapters


def crawl_content(url: str) -> str:
    """
    实时拉取正文并清洗净化 (加入 Referer 完美过防盗链保护)
    """
    clean_text = "抓取章节正文内容失败，请稍后刷新重试"
    session = get_secure_session()
    
    # 提取 book_id 以构造 Referer 伪装
    book_id_match = re.search(r'/book/(\d+)/', url)
    if book_id_match:
        clean_id = book_id_match.group(1)
        session.headers.update({
            "Referer": f"https://www.bqg78.com/book/{clean_id}/"
        })
    else:
        session.headers.update({
            "Referer": "https://www.bqg78.com/"
        })
        
    try:
        logger.info(f"🕸️ [bqg78] 正在抓取正文内容: {url}")
        response = session.get(url, timeout=8)
        if response.status_code == 200:
            html = response.text
            # 兼容多种常见的笔趣阁系正文包裹标签 (包含 #content, .content, #htmlContent, #chaptercontent)
            content_block = re.search(r'<div\s+id\s*=\s*"content">(.*?)</div>', html, re.S)
            if not content_block:
                content_block = re.search(r'<div\s+id\s*=\s*"chaptercontent">(.*?)</div>', html, re.S)
            if not content_block:
                content_block = re.search(r'<div\s+id\s*=\s*"htmlContent">(.*?)</div>', html, re.S)
            if not content_block:
                content_block = re.search(r'<div\s+class\s*=\s*"content">(.*?)</div>', html, re.S)
                
            if content_block:
                clean_text = clean_content_text(content_block.group(1))
            else:
                logger.warning("⚠️ [bqg78] 未能在页面中匹配到任何正文包裹 DIV 标签")
        else:
            logger.warning(f"⚠️ [bqg78] 获取正文失败，状态码: {response.status_code}")
    except Exception as e:
        logger.error(f"❌ [bqg78] 抓取正文出错: {str(e)}")
        
    return clean_text
