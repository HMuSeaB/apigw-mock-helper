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
from fastapi.responses import JSONResponse

from sources import manager as sources_manager
from sources.utils import aes_encrypt_base64

# 1. 基础配置与日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="apigw-mock-helper-api")
DB_FILE = os.path.join(os.path.dirname(__file__), "legado.db")

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
            conn.commit()
            logger.info("SQLite 数据库初始化及建表成功。")
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
    二、 书籍详情 API (提供实时原站信息匹配与备用换源指引拼装)
    """
    try:
        body = await request.json()
        book_id = str(body.get("bookId", "69_43977")).strip()
        logger.info(f"🔔 详情页获取: bookId={book_id}")
        
        # 调度模块层获取各大源站的真实图书数据 (书名、作者、封面与简介)
        book_detail = sources_manager.get_book_info(book_id)
        
        book_name = book_detail["book_name"]
        book_author = book_detail["book_author"]
        book_pic = book_detail["book_pic"]
        book_intro = book_detail["book_intro"]
        latest_ch = book_detail["latest_ch"]

        # 将 18 个镜像站的配置指引动态格式化并追加到简介尾部，展现真实小说的最新状态！
        try:
            formatted_intro = MULTISOURCE_INTRO.format(latest_ch=latest_ch)
        except Exception:
            formatted_intro = MULTISOURCE_INTRO
        
        book_intro += formatted_intro
        
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
                    "categoryName": "实时云聚合"
                }
            }
        })
    except Exception as e:
        logger.error(f"详情接口内部出错: {str(e)}")
        return JSONResponse(status_code=500, content={"msg": str(e), "code": -1})


@app.post("/api.php/Book/getResources")
async def get_resources(request: Request):
    """
    三、 核心 API：获取书籍的实时目录并对其下发 AES-128-CBC 加密包
    客户端 ruleToc.chapterList 会读取 $.data.chapters，
    章节名称 ruleToc.chapterName 会配合本地 Rhino 用密码 Pxga!h*e4@T8xfOm 解密章节名字。
    """
    try:
        body = await request.json()
        book_id = str(body.get("bookId", "69_43977")).strip()
        logger.info(f"🔔 实时目录抓取与AES加密: bookId={book_id}")
        
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
            
        # 2. 从本地加载并格式化 18 个全网最强小说镜像源
        resources_list = []
        for res in EXTERNAL_RESOURCES:
            res_copy = dict(res)
            try:
                # 动态填充 URL 中的占位符
                res_copy["chapterPageUrl"] = res.get("chapterPageUrl", "").format(raw_id=raw_id, pref=pref)
            except Exception:
                pass
            resources_list.append(res_copy)

        # 3. 调度爬虫获取加密后的目录结构
        chapters = sources_manager.get_chapters(book_id)
        
        return JSONResponse(content={
            "msg": "Success",
            "code": 0,
            "data": {
                "chapters": chapters,
                "resources": resources_list
            }
        })
    except Exception as e:
        logger.error(f"获取章节列表接口失败: {str(e)}")
        return JSONResponse(status_code=500, content={"msg": str(e), "code": -1})


@app.post("/api.php/Book/getRealContent")
async def get_real_content(request: Request):
    """
    四、 核心 API：实时拉取正文、广告智能净化清洗并进行云端 AES-128-CBC 加密分发
    """
    try:
        body = await request.json()
        url = body.get("url", "").strip()
        logger.info(f"🔔 实时抓取正文、净化与AES加密: URL={url}")
        
        if not url:
            return JSONResponse(content={"msg": "未指定正文链接参数", "code": -1})
            
        # 调度多源模块爬取并清洗正文
        clean_text = sources_manager.get_content(url)
        
        # 对净化后的正文文字进行 AES 加密
        encrypted_text = aes_encrypt_base64(clean_text)
        
        return JSONResponse(content={
            "msg": "Success",
            "code": 0,
            "data": {
                "content": encrypted_text
            }
        })
    except Exception as e:
        logger.error(f"正文抓取加密接口发生异常: {str(e)}")
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

        logger.info(f"用户 UID={user_id} 添加书籍 ID={book_id} 到云端书架")

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO sheets (user_id, book_id, book_name, book_author, book_pic, book_intro, toc_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, book_id, book_name, book_author, book_pic, book_intro, "")
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


if __name__ == "__main__":
    import uvicorn
    # 在局域网 0.0.0.0 上监听 8000 端口启动
    uvicorn.run(app, host="0.0.0.0", port=8000)
