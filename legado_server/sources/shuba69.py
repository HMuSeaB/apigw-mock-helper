# -*- coding: utf-8 -*-
"""
apigw-mock-helper - 69书吧 (69shuba.com) 爬虫解析模块
"""

import re
import urllib.parse
import logging
from typing import Dict, Any, List
from sources.utils import get_secure_session, clean_content_text, aes_encrypt_base64

logger = logging.getLogger(__name__)

def crawl_search(keyword: str) -> List[Dict[str, Any]]:
    """
    去 69书吧 实时抓取并解析搜索结果 (防 403 升级版 - 彻底修复 GBK payload urlencode 问题)
    """
    books = []
    if not keyword:
        return books
        
    search_url = "https://www.69shuba.com/modules/article/search.php"
    session = get_secure_session()
    
    try:
        # 使用 urllib.parse.urlencode 显式指定 gbk 编码并转为 bytes
        payload_data = {
            "searchkey": keyword,
            "searchtype": "all"
        }
        encoded_payload = urllib.parse.urlencode(payload_data, encoding="gbk").encode("gbk")
        
        # 显式更新 Headers 的 Content-Type 为表单提交格式，绕开防火墙 403 拦截
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.69shuba.com/"
        }
        logger.info(f"🕸️ [shuba69] 正在实时发起 GBK 数据检索: keyword={keyword}")
        
        response = session.post(search_url, data=encoded_payload, headers=headers, timeout=8, verify=False)
        response.encoding = 'gbk'
        html = response.text
        
        # 状况 A：直接重定向到详情页 (通常因为精确匹配了书名)
        if "booknav2" in html:
            name_match = re.search(r'<h1><a href=".*?">(.*?)</a></h1>', html)
            author_match = re.search(r'<div class="booknav2">.*?作者：<a href=".*?">(.*?)</a>', html, re.S)
            url_match = re.search(r'property="og:url" content="(.*?)"', html)
            cover_match = re.search(r'<div class="bookimg2"><img src="(.*?)"', html)
            intro_match = re.search(r'<div class="navtxt">(.*?)</div>', html, re.S)
            
            if name_match and url_match:
                name = name_match.group(1).strip()
                author = author_match.group(1).strip() if author_match else "未知"
                url = url_match.group(1).strip()
                cover = cover_match.group(1).strip() if cover_match else "https://api.mwm.moe/ycy"
                intro = clean_content_text(intro_match.group(1)) if intro_match else "暂无简介"
                
                book_id_match = re.search(r'/book/(\d+)\.htm', url)
                book_id = book_id_match.group(1) if book_id_match else "38422"
                
                books.append({
                    "book_id": f"69_{book_id}",
                    "book_name": name,
                    "book_author": author,
                    "book_pic": cover,
                    "book_intro": intro[:150] + "...",
                    "book_lastchapter": "点击阅读本章节",
                    "categoryName": "69书吧 (自建云中转)"
                })
                
        # 状况 B：返回搜索结果列表页
        else:
            items = re.findall(r'<div class="newbox">.*?<li>(.*?)</li>', html, re.S)
            for item in items:
                name_url = re.search(r'<h3><a href="(.*?)">(.*?)</a></h3>', item)
                author = re.search(r'<span class="author">作者：(.*?)</span>', item)
                cover = re.search(r'<img src="(.*?)"', item)
                intro = re.search(r'<p>(.*?)</p>', item, re.S)
                
                if name_url:
                    url = name_url.group(1)
                    name = name_url.group(2).strip()
                    author_str = author.group(1).strip() if author else "未知"
                    cover_str = cover.group(1) if cover else "https://api.mwm.moe/ycy"
                    intro_str = re.sub(r'<.*?>|\s+', '', intro.group(1)) if intro else "暂无"
                    
                    book_id_match = re.search(r'/book/(\d+)\.htm', url)
                    book_id = book_id_match.group(1) if book_id_match else "38422"
                    
                    books.append({
                        "book_id": f"69_{book_id}",
                        "book_name": name,
                        "book_author": author_str,
                        "book_pic": cover_str,
                        "book_intro": intro_str[:150] + "...",
                        "book_lastchapter": "点击源站换源阅读",
                        "categoryName": "69书吧 (自建云中转)"
                    })
    except Exception as e:
        logger.error(f"❌ [shuba69] 实时搜索 69书吧 发生严重异常: {str(e)}")
        
    return books


def crawl_info(book_id: str) -> Dict[str, Any]:
    """
    实时去 69书吧 爬取书籍详情 (含动态更新时间)
    """
    from sources.utils import get_relative_time
    raw_id = book_id.replace("69_", "")
    book_url = f"https://www.69shuba.com/book/{raw_id}.htm"
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
        logger.info(f"🕸️ [shuba69] 正在实时抓取书籍详情: {book_url}")
        response = session.get(book_url, timeout=8, verify=False)
        response.encoding = 'gbk'
        html = response.text
        
        name_match = re.search(r'<h1><a href=".*?">(.*?)</a></h1>', html)
        author_match = re.search(r'<div class="booknav2">.*?作者：<a href=".*?">(.*?)</a>', html, re.S)
        cover_match = re.search(r'<div class="bookimg2"><img src="(.*?)"', html)
        intro_match = re.search(r'<div class="navtxt">(.*?)</div>', html, re.S)
        
        latest_match = re.search(r'最新章节：<a[^>]*>(.*?)</a>', html)
        if not latest_match:
            latest_match = re.search(r'property="og:novel:latest_chapter_name"\s+content="(.*?)"', html)
            
        update_match = re.search(r'property="og:novel:update_time"\s+content="(.*?)"', html)
        if not update_match:
            update_match = re.search(r'更新时间：\s*(.*?)(?:<|$)', html)
        
        if name_match:
            detail["book_name"] = name_match.group(1).strip()
        if author_match:
            detail["book_author"] = author_match.group(1).strip()
        if cover_match:
            detail["book_pic"] = cover_match.group(1).strip()
        if intro_match:
            detail["book_intro"] = clean_content_text(intro_match.group(1))
        if latest_match:
            detail["latest_ch"] = latest_match.group(1).strip()
        if update_match:
            raw_time = update_match.group(1).strip()
            detail["latest_update"] = get_relative_time(raw_time)
    except Exception as e:
        logger.error(f"❌ [shuba69] 抓取 69书吧 详情异常: {str(e)}")
        
    return detail


def crawl_toc(book_id: str) -> List[Dict[str, Any]]:
    """
    解析 69书吧目录结构
    """
    chapters = []
    raw_id = book_id.replace("69_", "")
    book_url = f"https://www.69shuba.com/book/{raw_id}.htm"
    session = get_secure_session()
    
    try:
        logger.info(f"🕸️ [shuba69] 正在实时抓取目录: {book_url}")
        response = session.get(book_url, timeout=8, verify=False)
        response.encoding = 'gbk'
        html = response.text
        
        catalog_block = re.search(r'<div class="catalog">.*?<ul>(.*?)</ul>', html, re.S)
        if catalog_block:
            li_tags = re.findall(r'<li.*?><a href="(.*?)">(.*?)</a></li>', catalog_block.group(1), re.S)
            for href, name in li_tags:
                clean_name = name.strip()
                encrypted_name = aes_encrypt_base64(clean_name)
                chapters.append({
                    "name": encrypted_name,
                    "path": href
                })
    except Exception as e:
        logger.error(f"❌ [shuba69] 抓取 69书吧 目录异常: {str(e)}")
        
    return chapters


def crawl_content(url: str) -> str:
    """
    实时拉取正文并清洗净化
    """
    clean_text = "抓取章节正文内容失败，请稍后刷新重试"
    session = get_secure_session()
    try:
        logger.info(f"🕸️ [shuba69] 正在抓取正文: {url}")
        response = session.get(url, timeout=8, verify=False)
        response.encoding = 'gbk'
        html = response.text
        
        content_block = re.search(r'<div class="txtnav">(.*?)</div>', html, re.S)
        if content_block:
            clean_text = clean_content_text(content_block.group(1))
    except Exception as e:
        logger.error(f"❌ [shuba69] 抓取 69书吧正文出错: {str(e)}")
        
    return clean_text
