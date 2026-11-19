# 测谱 · 测试用例与报告平台

整合测试用例与各类报告，支持版本历史和用例↔报告关联。无登录，架构保持简单：FastAPI + SQLite + Vue 3。

## 本地启动

```bash
# 1. 后端依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 前端构建（产物由 FastAPI 一起托管）
cd frontend
npm install
npm run build
cd ..

# 3. 导入官方用例/报告（从 data/sources 读取；首次可运行脚本从 /workspace 拷贝）
python -m app.seed

# 4. 启动
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

浏览器打开 <http://127.0.0.1:8080>。开发时也可在 `frontend` 里执行 `npm run dev`（已代理到 8080）。

## 数据说明

- 数据库：`data/platform.db`（SQLite），存用例/报告元数据与关联结论、推演详情表格字段（链路、结果、原因、备注）和报告页头（仓库、分支、参与人、样式），以及用例文档附加信息（待确认、不测统计、用例信息）和用例评论。
- 原始 HTML / Markdown 仍放在 `data/files/`，评论图片在 `data/files/comments/`。导入或启动时解析一次写入数据库，之后用例分页与 `/api/review-detail` 按库读取，不再每次全量解析 HTML。
- 无独立 Alembic 脚本；表结构由启动时 `create_all()` 与 `migrate_schema()` 维护。
- 种子源文件在 `data/sources/`，运行时不依赖仓库外的目录。`app.seed` 会先把正式文件拷贝到此处再入库，并回填推演详情与用例文档信息。
- `data/` 下的源文件与数据库默认不进入 git（部分报告超过 4MB）。重新部署时在本机准备好 `data/sources` 后执行 `python -m app.seed`。

种子默认会重建数据库。重复运行是安全的，但会清空手工新增的数据。

## 能力范围

- 用例库：列表 / 搜索 / 过滤，详情，版本切换，关联报告。
- 报告库：列表 / 搜索 / 过滤，详情，HTML 或 Markdown 在线预览，关联用例及结果。
- 新建或编辑用例（保存为新版本）；上传 HTML/MD 导入为新版本；手动补扣关联。

不包含：权限、CI、任务调度、执行引擎。

## Docker 部署

镜像已包含前端构建产物和当前库内的用例/报告数据。GitHub 对单文件限制 100MB，镜像 tar 放在 [Releases](https://github.com/grokbot-used/test_platform/releases) 中下载。

```bash
# 加载镜像
docker load -i test_platform-0.1.4.tar

# 启动（本机 8080）
docker run --rm -p 8080:8080 test_platform:0.1.4
```

浏览器打开 <http://127.0.0.1:8080>。也可用仓库里的 `docker-compose.yml` 在有 Dockerfile 和数据的情况下重新构建：`docker compose up --build`。
