# 三層記憶系統設計

**日期**：2026-04-07  
**狀態**：待實作  
**取代**：`agent/storage/memory.py`（現有 LongTermMemoryManager + LongTermMemoryStore）

---

## 背景

現有記憶系統問題：
- Retrieval 用 token overlap 評分，準確性差
- 每 turn 跑兩次 background LLM extraction，浪費呼叫
- 單一 `skill-memory.json` 扁平存儲，無法表達話題層次
- 沒有原始對話存檔，無法回溯

新系統採三層架構，參照 Claude Code memdir 設計。

---

## 架構總覽

```
Hot   → MEMORY.md（常駐索引，每次對話注入）
Warm  → topics/*.md（按需載入，小模型選擇）
Cold  → transcripts/*.jsonl（Grep 搜索，不用 RAG）
```

---

## 檔案結構

```
agent/data/memories/
├── MEMORY.md                          # Hot 層：常駐索引
├── topics/                            # Warm 層：話題文件
│   ├── user-preferences.md
│   ├── schedule-gotchas.md
│   ├── notion-known-issues.md
│   └── ...
└── transcripts/                       # Cold 層：歷史對話
    ├── session-20260407-143022.jsonl
    ├── session-20260406-091500.jsonl
    └── ...
```

---

## Section 1：Hot 層（MEMORY.md）

### 規格
- 每次對話強制載入，注入 system prompt
- 限制：**200 行 / 25KB**，雙保險
- 截斷策略：在最後一個換行符處切開（不切半行），並追加：
  ```
  [WARNING: memory index truncated, some entries not loaded]
  ```
- 只存指標，不存內容

### 索引行格式
```
- [filename.md] skill:SKILL_NAME | updated:YYYY-MM-DD | 一行描述
```

範例：
```
- [schedule-gotchas.md] skill:schedule-task | updated:2026-04-07 | 排程任務的已知陷阱與限制
- [user-preferences.md] skill:null | updated:2026-04-06 | 用戶偏好、語言與工作流設定
- [notification-workflow.md] skill:null | updated:2026-04-07 | 通知排程偏好設定
```

---

## Section 2：Warm 層（Topic Files）

### 規格
- 每次對話，用小模型從 MEMORY.md 索引選出最多 **5 個**相關 topic file
- 選中的文件內容追加進 system prompt
- 選擇規則（繼承自 Claude Code）：
  - 正在使用的 skill → 跳過其 API/使用文件
  - 但**一定選**包含已知問題、陷阱、gotcha 的文件
  - 記憶不記代碼（代碼會變，記憶不會自動更新）

### Frontmatter 格式
```yaml
---
title: 排程任務已知問題
tags: [scheduler, gotcha, bug]
skill: schedule-task       # 關聯 skill，null 表示不限
updated: 2026-04-07
---

## 內容...
```

### Warm 選擇器 Prompt 核心規則
```
你正在選擇對 agent 有幫助的記憶文件。
請回傳最多 5 個「明確有用」的檔名。

- 如果列出了最近使用的工具，不要選擇該工具的 API 文件。
- 但仍要選擇包含「警告、陷阱、已知問題」的記憶文件。
- skill 欄位匹配當前呼叫的 skill 時優先選取。
```

---

## Section 3：Cold 層（Transcripts）

### 規格
- Session 啟動時建立新檔：`session-YYYYMMDD-HHMMSS.jsonl`
- 每 turn 結束後 **async append**，不阻塞主回覆
- 搜索方式：Grep 關鍵詞，不用 RAG，不用向量資料庫

### .jsonl 每行格式
```json
{"ts":"2026-04-07T14:30:22+08:00","role":"user","content":"..."}
{"ts":"2026-04-07T14:30:25+08:00","role":"assistant","content":"..."}
```

### 搜索指令（主模型 emit）
```json
{
  "memory": "search",
  "query": "notion webhook",
  "limit": 20
}
```

搜索結果格式：
```
[session-20260402-091500.jsonl | line 47]
user: notion webhook 的問題是...
assistant: 根本原因是...
```
回傳匹配行 + 前後各 2 行作為上下文。

---

## Section 4：寫入機制

### 觸發方式
主模型 inline 判斷並 emit 指令，**移除**現有 background extraction（每 turn 兩次額外 LLM 呼叫）。

### 寫入指令格式
```json
{
  "memory": "write",
  "file": "schedule-gotchas.md",
  "skill": "schedule-task",
  "title": "排程任務已知問題",
  "tags": ["scheduler", "gotcha"],
  "content": "## 相對時間錨定\n排程建立時必須先呼叫 time-query.now 確認本地日期..."
}
```

### 觸發情境

| 情境 | 例子 |
|------|------|
| 用戶明確要求 | 「記住這個」、「以後都這樣做」 |
| 主模型發現 gotcha | 某 skill 回傳意外錯誤，解法值得留存 |
| Context reset 交接 | 「幫我整理這次工作的進度」 |

### 寫入流程
```
主模型 emit memory.write
│
├─ 檔案存在 → 更新內容 + 更新 frontmatter updated 欄位
├─ 檔案不存在 → 建立新 topic file
└─ 兩者都執行 → 更新 MEMORY.md 索引行
   （新檔 → 追加索引行，並檢查 200 行 / 25KB 限制）
```

### 不寫入規則
- 不存程式碼（程式碼會變，記憶不會自動更新）
- 不存一次性任務指令
- 不存暫時狀態（debug 中間結果等）

---

## 移除項目

| 移除 | 原因 |
|------|------|
| `LongTermMemoryManager.remember_turn()` | 改為主模型 inline 寫入 |
| `_extract_memory_payload()` | background extraction 移除 |
| `_extract_explicit_memory_payload()` | background extraction 移除 |
| `LongTermMemoryStore`（JSON 存儲） | 改為 markdown topic files |

---

## 遷移計畫

現有 `skill-memory.json` 有 2 筆記憶（內容重複）：
1. `notification_workflow`
2. `notification_workflow_preference`

遷移步驟：
1. 合併為 `agent/data/memories/topics/notification-workflow.md`
2. 在 `MEMORY.md` 加入索引行
3. 保留原始 `skill-memory.json` 為備份，不刪除

---

## 新增元件

| 元件 | 職責 |
|------|------|
| `MemoryHotLayer` | 讀 MEMORY.md，截斷，注入 system prompt |
| `MemoryWarmSelector` | 小模型選最多 5 個 topic files，載入內容 |
| `MemoryColdWriter` | Async append 每 turn 到 session .jsonl |
| `MemoryWriter` | 處理主模型 emit 的 write/search 指令 |
