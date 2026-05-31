# -*- coding: utf-8 -*-
"""
apigw-mock-helper - 通用 API 代理与协议测试网关 (重构模块化版)
"""

import os
import json
import sqlite3
import logging
import secrets
from typing import Dict, Any, List
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse

from sources import manager as sources_manager
from sources import bqg78
from sources.utils import aes_encrypt_base64

# 1. 基础配置与日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="apigw-mock-helper-api")
DB_FILE = os.path.join(os.path.dirname(__file__), "legado.db")

# 全局多源 ID 智能自愈与对齐缓存字典 (书名 -> {源站: ID})
ID_ALIGNMENT_CACHE = {}

# 全局正文中转模式开关 (False 表示不走中转直接 302 重定向直连原站，True 表示走服务端中转中介清洗)
PROXY_CONTENT_DELIVERY = True

# ==================== 全局多源备用指引 (本地 sources.json 动态配置) ====================
MULTISOURCE_INTRO = ""
EXTERNAL_RESOURCES = []

def load_external_sources():
    global MULTISOURCE_INTRO, EXTERNAL_RESOURCES
    sources_path = os.path.join(os.path.dirname(__file__), "sources.json")
    if os.path.exists(sources_path):
        try:
            with open(sources_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                MULTISOURCE_INTRO = data.get("multisource_intro", "")
                EXTERNAL_RESOURCES = data.get("resources", [])
                logger.info("✅ 成功加载本地私有外部数据源配置 (sources.json)")
        except Exception as e:
            logger.error(f"⚠️ 读取 sources.json 失败: {str(e)}")
    else:
        MULTISOURCE_INTRO = "\n\n📌使用说明：请放置本地 sources.json 以激活多数据源中转指引。"
        EXTERNAL_RESOURCES = []

load_external_sources()


# ==================== SQLite 本地云书架数据库管理 ====================

def init_db():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            # 用户表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mobile TEXT UNIQUE NOT NULL,
                    nickname TEXT NOT NULL,
                    password TEXT NOT NULL,
                    token TEXT UNIQUE NOT NULL
                )
            """)
            # 用户书架绑定表 (存放用户收藏的书籍，包含了我们在爬虫阶段为其编造的虚拟 book_id)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sheets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    book_id TEXT NOT NULL,
                    book_name TEXT NOT NULL,
                    book_author TEXT NOT NULL,
                    book_pic TEXT NOT NULL,
                    book_intro TEXT NOT NULL,
                    toc_url TEXT NOT NULL,
                    UNIQUE(user_id, book_id),
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
            """)
            # 多源对齐 ID 持久化表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS aligned_ids (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_name TEXT NOT NULL,
                    source_domain TEXT NOT NULL,
                    raw_id TEXT NOT NULL,
                    pref TEXT NOT NULL,
                    UNIQUE(book_name, source_domain)
                )
            """)
            # 升级已有表字段 (添加对齐ID)
            try:
                cursor.execute("ALTER TABLE sheets ADD COLUMN aligned_bq_id TEXT")
            except sqlite3.OperationalError:
                pass # 列已存在
            try:
                cursor.execute("ALTER TABLE sheets ADD COLUMN aligned_69_id TEXT")
            except sqlite3.OperationalError:
                pass # 列已存在
            conn.commit()
            logger.info("SQLite 数据库初始化及建表及平滑升级成功。")
    except Exception as e:
        logger.error(f"初始化数据库失败: {str(e)}")

init_db()


def verify_user(uid: str, token: str) -> int:
    """
    验证客户端下发的 UID 和 Token
    """
    if not uid or not token:
        return 0
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE id = ? AND token = ?", (uid, token))
            row = cursor.fetchone()
            if row:
                return row[0]
    except Exception as e:
        logger.error(f"校验用户身份凭证失败: {str(e)}")
    return 0


# ==================== FastAPI 核心 API 路由接口 ====================

@app.get("/", response_class=HTMLResponse)
async def index():
    """
    根路由：提供精美的 API 网关健康状态运行提示页面 (保持高水准的技术伪装)
    """
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>API Gateway Mock Helper</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                background-color: #0c0c0e;
                color: #e4e4e7;
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100vh;
                margin: 0;
            }
            .container {
                text-align: center;
                padding: 3rem 2.5rem;
                background: #141416;
                border-radius: 16px;
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
                border: 1px solid #27272a;
                max-width: 450px;
                width: 90%;
            }
            h1 {
                color: #10b981;
                font-size: 2rem;
                margin: 0 0 0.8rem 0;
                letter-spacing: -0.025em;
                font-weight: 700;
            }
            p {
                color: #a1a1aa;
                font-size: 1rem;
                line-height: 1.5;
                margin: 0 0 1.5rem 0;
            }
            .status {
                display: inline-block;
                padding: 0.4rem 1.2rem;
                background: rgba(16, 185, 129, 0.1);
                color: #10b981;
                border-radius: 30px;
                font-weight: 600;
                font-size: 0.875rem;
                border: 1px solid rgba(16, 185, 129, 0.25);
                letter-spacing: 0.05em;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>apigw-mock-helper</h1>
            <p>API Proxy Gateway & Protocol Testing Service is running successfully.</p>
            <div class="status">● ACTIVE</div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)


@app.post("/api.php/Book/getSearchBook")
async def get_search_book(request: Request):
    """
    一、 全网实时去重搜索 API
    """
    try:
        try:
            body = await request.json()
        except Exception:
            try:
                # 兼容由于 Windows 终端转义问题导致的非标 JSON 字符串
                raw_body = await request.body()
                raw_str = raw_body.decode('utf-8', errors='ignore').strip()
                body = json.loads(raw_str)
            except Exception as json_err:
                logger.warning(f"解析非标 JSON 请求体失败: {str(json_err)}")
                body = {}

        keyword = body.get("keyword", "").strip()
        logger.info(f"🔔 收到阅读客户端全局搜索指令: keyword='{keyword}'")
        
        if not keyword:
            return JSONResponse(content={"msg": "Success", "code": 0, "data": {"list": []}})
        
        # 调度多源模块合并去重搜索
        merged_books = sources_manager.search_books(keyword)
        
        # 空白保护：如果全网没有搜到，返回一本自建引导的虚拟演示书
        if not merged_books:
            merged_books.append({
                "book_id": "69_43977",
                "book_name": f"未搜到《{keyword}》，点击体验测试",
                "book_author": "自建云聚合",
                "book_pic": "https://api.mwm.moe/ycy",
                "book_intro": "📂 简介：自建服务器没有在各个书源检索到对应书籍，您可以点击此书测试云端实时目录抓取和正文 AES 解密功能！",
                "book_lastchapter": "第一章 开始自建看书之旅",
                "categoryName": "云聚合演示"
            })
            
        return JSONResponse(content={
            "msg": "Success",
            "code": 0,
            "data": {
                "list": merged_books
            }
        })
    except Exception as e:
        logger.error(f"搜书总接口内部出错: {str(e)}")
        return JSONResponse(status_code=500, content={"msg": str(e), "code": -1})


@app.post("/api.php/Book/getBookInfo")
async def get_book_info(request: Request):
    """
    二、 书籍详情 API (提供实时原站信息匹配与备用换源指引拼装，完美支持动态更新时间同步)
    """
    try:
        try:
            body = await request.json()
            book_id = str(body.get("bookId", "69_43977")).strip()
        except Exception:
            book_id = request.query_params.get("bookId", "69_43977").strip()
            
        logger.info(f"🔔 详情页获取: bookId={book_id}")
        
        # 调度模块层获取各大源站的真实图书数据 (并提供极致的 try-except 安全保护，防止抛出 500)
        try:
            book_detail = sources_manager.get_book_info(book_id)
            book_name = book_detail.get("book_name", "精选多源小说")
            book_author = book_detail.get("book_author", "多源聚合")
            book_pic = book_detail.get("book_pic", "https://api.mwm.moe/ycy")
            book_intro = book_detail.get("book_intro", "实时中转及云备份服务")
            latest_ch = book_detail.get("latest_ch", "开始阅读")
            latest_update = book_detail.get("latest_update", "实时更新")
        except Exception as crawl_err:
            logger.warning(f"⚠️ 调度模块获取图书详情失败: {str(crawl_err)}，启动安全兜底机制")
            book_name = "自建云聚合小说"
            book_author = "多源聚合"
            book_pic = "https://api.mwm.moe/ycy"
            book_intro = "📂 智能云中转极速解析服务。"
            latest_ch = "开始阅读"
            latest_update = "实时同步中"

        # 简介去重净化重构：移除向简介追加 formatted_intro 的冗余逻辑，仅返回纯净的原站简介，交由客户端 JS 渲染唯一换源说明
        pass
        
        # 计算不带端口号的安全物理直连目录链接，作为手机端最后的 fallback 安全气囊，彻底消除闪退可能！
        raw_id = "673"
        for prefix in ["bqg78_", "69_", "xs_", "bq_"]:
            if book_id.startswith(prefix):
                raw_id = book_id.replace(prefix, "")
                break
                
        try:
            val_id = int(raw_id)
            pref = str(val_id // 1000)
        except ValueError:
            pref = "0"
            
        fallback_toc_url = f"https://www.bqg78.com/book/{raw_id}/"
        if book_id.startswith("69_"):
            fallback_toc_url = f"https://www.69shuba.tw/book/{raw_id}.htm"
        elif book_id.startswith("xs_"):
            fallback_toc_url = f"https://www.ibiquges.org/{pref}/{raw_id}/"
        
        return JSONResponse(content={
            "msg": "Success",
            "code": 0,
            "data": {
                "info": {
                    "book_id": book_id,
                    "book_name": book_name,
                    "book_author": book_author,
                    "book_pic": book_pic,
                    "book_intro": book_intro,
                    "tocUrl": fallback_toc_url,  # 注入无端口直连 fallback_toc_url
                    "categoryName": "实时云聚合"
                }
            }
        })
    except Exception as e:
        logger.error(f"详情接口内部出错: {str(e)}")
        return JSONResponse(status_code=500, content={"msg": str(e), "code": -1})


@app.api_route("/api.php/Book/getResources", methods=["GET", "POST"])
async def get_resources(request: Request):
    """
    三、 核心 API：获取书籍的实时目录并对其下发 AES-128-CBC 加密包
    客户端 ruleToc.chapterList 会读取 $.data.chapters，
    章节名称 ruleToc.chapterName 会配合本地 Rhino 用密码 Pxga!h*e4@T8xfOm 解密章节名字。
    """
    try:
        book_id = "69_43977"
        if request.method == "POST":
            try:
                body = await request.json()
                book_id = str(body.get("bookId", book_id)).strip()
            except Exception:
                book_id = request.query_params.get("bookId", book_id).strip()
        else:
            book_id = request.query_params.get("bookId", book_id).strip()

        logger.info(f"🔔 实时目录抓取与AES加密 ({request.method}): bookId={book_id}")
        
        # 0. 快速拉取详情以取得最新章节名与真实更新时间，避免向 18 个备用源发起慢速网络请求导致超时！
        book_detail = sources_manager.get_book_info(book_id)
        latest_ch = book_detail.get("latest_ch", "点击开始阅读")
        latest_update = book_detail.get("latest_update", "实时同步")

        # 1. 获取纯数字 ID 与前缀
        raw_id = "673"
        for prefix in ["bqg78_", "69_", "xs_", "bq_"]:
            if book_id.startswith(prefix):
                raw_id = book_id.replace(prefix, "")
                break
                
        try:
            val_id = int(raw_id)
            pref = str(val_id // 1000)
        except ValueError:
            pref = "0"
            
        # 开启国防级全局双向 ID 智能自愈与对齐系统 (支持数据库物理级别自愈 + 内存缓存加速)
        book_name = book_detail.get("book_name", "").strip()
        book_author = book_detail.get("book_author", "").strip()
        aligned_bq_raw_id = raw_id
        aligned_bq_pref = pref
        aligned_69_raw_id = raw_id

        # A. 优先从 SQLite sheets 数据库中拉取固化物理对齐 ID
        db_aligned_bq_id = ""
        db_aligned_69_id = ""
        try:
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT aligned_bq_id, aligned_69_id FROM sheets WHERE book_id = ?", (book_id,))
                row = cursor.fetchone()
                if row:
                    db_aligned_bq_id = row[0] or ""
                    db_aligned_69_id = row[1] or ""
        except Exception as db_err:
            logger.warning(f"⚠️ [align] 读取 SQLite 物理对齐 ID 异常: {str(db_err)}")

        if db_aligned_bq_id and db_aligned_69_id:
            logger.info(f"🎯 [align] 成功从 SQLite 提取固化物理对齐 ID: bq='{db_aligned_bq_id}', 69='{db_aligned_69_id}'")
            aligned_bq_raw_id = db_aligned_bq_id
            aligned_69_raw_id = db_aligned_69_id
            try:
                val_id = int(aligned_bq_raw_id)
                aligned_bq_pref = str(val_id // 1000)
            except ValueError:
                aligned_bq_pref = "0"
        else:
            # B. 降级走内存缓存与网络动态自愈
            if not book_id.startswith("69_"):
                # 主源为笔趣阁类，其本身的 ID 体系代表笔趣阁 ID，我们要去检索 69 书吧 ID 以供换源 69 时使用
                aligned_bq_raw_id = raw_id
                aligned_bq_pref = pref
                cache_key = f"{book_name}_69"
                if cache_key in ID_ALIGNMENT_CACHE:
                    aligned_69_raw_id = ID_ALIGNMENT_CACHE[cache_key]
                else:
                    try:
                        if book_name:
                            logger.info(f"🔄 [align] 正在为笔趣阁主源智能检索 69 书吧对齐 ID: '{book_name}'")
                            from sources import shuba69
                            search_results = shuba69.crawl_search(book_name)
                            for b in search_results:
                                if b.get("book_name", "").strip() == book_name:
                                    b_id = b.get("book_id", "")
                                    if b_id.startswith("69_"):
                                        aligned_69_raw_id = b_id.replace("69_", "")
                                        ID_ALIGNMENT_CACHE[cache_key] = aligned_69_raw_id
                                        logger.info(f"🎯 [align] 成功将笔趣阁 ID '{raw_id}' 对齐至 69 书吧真实 ID '{aligned_69_raw_id}'！")
                                        break
                    except Exception as align_err:
                        logger.warning(f"⚠️ [align] 检索 69 书吧对齐 ID 发生异常: {str(align_err)}")
            else:
                # 主源为 69 书吧，其本身的 ID 体系代表 69 书吧 ID，我们要去检索笔趣阁 ID 以供换源备用源时使用
                aligned_69_raw_id = raw_id
                cache_key = f"{book_name}_bq"
                if cache_key in ID_ALIGNMENT_CACHE:
                    aligned_bq_raw_id = ID_ALIGNMENT_CACHE[cache_key]
                    try:
                        val_id = int(aligned_bq_raw_id)
                        aligned_bq_pref = str(val_id // 1000)
                    except ValueError:
                        aligned_bq_pref = "0"
                else:
                    try:
                        if book_name:
                            logger.info(f"🔄 [align] 正在为 69 书吧主源智能检索笔趣阁对齐 ID: '{book_name}'")
                            search_results = bqg78.crawl_search(book_name)
                            for b in search_results:
                                if b.get("book_name", "").strip() == book_name:
                                    bq_id = b.get("book_id", "")
                                    if bq_id.startswith("bqg78_"):
                                        aligned_bq_raw_id = bq_id.replace("bqg78_", "")
                                        ID_ALIGNMENT_CACHE[cache_key] = aligned_bq_raw_id
                                        try:
                                            val_id = int(aligned_bq_raw_id)
                                            aligned_bq_pref = str(val_id // 1000)
                                        except ValueError:
                                            aligned_bq_pref = "0"
                                        logger.info(f"🎯 [align] 成功将 69 书吧 ID '{raw_id}' 对齐至笔趣阁真实 ID '{aligned_bq_raw_id}' (pref={aligned_bq_pref})！")
                                        break
                    except Exception as align_err:
                        logger.warning(f"⚠️ [align] 检索笔趣阁对齐 ID 发生异常: {str(align_err)}")

        # 检测是否为带端口的 IP 访问，规避手机客户端对于端口号冒号的正则匹配闪退缺陷
        host = request.headers.get("host", "")
        is_port_access = ":" in host
        logger.info(f"🔍 访问模式检测: host={host}, is_port_access={is_port_access}")

        # 2. 从本地加载并格式化 19 个全网最强小说镜像源并动态注入自愈 ID
        resources_list = []
        gateway_url = str(request.base_url).rstrip("/")
        for res in EXTERNAL_RESOURCES:
            res_copy = dict(res)
            try:
                # 强行在内存中硬重写升级提取正则，彻底根治 1Panel/Docker 单文件挂载 inode 冲突导致 sources.json 同步失败的隐患！
                res_copy["chapterUrl"] = {"rule": 'href\\s*=\\s*["\']((?!https?:)[^"\']*(?:/)?\\d+\\.html?)["\']'}
                res_copy["chapterName"] = {"rule": 'href\\s*=\\s*["\']?(?!https?:)[^"\'\\s>]*(?:/)?\\d+\\.html?["\']?[^>]*>([^<]+)</a>'}

                # 动态填充 URL 中的所有占位符，补齐绝对主机与协议以防止客户端正则 match null 闪退！
                raw_url = res.get("chapterPageUrl", "")
                if is_port_access:
                    # 如果是带端口访问，为了彻底防止手机端正则闪退，将代理链接恢复为真实的没有端口号的物理直连链接
                    formatted_url = raw_url.replace("{gateway_url}/proxy/", "https://")
                else:
                    formatted_url = raw_url.replace("{gateway_url}", gateway_url)
                
                # 动态根据备用源站的种类，自适应拼入校正对齐后的真实物理 ID
                if "69shuba" in res.get("sourceName", "") or "69" in res.get("sourceName", ""):
                    formatted_url = formatted_url.replace("{raw_id}", aligned_69_raw_id).replace("{pref}", "0")
                else:
                    formatted_url = formatted_url.replace("{raw_id}", aligned_bq_raw_id).replace("{pref}", aligned_bq_pref)
                
                # 动态把书名 and 作者通过 urllib.parse.quote 编码成 Query 参数，强行附在链接尾部，确保切源时网关能智能自愈！
                import urllib.parse
                encoded_name = urllib.parse.quote(book_name)
                encoded_author = urllib.parse.quote(book_author)
                if "?" in formatted_url:
                    formatted_url += f"&real_book_name={encoded_name}&real_book_author={encoded_author}"
                else:
                    formatted_url += f"?real_book_name={encoded_name}&real_book_author={encoded_author}"

                res_copy["chapterPageUrl"] = formatted_url
                # 动态将镜像源里的最新章节和更新时间，无缝同步为本书最精确的真实数据！
                res_copy["sourceLastChapter"] = latest_ch
                res_copy["sourceLastChapterUpdate"] = latest_update
            except Exception as format_err:
                logger.warning(f"⚠️ 格式化外部源失败: {str(format_err)}")
                pass
            resources_list.append(res_copy)

        # 3. 调度爬虫获取目录结构，并强力将章节链接透明中转至网关 (增加 try-except 强力保护，防止异常爆 500 导致闪退)
        try:
            raw_chapters = sources_manager.get_chapters(book_id)
        except Exception as crawl_ch_err:
            logger.warning(f"⚠️ 调度模块获取章节列表失败: {str(crawl_ch_err)}，启动安全空列表兜底保护")
            raw_chapters = []

        gateway_url = str(request.base_url).rstrip("/")
        
        final_chapters = []
        for ch in raw_chapters:
            try:
                ch_copy = dict(ch)
                original_path = ch.get('path', '').strip()
                
                # 智能剥离章节链接中的协议与域名部分，使其彻底转化为以 "/" 开头的规范相对路径
                # 这样可以 100% 契合客户端 JS 的 "sourceUrl1 + uri" 粗暴拼接规则，彻底消灭双重 http 粘连与 UnknownHost 异常！
                cleaned_path = original_path
                if cleaned_path.startswith(("http://", "https://")):
                    from urllib.parse import urlparse
                    parsed = urlparse(cleaned_path)
                    cleaned_path = parsed.path
                    if parsed.query:
                        cleaned_path += f"?{parsed.query}"
                
                # 确保清洗后的路径一定以 "/" 开头，强制走客户端的 baseUrl 正确域拼接分支
                if not cleaned_path.startswith("/"):
                    cleaned_path = "/" + cleaned_path
                
                if is_port_access:
                    # 如果是带端口访问，为了彻底消除代理导致的相对路径解析错误，章节 path 降级为真实的物理直连相对 URL
                    ch_copy["path"] = cleaned_path
                else:
                    # 域名访问下也使用不带域名的相对中转链接，由客户端 JS 拼接网关地址，过 WAF 破盾秒开
                    ch_copy["path"] = f"/api.php/Book/getRealContent?url={cleaned_path}"
                
                final_chapters.append(ch_copy)
            except Exception:
                pass
        
        # 4. 无论何种访问模式，均下发完整的 19 个备用源配置，100% 避免因客户端序号越界导致闪退崩溃
        final_resources = resources_list
        
        return JSONResponse(content={
            "msg": "Success",
            "code": 0,
            "data": {
                "chapters": final_chapters,
                "resources": final_resources
            }
        })
    except Exception as e:
        logger.error(f"获取章节列表接口失败: {str(e)}")
        return JSONResponse(status_code=500, content={"msg": str(e), "code": -1})


@app.api_route("/api.php/Book/getRealContent", methods=["GET", "POST"])
async def get_real_content(request: Request):
    """
    四、 核心 API：实时拉取正文、广告智能净化清洗与云端透明中转网关 (兼容 GET 纯 HTML 输出)
    """
    try:
        url = ""
        if request.method == "GET":
            url = request.query_params.get("url", "").strip()
        else:
            try:
                body = await request.json()
                url = body.get("url", "").strip()
            except Exception:
                pass
                
        if not url:
            if request.method == "GET":
                return HTMLResponse(content="未指定有效的正文链接参数", status_code=400)
            return JSONResponse(content={"msg": "未指定正文链接参数", "code": -1})

        # 物理还原域名
        url = url.strip()
        if "ddyueshu.com" in url and "/book/" in url:
            url = url.replace("/book/", "/")

        # 核心：如果不开启中转分发，直接 302 重定向直连原站，彻底不通过服务端中转！
        if not PROXY_CONTENT_DELIVERY:
            logger.info(f"🔄 [proxy] 已启用 302 不中转直连，重定向至原站正文: {url}")
            return RedirectResponse(url=url, status_code=302)

        # A. 针对手机端直接 GET 请求章节正文代理 (透明中转免盾秒开轨)
        if request.method == "GET":
            # 调度云端爬虫爬取并智能净化
            clean_text = sources_manager.get_content(url)
            
            # 直接以精美的极简 HTML 包裹正文返回，让手机客户端用 id="content" 或 java.getElement 完美提取！
            html_template = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>Proxy Content</title>
            </head>
            <body>
                <div id="content">{clean_text}</div>
            </body>
            </html>
            """
            return HTMLResponse(content=html_template, status_code=200)
            
        # B. 针对自建接口常规 POST 的 JSON 数据分发轨
        # 此时肯定已经提取到了 url，直接使用中转拉取
        clean_text = sources_manager.get_content(url)
        encrypted_text = aes_encrypt_base64(clean_text)
        
        return JSONResponse(content={
            "msg": "Success",
            "code": 0,
            "data": {
                "content": encrypted_text
            }
        })
    except Exception as e:
        logger.error(f"正文抓取代理接口发生异常: {str(e)}")
        if request.method == "GET":
            return HTMLResponse(content=f"正文代理服务发生内部异常: {str(e)}", status_code=500)
        return JSONResponse(status_code=500, content={"msg": str(e), "code": -1})


# ==================== SQLite 联动之云书架交互接口 ====================

@app.post("/api.php/users/register")
async def register(request: Request):
    """
    五、 云书架注册接口
    """
    try:
        body = await request.json()
        mobile = body.get("mobile", "").strip()
        nickname = body.get("nickname", "").strip()
        password = body.get("password", "").strip()

        if not mobile or not password:
            return JSONResponse(content={"msg": "注册失败：手机号和密码不能为空", "code": -1})

        user_token = secrets.token_hex(16)

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO users (mobile, nickname, password, token) VALUES (?, ?, ?, ?)",
                    (mobile, nickname, password, user_token)
                )
                conn.commit()
                logger.info(f"新用户注册成功: {mobile}")
                return JSONResponse(content={"msg": "注册成功！请点击登入", "code": 0})
            except sqlite3.IntegrityError:
                return JSONResponse(content={"msg": "注册失败：该手机号已被注册", "code": -1})
    except Exception as e:
        logger.error(f"注册接口异常: {str(e)}")
        return JSONResponse(content={"msg": f"服务端异常: {str(e)}", "code": -1})


@app.post("/api.php/users/login")
async def login(request: Request):
    """
    六、 云书架登录接口
    """
    try:
        body = await request.json()
        mobile = body.get("mobile", "").strip()
        password = body.get("password", "").strip()

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, nickname, token FROM users WHERE mobile = ? AND password = ?", (mobile, password))
            row = cursor.fetchone()
            if row:
                user_id, nickname, token = row
                logger.info(f"用户登录成功: UID={user_id}, 昵称={nickname}")
                return JSONResponse(content={
                    "msg": f"欢迎您，{nickname}！登录成功",
                    "code": 0,
                    "data": {
                        "userId": str(user_id),
                        "token": token
                    }
                })
            else:
                return JSONResponse(content={"msg": "登录失败：手机号或密码错误", "code": -1})
    except Exception as e:
        logger.error(f"登录接口异常: {str(e)}")
        return JSONResponse(content={"msg": f"服务端异常: {str(e)}", "code": -1})


@app.post("/api.php/users/addSheet")
async def add_sheet(request: Request, uid: str = Header(None), token: str = Header(None)):
    """
    七、 添加书籍到我的云书架 (SQLite 持久化关系，自动调用 CRAWL 获取详情存储)
    """
    try:
        user_id = verify_user(uid, token)
        if not user_id:
            return JSONResponse(content={"msg": "操作失败：请先登入！", "code": -1})

        body = await request.json()
        book_id = str(body.get("bookId", "")).strip()

        if not book_id:
            return JSONResponse(content={"msg": "操作失败：书籍 ID 不能为空", "code": -1})

        # 触发一次详情抓取，用来自动填充保存在 SQLite 书架表中的书籍属性，以供发现页优雅渲染
        book_detail = sources_manager.get_book_info(book_id)
        
        book_name = book_detail.get("book_name", "自选实时源书籍")
        book_author = book_detail.get("book_author", "多源聚合")
        book_pic = book_detail.get("book_pic", "https://api.mwm.moe/ycy")
        book_intro = book_detail.get("book_intro", "云端书架收藏书籍")
        
        # 裁剪可能过长的中转使用说明简介，以免数据库行过于庞大
        if len(book_intro) > 300:
            book_intro = book_intro[:300] + "..."

        # 自动对齐本小说的笔趣阁ID和69书吧ID，固化写入 SQLite 云书架，永保0毫秒免检对齐
        aligned_bq_id = ""
        aligned_69_id = ""
        
        # 提取当前纯数字 ID
        raw_id = ""
        for prefix in ["bqg78_", "69_", "xs_", "bq_"]:
            if book_id.startswith(prefix):
                raw_id = book_id.replace(prefix, "")
                break
        if not raw_id:
            raw_id = book_id

        if not book_id.startswith("69_"):
            # 当前为主源笔趣阁类，其本身就是笔趣阁通用 ID，去检索 69 书吧 ID 对齐
            aligned_bq_id = raw_id
            try:
                if book_name:
                    logger.info(f"🔄 [addSheet] 正在为新加书籍 '{book_name}' 物理对齐 69 书吧 ID")
                    from sources import shuba69
                    search_results = shuba69.crawl_search(book_name)
                    for b in search_results:
                        if b.get("book_name", "").strip() == book_name:
                            b_id = b.get("book_id", "")
                            if b_id.startswith("69_"):
                                aligned_69_id = b_id.replace("69_", "")
                                break
            except Exception as e:
                logger.warning(f"⚠️ [addSheet] 对齐 69 书吧 ID 失败: {e}")
        else:
            # 当前为 69 书吧主源，去检索笔趣阁 ID 对齐
            aligned_69_id = raw_id
            try:
                if book_name:
                    logger.info(f"🔄 [addSheet] 正在为新加书籍 '{book_name}' 物理对齐笔趣阁 ID")
                    search_results = bqg78.crawl_search(book_name)
                    for b in search_results:
                        if b.get("book_name", "").strip() == book_name:
                            bq_id = b.get("book_id", "")
                            if bq_id.startswith("bqg78_"):
                                aligned_bq_id = bq_id.replace("bqg78_", "")
                                break
            except Exception as e:
                logger.warning(f"⚠️ [addSheet] 对齐笔趣阁 ID 失败: {e}")

        logger.info(f"用户 UID={user_id} 添加书籍 ID={book_id} 到云端书架 (对齐ID: bq='{aligned_bq_id}', 69='{aligned_69_id}')")

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO sheets (user_id, book_id, book_name, book_author, book_pic, book_intro, toc_url, aligned_bq_id, aligned_69_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, book_id, book_name, book_author, book_pic, book_intro, "", aligned_bq_id, aligned_69_id)
                )
                conn.commit()
                return JSONResponse(content={"msg": "Success", "code": 0})
            except sqlite3.IntegrityError:
                return JSONResponse(content={"msg": "操作成功：书架已存在该书籍", "code": 0})
    except Exception as e:
        logger.error(f"添加书架异常: {str(e)}")
        return JSONResponse(content={"msg": f"服务端异常: {str(e)}", "code": -1})


@app.post("/api.php/users/sheetSetDelete")
async def delete_sheet(request: Request, uid: str = Header(None), token: str = Header(None)):
    """
    八、 从我的云书架移除书籍
    """
    try:
        user_id = verify_user(uid, token)
        if not user_id:
            return JSONResponse(content={"msg": "操作失败：请先登入！", "code": -1})

        body = await request.json()
        ids: List[Any] = body.get("ids", [])
        if not ids:
            return JSONResponse(content={"msg": "操作失败：未指定移除书籍", "code": -1})

        book_id = str(ids[0]).strip()
        logger.info(f"用户 UID={user_id} 从云书架移除书籍 ID={book_id}")

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sheets WHERE user_id = ? AND book_id = ?", (user_id, book_id))
            conn.commit()
            return JSONResponse(content={"msg": "Success", "code": 0})
    except Exception as e:
        logger.error(f"删除书架书籍异常: {str(e)}")
        return JSONResponse(content={"msg": f"服务端异常: {str(e)}", "code": -1})


@app.post("/api.php/users/getSheet")
async def get_sheet(request: Request, uid: str = Header(None), token: str = Header(None)):
    """
    九、 发现页拉取我的云书架列表 API
    """
    try:
        user_id = verify_user(uid, token)
        if not user_id:
            return JSONResponse(content={"msg": "未登录，云书架暂空", "code": 0, "data": {"list": []}})

        logger.info(f"用户 UID={user_id} 正在拉取发现页云书架列表")

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT book_id, book_name, book_author, book_pic, book_intro FROM sheets WHERE user_id = ?", (user_id,))
            rows = cursor.fetchall()

        results = []
        for row in rows:
            bid, name, author, pic, intro = row
            results.append({
                "book_id": bid,
                "book_name": name if name else f"自建书籍 ID: {bid}",
                "book_author": author if author else "自建多源",
                "book_pic": pic if pic else "https://api.mwm.moe/ycy",
                "book_intro": intro if intro else "云端书架收藏书籍",
                "book_lastchapter": "点击进入换源阅读",
                "categoryName": "我的云书架"
            })

        return JSONResponse(content={"msg": "Success", "code": 0, "data": {"list": results}})
    except Exception as e:
        logger.error(f"发现页拉取书架失败: {str(e)}")
        return JSONResponse(content={"msg": f"服务端异常: {str(e)}", "code": -1})


def find_aligned_id(source_domain: str, book_name: str, raw_path: str = "") -> Dict[str, str]:
    """
    通用嗅探搜寻算法：针对未对齐的备用小说域名进行精确 ID 对齐 (支持多重搜索路径、GBK/UTF-8自动编码及 302 重定向自愈)
    """
    import urllib.parse
    import re
    from sources.utils import get_secure_session
    
    book_name = book_name.strip()
    source_domain = source_domain.strip().lower()
    
    # 解析自适应主源原生 ID 作为备用兜底值，不使用硬编码的 673，防止错配！
    fallback_raw_id = "673"
    fallback_pref = "0"
    if raw_path:
        numbers = re.findall(r'\d+', raw_path)
        if len(numbers) >= 2:
            fallback_raw_id = numbers[-1]
            fallback_pref = numbers[-2]
        elif len(numbers) == 1:
            fallback_raw_id = numbers[0]
            fallback_pref = "0"
    default_res = {"raw_id": fallback_raw_id, "pref": fallback_pref}
    
    if not book_name:
        return default_res
        
    logger.info(f"🔄 [align] 开始为备用域名 '{source_domain}' 进行智能嗅探对齐 ID: 《{book_name}》 (自适应兜底: {default_res})")
    
    # 1. 尝试从 SQLite 中读取持久化缓存
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT raw_id, pref FROM aligned_ids WHERE book_name = ? AND source_domain = ?", (book_name, source_domain))
            row = cursor.fetchone()
            if row:
                logger.info(f"🎯 [align] SQLite 缓存命中 ({source_domain}): raw_id='{row[0]}', pref='{row[1]}'")
                return {"raw_id": row[0], "pref": row[1]}
    except Exception as e:
        logger.error(f"⚠️ [align] 读取 aligned_ids 缓存异常: {str(e)}")
        
    # 2. 强力直派自愈拦截分支：
    # A. 针对香书小说精准派发
    if "ibiquges" in source_domain:
        try:
            logger.info(f"🔄 [align] [direct] 正在为香书小说 '{source_domain}' 调度独立子模块检索对齐 ID: '{book_name}'")
            from sources import ibiquges
            search_results = ibiquges.crawl_search(book_name)
            for b in search_results:
                if b.get("book_name", "").strip() == book_name:
                    b_id = b.get("book_id", "")
                    if b_id.startswith("xs_"):
                        parts = b_id.replace("xs_", "").split("_")
                        if len(parts) == 2:
                            raw_id = parts[1]
                            pref = parts[0]
                            logger.info(f"🎯 [align] [direct] 香书小说独立子模块对齐成功: raw_id='{raw_id}', pref='{pref}'")
                            # 写入 SQLite 缓存
                            try:
                                with sqlite3.connect(DB_FILE) as conn:
                                    cursor = conn.cursor()
                                    cursor.execute(
                                        "INSERT OR REPLACE INTO aligned_ids (book_name, source_domain, raw_id, pref) VALUES (?, ?, ?, ?)",
                                        (book_name, source_domain, raw_id, pref)
                                    )
                                    conn.commit()
                            except Exception as db_err:
                                logger.error(f"⚠️ [align] 写入对齐缓存表异常: {db_err}")
                            return {"raw_id": raw_id, "pref": pref}
        except Exception as align_err:
            logger.warning(f"⚠️ [align] [direct] 调度香书小说对齐发生异常: {str(align_err)}")

    # B. 针对 69书吧精准派发
    elif "69shuba" in source_domain:
        try:
            logger.info(f"🔄 [align] [direct] 正在为 69书吧 '{source_domain}' 调度独立子模块检索对齐 ID: '{book_name}'")
            from sources import shuba69
            search_results = shuba69.crawl_search(book_name)
            for b in search_results:
                if b.get("book_name", "").strip() == book_name:
                    b_id = b.get("book_id", "")
                    if b_id.startswith("69_"):
                        raw_id = b_id.replace("69_", "")
                        pref = "0"
                        logger.info(f"🎯 [align] [direct] 69书吧独立子模块对齐成功: raw_id='{raw_id}', pref='{pref}'")
                        # 写入 SQLite 缓存
                        try:
                            with sqlite3.connect(DB_FILE) as conn:
                                cursor = conn.cursor()
                                cursor.execute(
                                    "INSERT OR REPLACE INTO aligned_ids (book_name, source_domain, raw_id, pref) VALUES (?, ?, ?, ?)",
                                    (book_name, source_domain, raw_id, pref)
                                )
                                conn.commit()
                        except Exception as db_err:
                            logger.error(f"⚠️ [align] 写入对齐缓存表异常: {db_err}")
                        return {"raw_id": raw_id, "pref": pref}
        except Exception as align_err:
            logger.warning(f"⚠️ [align] [direct] 调度 69书吧对齐发生异常: {str(align_err)}")

    # 3. 从 sources.json 获取该域名对应的 chapterPageUrl 正则匹配模板
    id_regex = r'/book/(?P<raw_id>\d+)/' # 默认
    chapter_page_url_tpl = ""
    for res in EXTERNAL_RESOURCES:
        if res.get("sourceName", "").lower() == source_domain or source_domain in res.get("sourceName", "").lower():
            chapter_page_url_tpl = res.get("chapterPageUrl", "")
            break
            
    if chapter_page_url_tpl:
        # 将 chapterPageUrl 转换为用于提取 ID 的正则表达式
        # 比如 `{gateway_url}/proxy/www.43kanshu.com/book/{raw_id}/` -> `book/(?P<raw_id>\d+)/`
        path_part = chapter_page_url_tpl
        if "/proxy/" in path_part:
            path_part = path_part.split("/proxy/")[1]
            path_part = "/".join(path_part.split("/")[1:]) # 去掉域名部分，保留相对路径部分
        
        # 将 {raw_id} 和 {pref} 转换为正则捕获组
        regex_str = re.escape(path_part)
        regex_str = regex_str.replace(r'\{raw_id\}', r'(?P<raw_id>\d+)').replace(r'\{pref\}', r'(?P<pref>\d+)')
        # 兼容可能有斜杠或无斜杠
        regex_str = regex_str.replace(r'\/', r'*(?:/)?')
        id_regex = regex_str
        logger.info(f"🔍 [align] 根据配置模板自适应编译出 ID 提取正则表达式: '{id_regex}'")

    session = get_secure_session()
    # 禁用系统代理防 CF IP 阻断 400
    session.trust_env = False
    session.proxies = {"http": None, "https": None}
    
    # 杰奇/笔趣阁系统经典搜索路由和参数类型列表
    search_paths = [
        # (搜索路径, 参数名, 是否强转 GBK)
        ("/modules/article/search.php", "searchkey", True),
        ("/search.php", "searchkey", True),
        ("/search.php", "keyword", True),
        ("/search.php", "searchkey", False),
        ("/search.php", "keyword", False),
        ("/s.php", "q", False),
        ("/s", "q", False),
        ("/search.html", "searchkey", True),
    ]
    
    for path, param_name, force_gbk in search_paths:
        try:
            encoding = "gbk" if force_gbk else "utf-8"
            try:
                quoted_keyword = urllib.parse.quote(book_name, encoding=encoding)
            except Exception:
                continue
                
            search_url = f"https://{source_domain}{path}?{param_name}={quoted_keyword}"
            logger.info(f"🕸️ [align] 尝试通用嗅探搜索: {search_url} (编码: {encoding})")
            
            # 注入高级伪装请求头以成功绕过 43看书网等站点的 WAF 403 阻断防护
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": f"https://{source_domain}/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
            }
            
            response = session.get(search_url, headers=headers, timeout=6, allow_redirects=True)
            
            if response.status_code == 200:
                # 检查是否直接 302 到了小说详情页
                final_url = str(response.url)
                logger.info(f"🕸️ [align] 搜索请求最终响应 URL: {final_url}")
                
                match = re.search(id_regex, final_url)
                if match:
                    groups = match.groupdict()
                    raw_id = groups.get("raw_id", "")
                    pref = groups.get("pref", "0")
                    if raw_id:
                        logger.info(f"🎯 [align] 通过 302 重定向成功精准对齐 ID! raw_id='{raw_id}', pref='{pref}'")
                        # 写入 SQLite
                        try:
                            with sqlite3.connect(DB_FILE) as conn:
                                cursor = conn.cursor()
                                cursor.execute(
                                    "INSERT OR REPLACE INTO aligned_ids (book_name, source_domain, raw_id, pref) VALUES (?, ?, ?, ?)",
                                    (book_name, source_domain, raw_id, pref)
                                )
                                conn.commit()
                        except Exception as db_err:
                            logger.error(f"⚠️ [align] 写入对齐缓存表异常: {db_err}")
                        return {"raw_id": raw_id, "pref": pref}
                
                # 如果没有重定向，而是在页面中返回了列表超链接，自动匹配
                content_type = response.headers.get("Content-Type", "").lower()
                if "gbk" in content_type or "gb2312" in content_type:
                    response.encoding = "gbk"
                else:
                    response.encoding = "utf-8"
                
                html = response.text
                # 匹配所有常规 <a> 超链接
                links = re.findall(r'href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>', html, re.I)
                for href, text in links:
                    text_clean = text.strip().replace(" ", "").lower()
                    book_name_clean = book_name.replace(" ", "").lower()
                    if book_name_clean in text_clean or text_clean in book_name_clean:
                        match = re.search(id_regex, href)
                        if match:
                            groups = match.groupdict()
                            raw_id = groups.get("raw_id", "")
                            pref = groups.get("pref", "0")
                            if raw_id:
                                logger.info(f"🎯 [align] 通过列表 HTML 超链接分析成功对齐 ID! href='{href}', raw_id='{raw_id}', pref='{pref}'")
                                # 写入 SQLite
                                try:
                                    with sqlite3.connect(DB_FILE) as conn:
                                        cursor = conn.cursor()
                                        cursor.execute(
                                            "INSERT OR REPLACE INTO aligned_ids (book_name, source_domain, raw_id, pref) VALUES (?, ?, ?, ?)",
                                            (book_name, source_domain, raw_id, pref)
                                        )
                                        conn.commit()
                                except Exception as db_err:
                                    logger.error(f"⚠️ [align] 写入对齐缓存表异常: {db_err}")
                                return {"raw_id": raw_id, "pref": pref}
            else:
                logger.warning(f"⚠️ [align] 搜索响应状态码不正确: {response.status_code}")
        except Exception as ex:
            logger.warning(f"⚠️ [align] 尝试嗅探路径 {path} 发生异常: {str(ex)[:100]}")
            
    logger.warning(f"⚠️ [align] 通用嗅探无法搜寻到 {source_domain} 上《{book_name}》的真实 ID，启动自适应主源原生兜底防护。")
    return default_res


@app.get("/proxy/{source_domain}/{path:path}")
async def unified_proxy(source_domain: str, path: str, request: Request):
    """
    十、 核心 API：通用云端代理、防爬盾拦截重写网关与“服务端自解析纯净化”重构 (全新免网关接口版本)
    通过云端 Pro 级 Session 在服务器端 100% 破解 JS 盾与 WAF 防御，并服务端自获取网页真实目录的 div 块，
    在服务端精准将所有符合章节超链接规则的相对 href 重写替换为指向我们原生 getRealContent 正文接口的相对根超链接（格式为 href="/api.php/Book/getRealContent?url=真实绝对URL"），
    并把处理后但保留了原网页完美 div 结构和排版的 HTML 吐给客户端，从根本上兼顾了“原网页匹配”与“直连接口绝对稳定”的超级闭环。
    """
    import re
    import urllib.parse
    from urllib.parse import urljoin
    
    query_params = dict(request.query_params)
    real_book_name = query_params.get("real_book_name", "").strip()
    real_book_author = query_params.get("real_book_author", "").strip()
    
    # 剥离自建 Query 参数，防止原站解析错误
    filtered_params = {k: v for k, v in query_params.items() if k not in ["real_book_name", "real_book_author"]}
    query_str = urllib.parse.urlencode(filtered_params) if filtered_params else ""
    
    # A. 开启多源 ID 实时自愈拦截
    if real_book_name:
        aligned = find_aligned_id(source_domain, real_book_name, path)
        aligned_raw_id = aligned["raw_id"]
        aligned_pref = aligned["pref"]
        
        logger.info(f"🔄 [proxy] 正在对请求 path 执行 ID 替换自愈: 原始 path='{path}', 正确对齐 ID='{aligned_raw_id}'(pref={aligned_pref})")
        
        # 识别并强行自愈替换 path 里的数字 ID
        if "_" in path:
            path = re.sub(r'\d+_\d+', f"{aligned_pref}_{aligned_raw_id}", path)
        else:
            numbers = re.findall(r'\d+', path)
            if len(numbers) >= 2:
                path = path.replace(numbers[-1], aligned_raw_id).replace(numbers[-2], aligned_pref)
            elif len(numbers) == 1:
                path = path.replace(numbers[0], aligned_raw_id)
                
        logger.info(f"🎯 [proxy] 自愈替换完成: 自愈后 path='{path}'")

    # 构建原站真实目录绝对 URL (物理擦除 /book/ 顶点前缀)
    raw_path = path
    if "ddyueshu.com" in source_domain and raw_path.startswith("book/"):
        raw_path = raw_path.replace("book/", "")
        
    target_url = f"https://{source_domain}/{raw_path}"
    if query_str:
        target_url += f"?{query_str}"
        
    logger.info(f"🕸️ [proxy] 代理拦截并破盾自愈抓取: {target_url}")
    
    session = sources_manager.get_secure_session()
    # 禁用系统代理防 CF IP 阻断 400
    session.trust_env = False
    session.proxies = {"http": None, "https": None}
    
    try:
        response = session.get(target_url, timeout=10, verify=False)
        
        content_type = response.headers.get("Content-Type", "").lower()
        if "gb2312" in content_type or "gbk" in content_type:
            response.encoding = 'gbk'
        else:
            response.encoding = 'utf-8'
            
        html = response.text
        
        final_url = str(response.url)
        final_domain_match = re.search(r'https?://([^/]+)', final_url)
        final_domain = final_domain_match.group(1) if final_domain_match else source_domain
        
        # B. 服务端自解析高保真重写：如果不是以 html 结尾的章节页，则认定为目录页！
        if not path.endswith((".html", ".htm")):
            logger.info(f"📝 [proxy] 检测到目录页响应，启动“服务端自解析真实 div + href 原位替换”重构流程")
            
            # 1. 动态加载该源在 sources.json 中的提取规则
            chapter_beat_regex = ""
            chapter_url_regex = 'href\\s*=\\s*["\']((?!https?:)[^"\']*(?:/)?\\d+\\.html?)["\']' # 默认
            
            for res in EXTERNAL_RESOURCES:
                if res.get("sourceName", "").lower() == source_domain or source_domain in res.get("sourceName", "").lower():
                    chapter_beat_regex = res.get("chapterPageBeat", {}).get("rule", "")
                    chapter_url_regex = res.get("chapterUrl", {}).get("rule", chapter_url_regex)
                    break
            
            # 2. 精准获取网页真实的目录 div 块
            cont = html
            if chapter_beat_regex:
                try:
                    beat_match = re.search(chapter_beat_regex, html, re.I | re.S)
                    if beat_match:
                        # 仅保留包含章节超链接的真实目录 div 部分，实现原汁原味的排版和过滤
                        cont = beat_match.group(1)
                except Exception as e:
                    logger.warning(f"⚠️ [proxy] chapterPageBeat 过滤块正则运行失败: {e}")
            
            # 3. 在服务端对真实 div 中的章节相对超链接执行 href 高保真精准原位替换
            # 定义超链接 href 精准替换函数，排除绝对外链，仅替换符合章节正则的相对链接
            def replace_href(match):
                raw_href = match.group(1).strip()
                if raw_href.startswith(("http://", "https://", "javascript:", "#")):
                    return match.group(0)
                
                # 重新包装为 href="xxx" 格式以完美契合 chapter_url_regex 对完整属性标签的匹配校验
                test_str = f'href="{raw_href}"'
                if re.search(chapter_url_regex, test_str):
                    real_abs_url = urljoin(target_url, raw_href)
                    encoded_url = urllib.parse.quote(real_abs_url)
                    # 替换为以斜杠开头、免代理中转直接指向核心正文接口的根相对路径格式！
                    return f'href="/api.php/Book/getRealContent?url={encoded_url}"'
                
                return match.group(0)
            
            # 执行高保真精准超链接原位替换
            try:
                # 匹配所有超链接中的 href 属性进行原位替换
                rewritten_div = re.sub(r'href\s*=\s*["\']([^"\']+)["\']', replace_href, cont)
                
                # 返回保留了原站排版与 div、且重写了 href 章节超链接的 HTML 页面
                final_toc_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>TOC - Aligned</title>
</head>
<body>
    {rewritten_div}
</body>
</html>"""
                logger.info("✅ 真实目录 div 章节超链接高保真 href 替换完成！成功交付！")
                return HTMLResponse(content=final_toc_html, status_code=200)
            except Exception as parse_err:
                logger.error(f"❌ 真实目录 div 章节重写替换失败: {parse_err}，自动降级为安全气囊逻辑")
                
            # C. 降级安全气囊：如果自解析失败，自动执行 Response Rewriting 兜底
            logger.info(f"📝 [proxy] 启动绝对 URL 智能重写，重定向域名: {final_domain}")
            gateway_base = f"/proxy/{final_domain}/"
            
            # 替换带域名的绝对链接
            html = re.sub(
                rf'href\s*=\s*["\']https?://{final_domain}/([^"\']+)["\']',
                rf'href="{gateway_base}\1"',
                html
            )
            if final_domain != source_domain:
                html = re.sub(
                    rf'href\s*=\s*["\']https?://{source_domain}/([^"\']+)["\']',
                    rf'href="{gateway_base}\1"',
                    html
                )
                
            # 兼容其他可能绝对章节链接
            html = re.sub(
                r'href\s*=\s*["\'](https?://[^"\']+\.(?:html|htm))["\']',
                lambda m: f'href="/proxy/{re.search(r"https?://([^/]+)", m.group(1)).group(1)}/{re.search(r"https?://[^/]+/(.+)", m.group(1)).group(1)}"',
                html
            )
            
        return HTMLResponse(content=html, status_code=200)
    except Exception as e:
        logger.error(f"❌ [proxy] 代理抓取发生严重异常: {str(e)}")
        return HTMLResponse(content=f"API Gateway Proxy Error: {str(e)}", status_code=500)


if __name__ == "__main__":
    import uvicorn
    # 在局域网 0.0.0.0 上监听 8000 端口启动
    uvicorn.run(app, host="0.0.0.0", port=8000)
