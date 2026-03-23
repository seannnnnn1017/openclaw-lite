# OpenClaw Lite

## 啟動前準備

- Python 3.10 以上
- 已啟動 LM Studio 本機 API Server
- LM Studio 內已載入模型，且 `agent/config/config.json` 內的 `llm.model` 與實際模型名稱一致

預設設定：

- LLM API：`http://localhost:1234/v1`
- Skill Server：`http://127.0.0.1:8001`

## 安裝依賴

建議先建立虛擬環境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install openai fastapi uvicorn pydantic
```

## 啟動方式

請在專案根目錄開兩個 terminal。

### Terminal 1：啟動 Skill Server

```bash
source .venv/bin/activate
python3 agent/skill_server.py
```

### Terminal 2：啟動 Agent

```bash
source .venv/bin/activate
python3 agent/main.py
```

啟動後可直接在終端輸入訊息，例如：

```text
You: 幫我讀取 README.md
```

輸入 `exit` 或 `quit` 可結束程式。

## 設定檔

設定檔位置：

```text
agent/config/config.json
```

可依需求調整：

- `llm.base_url`：LM Studio API 位址
- `llm.api_key`：LLM API 金鑰
- `llm.model`：模型名稱
- `llm.temperature`：生成溫度
- `llm.max_tokens`：輸出 token 上限
- `skill_server.base_url`：Skill Server 位址
