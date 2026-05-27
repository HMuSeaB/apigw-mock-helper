# 读取文件
with open(r'd:\4rchive\Code\shuyuan\shareBookSource.json', 'r', encoding='utf-8') as f:
    content = f.read()

# 使用原始字符串修复JSON转义问题
# 将 \"\"\]\,\n 替换为 \"\"\],\n
import re
content = re.sub(r'""\\]\\,', '""],', content)

# 写入修复后的文件
with open(r'd:\4rchive\Code\shuyuan\shareBookSource.json', 'w', encoding='utf-8') as f:
    f.write(content)

print("修复完成")