# Personal Chief API 项目面试讲解手册

这份文档用于帮助你快速读懂项目、梳理面试表达，并把项目从“课程练习”讲成一个有业务闭环、有 Agent 设计思考的简历项目。

## 1. 项目一句话介绍

Personal Chief API 是一个基于 FastAPI、LangChain/LangGraph、SQLite 记忆、Tavily 搜索和阿里云 OSS 的 AI 私人厨师助手。

它最初支持用户输入食材列表或上传食材图片，然后由 AI Agent 检索菜谱并流式返回推荐。现在项目进一步加入了“厨房记忆 + 多日膳食规划”能力：系统可以保存用户的食材库存、过期时间、饮食偏好、忌口和预算，并生成 1 到 7 天的菜单规划与购物清单。

面试时可以这样说：

> 我做的是一个 AI 私人厨师 Agent。它不只是根据食材推荐一道菜，而是维护用户的长期厨房记忆，包括库存、偏好、忌口和食材过期时间。Agent 在对话时会读取这些结构化记忆，并在用户要求规划一周菜单时，优先消耗临期食材，生成多日菜单和购物清单。

## 2. 项目解决的问题

普通菜谱推荐一般是单轮问答，例如“我有鸡蛋和番茄，能做什么”。这种能力比较常见，简历区分度不高。

这个项目升级后的核心问题是：

- 用户不知道冰箱里的食材怎么组合。
- 食材容易过期，造成浪费。
- 用户有长期偏好，例如减脂、不吃香菜、预算有限、做饭时间少。
- 用户需要的不只是答案，而是一套可执行的多日饮食计划。

所以项目把“菜谱问答”升级成了“有状态的厨房决策 Agent”。

## 3. 技术栈

后端框架：

- FastAPI：提供 HTTP API、参数校验、流式响应。
- Pydantic：定义请求模型和字段验证。
- Uvicorn：运行 ASGI 服务。

AI / Agent：

- LangChain：模型初始化、工具封装。
- LangGraph checkpoint：保存多轮对话状态。
- LLM：通过 `langchain.chat_models.init_chat_model` 接入模型服务。
- Tavily Search：作为联网菜谱搜索工具。

存储：

- SQLite：保存 LangGraph checkpoint。
- SQLite：单独保存厨房库存和用户偏好。

文件上传：

- 阿里云 OSS：生成食材图片上传预签名 URL。

工程工具：

- uv：依赖管理和运行命令。
- unittest + FastAPI TestClient：接口级冒烟测试。

## 4. 项目目录结构

```text
app/
  agents/
    personal_chief.py        AI 私人厨师 Agent，包含 prompt、工具、流式对话、checkpoint 读取
  api/v1/
    chat.py                  聊天流式接口
    chef.py                  厨房库存、偏好、菜单规划接口
    oss.py                   阿里云 OSS 图片上传预签名接口
  common/
    logger.py                日志配置
  core/
    settings.py              环境变量和运行配置
  models/
    schemas.py               请求模型、字段校验、thread_id 校验
  services/
    meal_planner.py          厨房记忆存储和菜单规划业务逻辑
  static/
    ...                      前端静态页面
database/
  memory.db                  LangGraph 对话 checkpoint，运行时生成
  chef_memory.db             厨房库存和偏好，运行时生成
tests/
  test_app.py                接口冒烟测试
README.md                    项目说明
pyproject.toml               项目依赖
```

## 5. 核心功能

### 5.1 食材/图片菜谱推荐

用户通过 `/api/v1/chat/stream` 发送文本或图片 URL。

Agent 的基本流程是：

```text
用户输入食材或图片
  -> 构造 HumanMessage
  -> Agent 读取当前 thread_id 的对话状态
  -> 必要时调用 web_search 工具搜索菜谱
  -> LLM 综合食材、菜谱和用户需求生成回答
  -> StreamingResponse 流式返回文本
```

相关文件：

- `app/api/v1/chat.py`
- `app/agents/personal_chief.py`
- `app/models/schemas.py`

### 5.2 多轮对话记忆

项目使用 LangGraph 的 `SqliteSaver` 作为 checkpointer。

代码位置：

```python
connection = sqlite3.connect(settings.memory_db_path, check_same_thread=False)
checkpointer = SqliteSaver(connection)
checkpointer.setup()
```

每次 Agent 调用时都会传入：

```python
{"configurable": {"thread_id": thread_id}}
```

这样同一个 `thread_id` 下的历史消息可以被保存和读取。

面试表达：

> 我没有把所有用户混在一个上下文里，而是使用 thread_id 做会话隔离。LangGraph checkpoint 会把同一 thread_id 的消息状态保存到 SQLite，支持后续继续对话，也支持查询和清空历史消息。

### 5.3 联网搜索工具

Agent 内部定义了 `web_search` 工具：

```python
@tool
def web_search(query: str) -> Any:
    """Search recipes by ingredients or cooking requirements."""
```

当用户需要菜谱推荐时，Agent 可以调用 Tavily 搜索真实网页内容，而不是完全依赖模型常识。

面试表达：

> 菜谱推荐属于会变化、且需要参考真实来源的场景，所以我给 Agent 接入了 Tavily 搜索工具。这样模型不是闭门造车，而是先搜索，再结合用户食材做筛选和总结。

### 5.4 图片上传

前端上传图片时，不直接把文件传给后端保存，而是调用：

```text
GET /api/v1/oss/presign?filename=food.png
```

后端生成阿里云 OSS 的预签名上传地址，前端再直接上传到 OSS。

这样做的好处：

- 后端不需要承接大文件流量。
- 图片可以通过公网 URL 提供给多模态模型。
- 上传权限是临时的，安全性更好。

### 5.5 厨房库存管理

新增接口：

```text
GET    /api/v1/chef/inventory
POST   /api/v1/chef/inventory
DELETE /api/v1/chef/inventory
```

库存字段包括：

- `name`：食材名称。
- `quantity`：数量，例如 6 个、500g。
- `category`：分类，例如 protein、vegetable。
- `expires_on`：过期时间。
- `notes`：备注。

数据库表：

```sql
CREATE TABLE IF NOT EXISTS inventory_items (
    thread_id TEXT NOT NULL,
    name TEXT NOT NULL,
    quantity TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    expires_on TEXT,
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (thread_id, name)
)
```

这里的设计重点是 `PRIMARY KEY (thread_id, name)`。同一个用户同一种食材再次提交时，会执行 upsert 更新，而不是重复插入。

### 5.6 用户偏好管理

新增接口：

```text
GET  /api/v1/chef/preferences
POST /api/v1/chef/preferences
```

偏好字段包括：

- `dietary_goals`：饮食目标，例如减脂、控糖、高蛋白。
- `allergies`：过敏源。
- `disliked_ingredients`：不喜欢或忌口食材。
- `liked_flavors`：喜欢的口味。
- `budget_level`：预算等级，支持 low、normal、high。
- `cooking_time_minutes`：可接受做饭时间。

面试表达：

> 我把用户偏好做成结构化长期记忆，而不是只放在 prompt 里。这样偏好可以被 API 更新，也可以被菜单规划服务和聊天 Agent 共同读取。

### 5.7 多日菜单规划

新增接口：

```text
POST /api/v1/chef/meal-plan
```

请求示例：

```json
{
  "thread_id": "demo-user",
  "days": 3,
  "meals": ["dinner"],
  "people": 1
}
```

返回内容包括：

- `strategy`：规划策略说明。
- `inventory_summary`：库存数量、临期优先食材、偏好。
- `days`：每天的菜单。
- `shopping_list`：购物清单。
- `agent_talking_points`：用于简历和面试说明的技术亮点。

规划逻辑在 `generate_meal_plan` 中。

核心思路：

```text
读取 thread_id 对应库存和偏好
  -> 找出 5 天内过期的临期食材
  -> 优先使用临期食材生成菜单
  -> 如果没有临期食材，则使用普通库存
  -> 生成每餐菜名、使用库存、缺失食材、推荐理由、步骤
  -> 汇总所有缺失食材生成购物清单
```

这里用了确定性业务逻辑，而不是全部交给 LLM。这样更稳定，也更容易测试。

面试表达：

> 我把菜单规划拆成两层：库存读取和临期食材排序是确定性业务逻辑，保证结果稳定；LLM 负责对话表达和复杂需求理解。这样既有 Agent 的灵活性，也避免了把所有业务规则都塞进 prompt 导致不可控。

## 6. Agent 升级点

原项目是：

```text
用户输入
  -> Agent
  -> web_search
  -> 推荐菜谱
```

升级后是：

```text
用户输入
  -> 根据 thread_id 注入厨房长期记忆
  -> Agent 判断用户意图
  -> 需要菜谱时调用 web_search
  -> 需要菜单规划时调用 kitchen_memory / meal_plan
  -> 输出个性化建议
```

新增工具：

```python
@tool
def kitchen_memory(thread_id: str) -> Any:
    """Get saved inventory and cooking preferences for a conversation thread."""
```

```python
@tool
def meal_plan(thread_id: str, days: int = 3) -> Any:
    """Create a multi-day meal plan from saved inventory and preferences."""
```

同时，`search_recipes` 会在构造用户消息前读取厨房记忆：

```python
context = inventory_context(thread_id)
if context:
    prompt = f"当前 thread_id: {thread_id}\n{context}\n\n当前用户请求:\n{prompt}"
```

这个设计让普通聊天也能感知长期库存和偏好。

## 7. 主要接口说明

### 健康检查

```text
GET /health
```

返回服务状态和功能是否可用：

```json
{
  "status": "ok",
  "service": "Personal Chief API",
  "version": "0.1.0",
  "features": {
    "llm": true,
    "search": true,
    "oss": true,
    "chef_memory": true,
    "meal_plan": true
  }
}
```

### 流式聊天

```text
POST /api/v1/chat/stream
```

请求：

```json
{
  "message": "我这几天晚饭怎么安排？",
  "image_url": null,
  "thread_id": "demo-user"
}
```

返回：`text/plain` 流式文本。

### 查询历史消息

```text
GET /api/v1/chat/messages?thread_id=demo-user
```

### 清空历史消息

```text
DELETE /api/v1/chat/messages?thread_id=demo-user
```

### 新增或更新库存

```text
POST /api/v1/chef/inventory
```

请求：

```json
{
  "thread_id": "demo-user",
  "items": [
    {
      "name": "鸡蛋",
      "quantity": "6个",
      "category": "protein",
      "expires_on": "2026-06-04",
      "notes": "优先使用"
    },
    {
      "name": "番茄",
      "quantity": "3个",
      "category": "vegetable"
    }
  ]
}
```

### 保存偏好

```text
POST /api/v1/chef/preferences
```

请求：

```json
{
  "thread_id": "demo-user",
  "preferences": {
    "dietary_goals": ["减脂"],
    "allergies": [],
    "disliked_ingredients": ["香菜"],
    "liked_flavors": ["清淡"],
    "budget_level": "normal",
    "cooking_time_minutes": 30
  }
}
```

### 生成菜单规划

```text
POST /api/v1/chef/meal-plan
```

请求：

```json
{
  "thread_id": "demo-user",
  "days": 3,
  "meals": ["dinner"],
  "people": 1
}
```

## 8. 数据流完整链路

### 8.1 用户保存库存

```text
前端/接口调用
  -> POST /api/v1/chef/inventory
  -> Pydantic 校验 IngredientItem
  -> ChefMemoryStore.upsert_inventory
  -> SQLite inventory_items 表
  -> 返回当前库存列表
```

### 8.2 用户保存偏好

```text
前端/接口调用
  -> POST /api/v1/chef/preferences
  -> Pydantic 校验 UserPreferences
  -> ChefMemoryStore.save_preferences
  -> SQLite user_preferences 表
  -> 返回当前偏好
```

### 8.3 用户生成菜单

```text
前端/接口调用
  -> POST /api/v1/chef/meal-plan
  -> generate_meal_plan
  -> 读取库存和偏好
  -> _priority_items 找出 5 天内临期食材
  -> _select_ingredients 选择每餐食材
  -> _dish_name 生成菜名
  -> _missing_for 生成缺失调味和配菜
  -> _shopping_list 汇总购物清单
  -> 返回结构化菜单
```

### 8.4 用户通过聊天询问

```text
前端/接口调用
  -> POST /api/v1/chat/stream
  -> search_recipes
  -> inventory_context(thread_id)
  -> 将厨房记忆拼入当前 prompt
  -> Agent 根据需求调用工具
  -> LangGraph checkpoint 保存对话
  -> StreamingResponse 返回
```

## 9. 关键代码理解

### 9.1 `settings.py`

负责读取环境变量，包括：

- 应用名称、版本、端口。
- 模型配置：`DASHSCOPE_API_KEY`、`BASE_URL`、`MODEL_NAME`。
- 搜索配置：`TAVILY_API_KEY`。
- OSS 配置：bucket、region、endpoint。
- 数据库路径：`memory_db_path`、`chef_memory_db_path`。

这里用 dataclass 做配置集中管理，避免在业务代码里到处读取环境变量。

### 9.2 `schemas.py`

负责请求参数校验。

值得讲的点：

- `THREAD_ID_PATTERN` 限制 thread_id 只能包含安全字符。
- `ChatRequest` 限制消息长度，避免无限输入。
- `IngredientItem` 限制食材字段长度，防止异常数据。
- `MealPlanRequest` 限制 days 在 1 到 7 天，避免生成过大响应。

面试表达：

> 我把接口输入边界放在 Pydantic schema 层处理，这样业务层可以假设拿到的数据已经基本合法，代码更清晰。

### 9.3 `personal_chief.py`

这是 Agent 核心。

它包含：

- 系统提示词。
- LangGraph SQLite checkpointer。
- `web_search` 搜索工具。
- `kitchen_memory` 厨房记忆工具。
- `meal_plan` 菜单规划工具。
- `search_recipes` 流式生成函数。
- 历史消息查询和清空函数。

关键点是 Agent 的工具不是摆设，而是和真实业务状态连接的：

- `web_search` 连接外部搜索。·
- `kitchen_memory` 连接 SQLite 厨房记忆。
- `meal_plan` 连接确定性菜单规划服务。

### 9.4 `meal_planner.py`

这是新增的项目亮点。

它主要分成两部分：

第一部分是 `ChefMemoryStore`：

- 创建库存表和偏好表。
- upsert 库存。
- 查询库存。
- 清空库存。
- 保存偏好。
- 查询偏好。
- 获取完整 snapshot。

第二部分是菜单规划函数：

- `inventory_context`：把结构化记忆转成 Agent 可读的上下文。
- `generate_meal_plan`：生成多日菜单。
- `_priority_items`：计算临期食材。
- `_shopping_list`：生成购物清单。

### 9.5 `chef.py`

这是新增的 Chef API 路由层。

路由层只做薄封装：

- 接收请求。
- 调用 service。
- 返回 JSON。

这种分层的好处是：API 层不会堆积业务逻辑，后续如果要加前端、CLI 或定时任务，也可以复用 `meal_planner.py`。

## 10. 简历写法

可以写成 3 条：

- 基于 FastAPI + LangGraph 实现 AI 私人厨师 Agent，支持多轮对话、流式响应、联网菜谱检索和食材图片输入。
- 设计厨房长期记忆模块，使用 SQLite 持久化用户库存、食材过期时间、饮食偏好、忌口和预算，并通过 thread_id 实现用户会话隔离。
- 实现多日菜单规划能力，优先消耗临期食材，自动生成每日菜品、缺失食材和购物清单，并将结构化厨房记忆注入 Agent 对话流程，实现上下文感知推荐。

更高级一点的版本：

> 设计并实现“厨房记忆驱动”的个人厨师 Agent：通过 FastAPI 提供库存、偏好和菜单规划 API，使用 SQLite 持久化用户长期状态，结合 LangGraph checkpoint 管理多轮对话，并为 Agent 注册 web_search、kitchen_memory、meal_plan 工具，使其能够根据临期食材、忌口、预算和烹饪时间生成个性化多日菜单与购物清单。

## 11. 面试时的讲解顺序

建议按这个顺序讲，面试官比较容易听懂：

1. 先说业务场景：解决“冰箱有什么、这几天怎么吃、怎么减少浪费”的问题。
2. 再说基础能力：FastAPI 接口、流式聊天、图片上传、联网搜索。
3. 然后说 Agent：LangGraph checkpoint 保存对话，工具调用搜索和菜单规划。
4. 重点说升级点：厨房长期记忆、临期食材优先、多日菜单和购物清单。
5. 最后说工程质量：Pydantic 校验、SQLite 持久化、接口测试。

## 12. 常见面试问题

### Q1：这个项目和普通 ChatGPT 套壳有什么区别？

答：

普通套壳主要是把用户输入直接发给大模型。我这个项目有三点不同：

- 有工具调用，Agent 可以使用 web_search 查询外部菜谱。
- 有状态记忆，LangGraph checkpoint 保存多轮对话。
- 有业务状态，厨房库存和用户偏好单独持久化，菜单规划会基于真实库存和临期时间生成。

### Q2：为什么要用 LangGraph checkpoint？

答：

因为 Agent 对话不是一次性的。用户可能先上传食材，再问“还有别的做法吗”，或者过一会儿继续问“那明天吃什么”。checkpoint 可以用 thread_id 保存对话状态，实现多轮上下文连续。

### Q3：为什么厨房库存不用直接放在 prompt 里？

答：

直接放 prompt 只能解决当前一轮，而且不可查询、不可更新、不可测试。我把库存和偏好做成 SQLite 结构化存储，API 可以增删查改，Agent 对话时再按 thread_id 注入上下文。这样状态管理更稳定。

### Q4：为什么菜单规划不全部交给大模型？

答：

临期食材排序、购物清单汇总这些规则是确定性的，交给代码更可靠，也方便测试。大模型更适合处理自然语言理解和生成解释。因此我把系统拆成“确定性业务逻辑 + LLM Agent 表达与决策”。

### Q5：如何保证不同用户的数据隔离？

答：

项目使用 `thread_id` 作为会话和厨房记忆的隔离键。LangGraph checkpoint 查询时传入 thread_id，库存和偏好表也都有 thread_id 字段，所以不同用户的数据不会混在一起。

### Q6：搜索工具失败怎么办？

答：

如果没有配置 Tavily key，`web_search` 会返回搜索不可用的信息。系统 prompt 也要求搜索不到时基于常识补充。后续还可以在接口层加入更细的降级策略和错误码。

### Q7：为什么使用 SQLite？

答：

这个项目当前是个人助手和课程练习升级版，SQLite 部署简单、零运维，适合本地演示和小规模使用。后续如果要上线多用户版本，可以把存储层替换为 PostgreSQL 或 MySQL，service 层接口基本不用大改。

### Q8：你这个 Agent 有哪些工具？

答：

目前有三个核心工具：

- `web_search`：搜索菜谱和烹饪资料。
- `kitchen_memory`：读取当前 thread_id 的库存和偏好。
- `meal_plan`：基于库存和偏好生成多日菜单。

### Q9：如何测试这个项目？

答：

项目用 `unittest` 和 FastAPI `TestClient` 做接口冒烟测试。测试覆盖：

- `/health` 健康检查。
- 前端页面是否可访问。
- chat 参数校验。
- OSS 文件名校验。
- 厨房库存、偏好和菜单规划完整链路。

运行命令：

```powershell
uv run python -m compileall app tests
uv run python -m unittest discover -s tests
```

### Q10：这个项目还可以怎么优化？

答：

可以从四个方向继续优化：

- 更智能的菜单规划：引入营养估算、热量目标、蛋白质/碳水/脂肪比例。
- 更真实的库存扣减：用户确认吃完某道菜后，自动减少对应食材数量。
- 更强的工具编排：把“识别图片库存、更新库存、规划菜单、生成购物清单”串成 LangGraph 多节点工作流。
- 更完整的前端体验：增加库存管理页面、菜单日历、购物清单勾选和烹饪步骤模式。

## 13. 本地运行和验证

安装依赖：

```powershell
uv sync
```

复制环境变量：

```powershell
Copy-Item .env.example .env
```

启动服务：

```powershell
uv run python -m app.main
```

默认地址：

```text
http://127.0.0.1:8001
```

运行测试：

```powershell
uv run python -m compileall app tests
uv run python -m unittest discover -s tests
```

## 14. 演示脚本

面试或作品展示时，可以按这个顺序演示：

第一步，保存库存：

```json
{
  "thread_id": "demo-user",
  "items": [
    {
      "name": "鸡蛋",
      "quantity": "6个",
      "category": "protein",
      "expires_on": "2026-06-04"
    },
    {
      "name": "番茄",
      "quantity": "3个",
      "category": "vegetable"
    },
    {
      "name": "鸡胸肉",
      "quantity": "300g",
      "category": "protein",
      "expires_on": "2026-06-05"
    }
  ]
}
```

第二步，保存偏好：

```json
{
  "thread_id": "demo-user",
  "preferences": {
    "dietary_goals": ["减脂", "高蛋白"],
    "allergies": [],
    "disliked_ingredients": ["香菜"],
    "liked_flavors": ["清淡"],
    "budget_level": "normal",
    "cooking_time_minutes": 30
  }
}
```

第三步，生成 3 天晚餐：

```json
{
  "thread_id": "demo-user",
  "days": 3,
  "meals": ["dinner"],
  "people": 1
}
```

第四步，在聊天里问：

```json
{
  "thread_id": "demo-user",
  "message": "根据我现在的库存，这三天晚饭怎么安排？顺便告诉我还要买什么。",
  "image_url": null
}
```

你可以重点展示：Agent 会结合之前保存的库存和偏好，而不是把用户当作全新的上下文。

## 15. 项目亮点总结

这个项目最适合在面试里强调三句话：

第一，它不是简单聊天，而是一个带工具调用的 AI Agent。

第二，它不是无状态问答，而是同时有 LangGraph 对话记忆和 SQLite 业务记忆。

第三，它不是只推荐一道菜，而是围绕库存、偏好、临期食材和购物清单形成了一个完整的生活场景闭环。

第四，它加入了轻量登录注册体系。用户注册登录后，前端会基于用户 id 生成独立 thread_id，后端使用 SQLite 保存用户、加盐密码哈希和 bearer token，使厨房记忆和对话状态具备用户隔离基础。

## 16. 预定义工具升级

这次工具升级的目标不是简单堆功能，而是补齐 Agent 从“推荐”到“执行”的闭环。

新增工具可以分成四类：

- 状态写入工具：`update_inventory`、`consume_inventory`
- 决策辅助工具：`substitute_ingredient`、`estimate_meal_nutrition`
- 执行陪跑工具：`start_cooking_steps`、`cooking_step`
- 原有工具：`web_search`、`kitchen_memory`、`meal_plan`

### 16.1 为什么要加库存写入和扣减

原来的 Agent 可以读取库存，但如果用户说“我刚买了鸡胸肉”或者“番茄炒蛋已经做完了”，系统不能主动更新库存。

新增后：

```text
用户说买了新食材
  -> update_inventory
  -> SQLite 库存更新

用户确认做完一道菜
  -> consume_inventory
  -> 记录食材消耗
  -> 必要时从库存删除
```

这里没有强行解析“6个”“300g”“半瓶”等复杂自然语言数量，因为这很容易产生假精确。当前设计更稳妥：记录消耗行为，如果食材完全用完，调用方可以传 `remove_from_inventory=true`。

面试表达：

> 我没有让 Agent 盲目修改库存数量，因为中文食材单位很复杂。当前实现采用保守策略：记录消耗日志，并支持明确删除已用完食材。这样保证状态更新可信，后续可以再引入单位解析模块。

### 16.2 替代食材工具

`substitute_ingredient` 用于解决做饭中常见的问题：用户缺少某个食材。

它会结合：

- 当前库存中已有的食材。
- 用户过敏源。
- 用户不喜欢的食材。
- 预定义替代规则。

输出内容包括：

- 替代食材名称。
- 替代比例。
- 口味影响。
- 是否已在库存中。

面试表达：

> 替代食材不是单纯让模型发挥，而是先查库存和偏好，再用预定义规则给出可解释建议。这样结果更稳定，也能避免推荐用户过敏或讨厌的食材。

### 16.3 营养估算工具

`estimate_meal_nutrition` 用于轻量估算热量和三大营养素。

返回：

- calories
- protein_g
- carbs_g
- fat_g
- per_serving
- confidence

这个工具定位是“膳食规划辅助”，不是医疗级营养计算。

面试表达：

> 我把营养估算定义为轻量工具，目的是辅助减脂、高蛋白等日常规划，不做医疗建议。对于数据库中没有的食材，会返回较低置信度，避免给用户造成过度准确的错觉。

### 16.4 烹饪步骤陪跑工具

`start_cooking_steps` 用于保存当前菜谱和步骤。

`cooking_step` 支持：

- `current`：查看当前步骤。
- `next`：进入下一步。
- `previous`：返回上一步。
- `finish`：结束烹饪。

这个功能让 Agent 能回答“下一步是什么”“刚才那一步再说一遍”等执行过程问题。

面试表达：

> 我把烹饪过程抽象成一个轻量状态机，保存当前 recipe、steps 和 current_step。这样用户在做饭过程中不需要重复上下文，Agent 可以接着当前进度继续指导。

### 16.5 新增接口

```text
POST /api/v1/chef/inventory/consume
POST /api/v1/chef/substitutions
POST /api/v1/chef/nutrition
POST /api/v1/chef/cooking-session
GET  /api/v1/chef/cooking-session
POST /api/v1/chef/cooking-session/advance
```

### 16.6 简历补充写法

可以在项目经历中加一条：

> 设计 Agent 预定义工具集，封装库存更新、库存消耗、替代食材推荐、营养估算和烹饪步骤追踪等工具，使系统具备从菜谱推荐、多日规划到执行反馈的状态闭环能力。
