# 读取文件
with open(r'd:\4rchive\Code\shuyuan\shareBookSource.json', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 在 ruleBookInfo.init 中添加书籍详情API日志
old_text1 = 'url=server  +`/api/index.php?api=content&book_id=${book_id||series_id}`\nresult=java.ajax(url)'
new_text1 = 'url=server  +`/api/index.php?api=content&book_id=${book_id||series_id}`\njava.log(\'【书籍详情API】完整URL: \' + url);\nresult=java.ajax(url)'
content = content.replace(old_text1, new_text1)

# 2. 在 ruleToc.chapterList 中添加章节列表API日志
old_text2 = 'url=server+`/api/index.php?api=book&book_id=${book_id}`\nr=JSON.parse(java.ajax(url)).data.chapterListWithVolume'
new_text2 = 'url=server+`/api/index.php?api=book&book_id=${book_id}`\njava.log(\'【章节列表API】完整URL: \' + url);\nr=JSON.parse(java.ajax(url)).data.chapterListWithVolume'
content = content.replace(old_text2, new_text2)

# 3. 在 searchUrl 中添加搜索API日志
old_text3 = 'result = base + "/api/index.php?api=search&key=" + key + "&offset={{(page-1)*10}}&tab_type=" + config.tab;\n    java.toast(config.toast);'
new_text3 = 'result = base + "/api/index.php?api=search&key=" + key + "&offset={{(page-1)*10}}&tab_type=" + config.tab;\n    java.log(\'【搜索API】完整URL: \' + result);\n    java.toast(config.toast);'
content = content.replace(old_text3, new_text3)

# 4. 在 searchUrl 中添加直接跳转日志
old_text4 = 'result = `data:;base64,${java.base64Encode(key)},{"type":"小六"}`;'
new_text4 = 'java.log(\'【搜索直接跳转】原始key: \' + key);\n    result = `data:;base64,${java.base64Encode(key)},{"type":"小六"}`;'
content = content.replace(old_text4, new_text4)

# 写入修复后的文件
with open(r'd:\4rchive\Code\shuyuan\shareBookSource.json', 'w', encoding='utf-8') as f:
    f.write(content)

print("调试日志添加完成")