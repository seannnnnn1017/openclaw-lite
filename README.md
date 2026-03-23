# OpenClaw Lite

OpenClaw Lite 是一個在 terminal 中運行的本地 agent。它使用 OpenAI-compatible chat API
作為 LLM 後端，並透過獨立的 skill server 執行本地工具，現在已內建：

- 一般對話與多輪 tool-use
- 檔案讀寫 / 定點文字修改 / 備份還原
- agent 內建排程任務
- CLI slash commands
- prompt / skill / config 熱重載
- 啟動時自動產生系統架構摘要

## 目前功能

### 1. Terminal agent

- 入口在 `agent/main.py`
- 使用者在 terminal 輸入自然語言，agent 會回覆結果
- agent 會在回合內自行決定是否直接回答，或改用 skill
- 支援多步 tool loop，不是只能呼叫一次工具

### 2. Prompt layers

系統 prompt 由這幾層組成：

- `agent/prompts/identity.md`
- `agent/prompts/system_rules.md`
- `agent/prompts/boundaries.md`
- 所有已啟用技能的 `SKILL.md`

agent 每次執行前都會檢查這些檔案是否被修改，若有變更會自動 reload。

### 3. Skill server

- skill server 是獨立的 FastAPI 服務，入口在 `agent/skill_server.py`
- agent 不是直接改檔，而是把 skill JSON 送到 skill server
- skill server 依照 `skills_config.json` 載入工具模組並執行

目前已啟用技能：

- `file-control`
- `schedule-task`

### 4. File control skill

`file-control` 用來做本地檔案操作，支援：

- `read`
- `create`
- `write`
- `append`
- `delete`
- `replace_text`
- `insert_after`
- `insert_before`
- `restore`

特性：

- 所有修改型操作都會先備份
- 備份索引存放在 `agent/SKILLs/file_control/scripts/temporary_data/file_ID.json`
- 備份檔存放在 `agent/SKILLs/file_control/scripts/temporary_data/backups/`

### 5. Schedule task skill

`schedule-task` 是 agent-native 排程，不是 Windows Task Scheduler。

支援：

- `create`
- `get`
- `list`
- `run`
- `enable`
- `disable`
- `delete`

排程類型：

- `once`
- `daily`
- `weekly`
- `minute`
- `hourly`

目前邏輯不是「到點直接跑 shell command」，而是：

1. skill 儲存時間設定與 `task_prompt`
2. background scheduler 定期檢查到期任務
3. 到點後把該 `task_prompt` 丟回 agent
4. agent 自己決定是否呼叫 `file-control` 或其他 skill
5. 執行結果顯示在聊天室，並回寫到 registry

限制：

- 只有 agent 開著時才會執行
- 關閉 agent 後不會在背景繼續跑
- 重開 agent 後，若 registry 還在，排程會依 `next_run_at` 繼續
- `/clear cache` 會重置排程 registry，所以會清掉已儲存的排程任務

排程 registry 位置：

- `agent/SKILLs/schedule_task/scripts/temporary_data/task_registry.json`

### 6. CLI commands

目前 terminal 內建 slash commands：

```text
/help
/exit
/quit
/model
/model <name>
/model reset
/model save <name>
/clear
/clear history
/clear cache
/think
/think on
/think off
/reload
/status
```

說明：

- `/help`: 顯示指令清單
- `/exit`, `/quit`: 結束 agent
- `/model`: 顯示目前使用中的 model
- `/model <name>`: 只切換本次 session 的 model
- `/model reset`: 回到 `config.json` 中的預設 model
- `/model save <name>`: 直接更新 `agent/config/config.json` 的 `llm.model`
- `/clear`: 顯示 `clear` 子命令用法
- `/clear history`: 清除 in-memory 對話歷史
- `/clear cache`: 刪除 `.codex-temp` 並重置 `schedule-task` 的暫存資料，會清空排程 registry
- `/think`: 顯示目前 `[THINK]` 輸出狀態與子命令用法
- `/think on`: 顯示 `[THINK n]` 輸出
- `/think off`: 關閉 `[THINK n]` 輸出
- `/reload`: 重新載入 config / prompts / skills，並刷新 runtime clients
- `/status`: 顯示目前 model、history 長度、`[THINK]` 狀態、LLM URL、skill server URL

注意：

- `/clear cache` 會清掉 `.codex-temp`，並重置排程 registry
- `/clear cache` 不會清 file-control 的備份資料
- 一般文字輸入會送進 agent；只有 `/...` 才會先被 CLI 命令層攔截

## 執行邏輯

### 一般對話流程

1. 使用者在 terminal 輸入內容
2. `main.py` 先判斷是不是 slash command
3. 若不是 command，就交給 `SimpleAgent.run(...)`
4. agent 組合 system prompt 與近期 history
5. LLM 可以：
   - 直接回答
   - 回傳一個 skill JSON
6. 若是 skill JSON：
   - agent 把請求送到 skill server
   - skill server 執行工具
   - 結果再回餵給 agent 繼續推理
7. 直到 agent 產生最終自然語言回答

### 排程流程

1. 使用者建立 `schedule-task`
2. `schedule_runtime.py` 把任務寫入 registry
3. `chat_scheduler.py` 在背景 thread 輪詢到期任務
4. 到期後產生 dispatch event
5. `main.py` 收到 event，呼叫 `agent.run(dispatch_prompt)`
6. agent 執行該任務
7. 結果顯示在 terminal，並寫回排程紀錄

## 主要檔案

```text
agent/main.py                 Terminal entrypoint + slash commands + scheduler startup
agent/agent.py                Agent 主推理迴圈、多步 tool-use、history 管理
agent/config_loader.py        載入 config / prompts / skills，支援 reload
agent/lmstudio_client.py      LLM client
agent/skill_server.py         FastAPI skill server
agent/skill_runtime.py        skill registry / dynamic loader
agent/chat_scheduler.py       背景排程輪詢器
agent/schedule_runtime.py     排程 registry / next-run 計算 / dispatch metadata
agent/data/system/system_architecture.md
                              啟動時自動生成的系統架構摘要
```

## 安裝需求

建議環境：

- Windows PowerShell
- Python 3.10+
- LM Studio 或其他 OpenAI-compatible chat endpoint

至少需要的 Python 套件：

- `openai`
- `fastapi`
- `uvicorn`
- `pydantic`

PowerShell 範例：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install openai fastapi uvicorn pydantic
```

## 啟動方式

### Terminal 1: skill server

```powershell
.venv\Scripts\Activate.ps1
python agent\skill_server.py
```

### Terminal 2: agent

```powershell
.venv\Scripts\Activate.ps1
python agent\main.py
```

## 基本使用

### 一般對話

```text
You: 幫我讀 README.md
```

### 檔案操作

直接用自然語言要求即可，agent 會自行決定是否使用 `file-control`。

### 建立排程

```text
You: 每小時新增一個當前時間的.txt
```

若排程建立成功，之後到時間時會在聊天室看到排程觸發訊息與執行結果。

### 查詢 CLI 狀態

```text
You: /status
You: /model
You: /help
```

## 設定檔

主設定檔：

- `agent/config/config.json`

目前主要欄位：

- `llm.base_url`: LLM API base URL
- `llm.api_key`: API key
- `llm.model`: 預設 model
- `llm.temperature`: 取樣溫度
- `llm.max_tokens`: 單次請求的 `max_tokens`
- `skill_server.base_url`: skill server URL
- `prompt_paths.identity`: identity prompt 路徑
- `prompt_paths.system_rules`: system rules 路徑
- `prompt_paths.boundaries`: boundaries prompt 路徑

model 邏輯：

- `config.json` 中的 `llm.model` 是預設 model
- `/model <name>` 只改目前 session
- `/model save <name>` 會把預設值寫回 `config.json`

## 注意事項

- `schedule-task` 不是系統層排程器；agent 沒開就不會執行
- 關閉 agent 時，正在進行中的排程任務通常也會中止
- 若刪掉 `task_registry.json`，未來排程會遺失；已經 dispatch 的當前任務不一定立刻停止
- `file-control` 的備份資料是持久化的；`/clear cache` 不會清掉它
- 啟動時會重建 `agent/data/system/system_architecture.md`

## 目前預設埠

- LLM API: `http://localhost:1234/v1`
- Skill Server: `http://127.0.0.1:8001`
