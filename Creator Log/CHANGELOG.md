# 项目修改日志

本文档用于记录本项目的修改历史，包括日期、作者、改动的代码范围以及改动内容。

## 2026-08-06

- 作者：godendusk
- 改动代码：初始化项目修改日志文件 `CHANGELOG.md`
- 改动内容：
  - 新建项目修改日志，用于后续持续记录项目代码变更、修改说明与维护记录。
  - `base.html`
  确认项目应使用 `kunlun` 环境运行，修改地址为：const API_BASE = "http://127.0.0.1:8000", 通过本地运行

  - 删除空库vector_db，上传群内的测试小向量库
    "C:\Users\user\Desktop\Postgraduate\科研\industry_graph-main\report_generation\vector_db"中原有的文件是空壳，替换为微信群内的小向量库，由于gitignore文件的编写，改动不同步到github中，使用前需要自己手动将微信群内的小向量库下载，解压后放到该路径下（完整的百度网盘的向量库应该是同理，小向量库还未进行测试）