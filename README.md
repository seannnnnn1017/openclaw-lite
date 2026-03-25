# OpenClaw Lite

Telegram note: standard Telegram chats now include `[SYSTEM]` and `[TOOL]` trace lines before the final answer.
Scheduled-task note: when Telegram delivery targets are known, scheduled task output is sent to both the terminal and Telegram.

OpenClaw Lite 是一個在 terminal 中運作的本地 agent。它透過 OpenAI-compatible chat API 與模型對話，並把檔案操作、排程、時間查詢等能力委派給 FastAPI skill server。

目前系統已支援：
- 多步 tool-use
- prompt / skill / config 熱重載
- agent-native 排程
- terminal 顯示分類：`[THINK]`、`[TOOL]`、`[SYSTEM]`
- CLI 指令管理：model、cache、task、status

## 架構概覽

- `agent/main.py`
  Terminal 入口、slash commands、scheduler 啟動點
- `agent/agent.py`
  LLM 對話主循環、tool JSON 解析、多步 skill 執行
- `agent/skill_server.py`
  FastAPI skill server，負責接收與執行 skill
- `agent/skill_runtime.py`
  skill registry 與 tool loader
- `agent/config_loader.py`
  載入 `config.json`、prompts、SKILL docs
- `agent/terminal_display.py`
  統一處理 `[THINK]`、`[TOOL]`、`[SYSTEM]`、`Agent:`、`[COMMAND]`
- `agent/chat_scheduler.py`
  背景輪詢到期任務
- `agent/schedule_runtime.py`
  排程 registry、到期判斷、dispatch metadata
- `agent/telegram_bridge.py`
  Telegram Bot API long polling bridge，負責收送訊息與 chat session 管理
- `agent/data/system/system_architecture.md`
  啟動時自動生成的系統總覽

## Prompt Layers

系統 prompt 由下列檔案組成：
- `agent/prompts/identity.md`
- `agent/prompts/system_rules.md`
- `agent/prompts/boundaries.md`
- 所有啟用中的 `agent/SKILLs/*/SKILL.md`

## 目前 Skills

### 1. `file-control`

用途：
- 讀檔
- 建立檔案
- 覆寫內容
- 追加內容
- 刪除檔案
- 定點文字替換
- 插入文字
- 還原備份

支援 action：
- `read`
- `create`
- `write`
- `append`
- `delete`
- `replace_text`
- `insert_after`
- `insert_before`
- `restore`

備份機制：
- 所有修改型操作都會先建立備份
- 備份索引：`agent/SKILLs/file_control/scripts/temporary_data/file_ID.json`
- 備份檔：`agent/SKILLs/file_control/scripts/temporary_data/backups/`
- 可用 `backup_id` 搭配 `restore` 還原

硬限制：
- `file-control` 不能修改自己的備份儲存區
- 如果 AI 嘗試對 `temporary_data/` 做 `create/write/append/delete/replace/insert`，工具會直接回傳 `Permission denied`
- 備份儲存區不屬於一般 file-control 編輯範圍

### 2. `schedule-task`

這是 agent-native scheduler，不是 Windows Task Scheduler。

用途：
- 建立定時任務
- 查詢任務
- 列出任務
- 立即排入執行
- 啟用 / 停用
- 刪除

支援 action：
- `create`
- `get`
- `list`
- `run`
- `enable`
- `disable`
- `delete`

支援排程類型：
- `once`
- `daily`
- `weekly`
- `minute`
- `hourly`

運作方式：
1. skill 只儲存排程時間與 `task_prompt`
2. 到時間後 `chat_scheduler.py` claim 任務
3. scheduler 把 `task_prompt` 丟回 agent
4. agent 再自行決定要不要呼叫 `file-control` 或其他 skill

限制：
- 只有 agent 開著時任務才會跑
- agent 關閉時不會像系統排程一樣持續執行

任務 registry：
- `agent/SKILLs/schedule_task/scripts/temporary_data/task_registry.json`

### 3. `time-query`

用途：
- 查現在時間 / 日期
- 查指定時區目前時間
- 一次比較多個時區
- 把明確時間從一個時區轉到另一個時區

支援 action：
- `now`
- `convert`

支援：
- IANA timezone，例如 `Asia/Taipei`、`UTC`、`America/New_York`
- 常見別名，例如 `Taipei`、`Tokyo`、`New York`
- 明確 UTC offset，例如 `+08:00`

## Telegram Bridge

系統現在可直接連 Telegram Bot API。

運作方式：
1. `telegram_bridge.py` 用 long polling 呼叫 `getUpdates`
2. 收到文字訊息後，依 `chat_id` 建立或重用一個獨立 `SimpleAgent` session
3. 如果訊息是 slash command，就走同一套 command handler
4. 如果是一般文字，就交給 `agent.run(...)`
5. 回覆再用 `sendMessage` 傳回 Telegram

特性：
- 每個 Telegram chat 有獨立 history，不會直接和 terminal session 混在一起
- Telegram 端不允許用 `/exit` 遠端關閉整個 agent
- 支援長訊息自動分段
- 支援 state file，避免重啟後重複處理同一批 update
- 可用 allowlist 限制 `chat_id` 或 `username`

建議：
- 如果 bot 不是私用，請設定 `allowed_chat_ids` 或 `allowed_usernames`
- 如果 token 曾經進過公開 repo，應立即到 BotFather 旋轉 token

## CLI Commands

目前內建指令如下：

```text
/help
/exit | /quit
/model [name]
  reset
  save <name>
/clear <history|cache>
  history
  cache
/task
  list
  remove <id|name>
  remove -all
/think [on|off]
/reload
/status
```

指令說明：
- `/help`
  顯示指令總覽
- `/exit`、`/quit`
  結束 agent
- `/model`
  顯示目前 model
- `/model <name>`
  只切換本次 session 的 model
- `/model reset`
  還原成 `config.json` 的預設 model
- `/model save <name>`
  永久寫回 `agent/config/config.json`
- `/clear history`
  清空本次 session 的 in-memory chat history
- `/clear cache`
  只刪除快取目錄：
  - `/.codex-temp`
  - `/agent/.codex-temp`
- `/task list`
  直接列出目前排程任務
- `/task remove <id|name>`
  直接刪除一個排程任務
- `/task remove -all`
  直接刪除全部排程任務
- `/think`
  顯示目前 `[THINK]` 設定
- `/think on`
  顯示 `[THINK n]`
- `/think off`
  隱藏 `[THINK n]`
- `/reload`
  重載 config / prompts / skills / runtime clients
- `/status`
  顯示 model、history size、display categories、endpoint URLs

補充：
- `/task ...` 是直接操作排程 registry，不需要經過 LLM
- `/clear cache` 不會刪排程任務
- `/clear cache` 不會刪 `file-control` 備份
- Telegram 訊息也可以使用 `/task`、`/model`、`/status` 等指令

## Terminal 輸出格式

目前 terminal 會顯示：
- `[THINK n]`
- `[TOOL] step=n note: ...`
- `[TOOL] step=n call: ...`
- `[TOOL] step=n result: ...`
- `[SYSTEM] ...`
- `Agent: ...`
- `[COMMAND] ...`

多行 `Agent:` 與 `[COMMAND]` 輸出只會在第一行顯示前綴，後續行改成縮排，避免每行重複標頭。

## 一般執行流程

1. 使用者在 terminal 輸入文字
2. `main.py` 先判斷是不是 slash command
3. 若不是 command，交給 `SimpleAgent.run(...)`
4. agent 用 prompts + SKILL docs 組 system prompt
5. LLM 可能：
   - 直接回答
   - 回傳一個 skill JSON
6. 若回傳 skill JSON：
   - agent 送到 skill server
   - skill server 執行 tool
   - 結果回給 agent
   - agent 持續推理直到輸出最終回答

## 排程流程

1. 使用者建立 `schedule-task`
2. `schedule_runtime.py` 寫入 registry
3. `chat_scheduler.py` 背景輪詢到期任務
4. 到期後產生 dispatch event
5. `main.py` 收到 event 後呼叫 `agent.run(dispatch_prompt)`
6. agent 依照 `task_prompt` 完成任務
7. 結果顯示在聊天室，並寫回任務執行狀態

## 安裝需求

建議環境：
- Windows PowerShell
- Python 3.10+
- 一個 OpenAI-compatible chat endpoint，例如 LM Studio

Python 套件：
- `openai`
- `fastapi`
- `uvicorn`
- `pydantic`

安裝範例：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install openai fastapi uvicorn pydantic
```

## 啟動方式

Terminal 1: 啟動 skill server

```powershell
.venv\Scripts\Activate.ps1
python agent\skill_server.py
```

Terminal 2: 啟動 agent

```powershell
.venv\Scripts\Activate.ps1
python agent\main.py
```

## 設定檔

主要設定檔：
- `agent/config/config.json`
- `agent/data/system/secrets.example.json`
- `agent/data/system/secrets.local.json` (git ignored)

## Secret Management

- Keep secrets in `agent/data/system/secrets.local.json` or environment variables.
- `secrets.local.json` is the shared location for the LLM API key, Telegram bot token, and Notion API key.
- Environment variables override the local secret file.
- Supported environment variables:
  - `OPENCLAW_LLM_API_KEY`
  - `OPENCLAW_TELEGRAM_BOT_TOKEN`
  - `OPENCLAW_NOTION_API_KEY`
  - `OPENCLAW_NOTION_PARENT_PAGE_ID`
  - `OPENCLAW_NOTION_PARENT_PAGE_URL`
  - `OPENCLAW_NOTION_VERSION`
- Keep tracked config files non-secret. `agent/config/config.json` should only store ordinary runtime settings.

目前欄位：
- `llm.base_url`
- `llm.api_key` (prefer `secrets.local.json` or `OPENCLAW_LLM_API_KEY`)
- `llm.model`
- `llm.temperature`
- `llm.max_tokens`
- `skill_server.base_url`
- `telegram.enabled`
- `telegram.bot_token` (prefer `secrets.local.json` or `OPENCLAW_TELEGRAM_BOT_TOKEN`)
- `telegram.poll_timeout_seconds`
- `telegram.retry_delay_seconds`
- `telegram.skip_pending_updates_on_start`
- `telegram.allowed_chat_ids`
- `telegram.allowed_usernames`
- `telegram.state_path`
- `prompt_paths.identity`
- `prompt_paths.system_rules`
- `prompt_paths.boundaries`

目前預設值：
- LLM API: `http://localhost:1234/v1`
- Skill Server: `http://127.0.0.1:8001`

## 重要資料位置

- `agent/SKILLs/file_control/scripts/temporary_data/file_ID.json`
  file-control 備份索引
- `agent/SKILLs/file_control/scripts/temporary_data/backups/`
  file-control 備份檔
- `agent/SKILLs/schedule_task/scripts/temporary_data/task_registry.json`
  正式排程 registry
- `agent/data/system/telegram_bridge_state.json`
  Telegram update offset state
- `.codex-temp/`
  專案根目錄快取
- `agent/.codex-temp/`
  agent 子目錄快取 / 測試沙盒
- `agent/data/system/system_architecture.md`
  啟動時自動生成的系統總覽

## 使用範例

一般對話：

```text
You: 幫我讀 README.md
```

建立排程：

```text
You: 每小時新增一個當前時間的 txt
```

管理排程：

```text
You: /task list
You: /task remove noodle-reminder
You: /task remove -all
```

Telegram：

```text
Telegram -> 直接傳訊息給 bot
/status
/task list
台北現在幾點
幫我讀 README.md
```

查時間：

```text
You: 台北現在幾點
You: 幫我比較台北、東京、紐約現在時間
You: 把 2026-03-24 14:30 的台北時間換成 UTC
```

## 目前限制

- scheduler 只在 agent 執行中有效
- agent 每一步只期望一個 tool JSON object
- 某些模型在長 history 下仍可能變不穩
- `file-control` 備份儲存區不可由一般 skill 修改
- Telegram bridge 目前只處理文字訊息

## 補充

如果要找系統整體檔案分布，先看：
- `agent/data/system/system_architecture.md`
