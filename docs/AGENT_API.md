# 斗地主 Agent API 文档

> 给 LLM agent / 脚本玩家用的接入文档。
> 服务地址（halo3 上的部署）：**`http://192.168.137.4:8765`**
> 协议：HTTP / JSON。无鉴权，靠 `token` 区分玩家。

---

## 1. 总览

每局游戏一个 `game_id`，三个座位 (`seat` 0/1/2)。流程：

```
   POST /api/games            ──►  game_id
        │
        ├── 三个 agent 各自 POST /api/games/{id}/join  ──►  token (即玩家身份)
        │
        ▼
   phase: bidding              叫地主 (出价 0/1/2/3)
        │
        ▼
   phase: playing              出牌 / 过牌
        │
        ▼
   phase: finished             winner_seat 揭晓
```

agent 的核心循环只有一句话：

> **不断 `GET /state?token=...`，看到 `you.is_your_turn == true` 就 `POST /bid` 或 `POST /play`。**

---

## 2. 端点速查

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET`  | `/api/health` | 健康检查 |
| `GET`  | `/api/games` | 列出所有房间 |
| `POST` | `/api/games` | 创建房间 |
| `POST` | `/api/games/{game_id}/join` | 入座 |
| `GET`  | `/api/games/{game_id}/state?token=...` | 看当前状态（带 token 时返回你的手牌） |
| `POST` | `/api/games/{game_id}/bid` | 叫地主 |
| `POST` | `/api/games/{game_id}/play` | 出牌 / 过牌 |

所有 4xx 错误返回 `{"detail": "<原因>"}`。

---

## 3. 牌面编码

`<RANK><SUIT>` 两字符：

- RANK ∈ `3 4 5 6 7 8 9 T J Q K A 2`（`T` = 10）
- SUIT ∈ `S H D C`（♠ ♥ ♦ ♣）
- 大小王：`BJ`（大王）、`RJ`（小王）

牌值排序（用于比较大小）：

```
3 < 4 < 5 < 6 < 7 < 8 < 9 < T < J < Q < K < A < 2 < RJ < BJ
```

示例：`["3S", "3H", "3D"]` = 三个 3（三张）；`["RJ", "BJ"]` = 王炸。

---

## 4. 接入流程

### 4.1 创建房间（任一 agent 做一次即可）

```bash
curl -X POST http://192.168.137.4:8765/api/games \
  -H 'Content-Type: application/json' \
  -d '{"rule_mode": "builtin"}'
```

请求体（全部可选）：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `rule_mode`   | string | `"builtin"` | `"builtin"` 用内置规则；`"referee"` 委托外部裁判 agent 判牌 |
| `referee_url` | string | `null` | `rule_mode=referee` 时必填 |
| `seed`        | int    | `null` | 固定洗牌种子，用于复现 |

返回：

```json
{"game_id": "ab12cd34", "rule_mode": "builtin"}
```

### 4.2 入座

每个 agent 调一次（共 3 次）：

```bash
curl -X POST http://192.168.137.4:8765/api/games/ab12cd34/join \
  -H 'Content-Type: application/json' \
  -d '{"player_name": "agent-alice"}'
```

返回（**保存好 `token`，后续所有调用都要带**）：

```json
{"player_id": "p_8a3f", "seat": 0, "token": "tok_xxxxxxxxxxx"}
```

三人都加入后服务端自动发牌，`phase` 从 `waiting` 变为 `bidding`。

### 4.3 轮询状态

```bash
curl 'http://192.168.137.4:8765/api/games/ab12cd34/state?token=tok_xxx'
```

返回示例（playing 阶段）：

```json
{
  "game_id": "ab12cd34",
  "phase": "playing",
  "rule_mode": "builtin",
  "players": [
    {"seat": 0, "name": "agent-alice", "joined": true, "hand_count": 17, "is_landlord": true},
    {"seat": 1, "name": "agent-bob",   "joined": true, "hand_count": 17, "is_landlord": false},
    {"seat": 2, "name": "agent-carol", "joined": true, "hand_count": 17, "is_landlord": false}
  ],
  "bids": [3, 0, 0],
  "current_bid": 3,
  "landlord_seat": 0,
  "bid_turn": -1,
  "current_turn": 0,
  "last_play_seat": -1,
  "last_play_cards": [],
  "last_play_category": null,
  "history": [],
  "winner_seat": -1,
  "bottom_cards": ["7C", "JD", "BJ"],
  "you": {
    "seat": 0,
    "name": "agent-alice",
    "hand": ["3S","3H","4D","6C","7C","8S","9H","TD","JC","JD","QS","KH","AS","2D","2C","RJ","BJ","..."],
    "is_landlord": true,
    "is_your_turn": true
  }
}
```

关键字段：

| 字段 | 含义 |
|---|---|
| `phase` | `waiting` / `bidding` / `playing` / `finished` |
| `you.hand` | **你的手牌**（只有带 token 时才会返回） |
| `you.is_your_turn` | 是不是该你叫牌 / 出牌 |
| `current_turn` | 当前出牌座位（`playing` 阶段） |
| `bid_turn` | 当前叫牌座位（`bidding` 阶段） |
| `last_play_seat` | 最后一手出牌的座位；如果等于 `-1` 或等于自己 = **新一轮，你坐庄，可以随便出** |
| `last_play_cards` | 上家牌；你要压过它 |
| `last_play_category` | 上家牌型；详见 §6 |
| `bottom_cards` | 三张底牌；`bidding` 阶段返回 `[]`，确定地主后才显示 |
| `winner_seat` | `finished` 时为胜者座位 |

### 4.4 叫地主

只在 `phase == "bidding"` 且 `you.is_your_turn` 时调用。

```bash
curl -X POST http://192.168.137.4:8765/api/games/ab12cd34/bid \
  -H 'Content-Type: application/json' \
  -d '{"token": "tok_xxx", "bid": 3}'
```

- `bid ∈ {0, 1, 2, 3}`；`0` = 不叫，`3` = 顶分直接结束叫牌。
- 必须**严格大于**当前 `current_bid`（除了 `0` 表示弃叫）。
- 三人全部都叫完一轮、或有人叫到 3 时结束。
- 若三人都叫 0，自动重新发牌。

### 4.5 出牌 / 过牌

只在 `phase == "playing"` 且 `you.is_your_turn` 时调用。

**出牌：**

```bash
curl -X POST http://192.168.137.4:8765/api/games/ab12cd34/play \
  -H 'Content-Type: application/json' \
  -d '{"token": "tok_xxx", "cards": ["3S", "3H", "3D"]}'
```

**过牌（"不要"）：**

```bash
curl -X POST http://192.168.137.4:8765/api/games/ab12cd34/play \
  -H 'Content-Type: application/json' \
  -d '{"token": "tok_xxx", "cards": []}'
```

规则：

- `cards` 中每张必须存在于你的手牌中（精确到花色，例如 `3S` 与 `3H` 不同）。
- `cards` 必须组成合法牌型（见 §6）；否则返回 `400 {"detail": "illegal combination"}`。
- 如果桌上有别人的牌（`last_play_seat != -1 && last_play_seat != 你`），你的牌必须**大于**桌上那一手；否则 `400 {"detail": "does not beat previous play"}`。
- 当 `last_play_seat == -1`（开局首手）或 `last_play_seat == 你`（两家都过完一圈回到你），你坐庄，**不能过牌**，必须出一手任意合法牌。

返回出牌结果：

```json
{
  "phase": "playing",
  "you": {...},
  "result": {
    "action": "play",
    "pattern": {"category": "trio", "main_value": 0, "length": 1,
                "cards": ["3S","3H","3D"]}
  }
}
```

`action ∈ {"play", "pass"}`；若你出完最后一张牌，会附带 `"winner": <seat>`，`phase` 变为 `finished`。

---

## 5. Agent 行为伪代码

```python
import requests, time

BASE = "http://192.168.137.4:8765"

def join(game_id, name):
    r = requests.post(f"{BASE}/api/games/{game_id}/join", json={"player_name": name})
    return r.json()["token"]

def state(game_id, token):
    return requests.get(f"{BASE}/api/games/{game_id}/state",
                        params={"token": token}).json()

def loop(game_id, token, decide_bid, decide_play):
    while True:
        s = state(game_id, token)
        if s["phase"] == "finished":
            print("winner:", s["winner_seat"])
            return
        if not s["you"]["is_your_turn"]:
            time.sleep(0.5)
            continue
        if s["phase"] == "bidding":
            bid = decide_bid(s)            # -> 0/1/2/3
            requests.post(f"{BASE}/api/games/{game_id}/bid",
                          json={"token": token, "bid": bid})
        elif s["phase"] == "playing":
            cards = decide_play(s)         # -> [] 表示过牌
            r = requests.post(f"{BASE}/api/games/{game_id}/play",
                              json={"token": token, "cards": cards})
            if r.status_code >= 400:
                # 决策非法（牌不在手 / 牌型非法 / 压不过），重试或过牌
                ...
```

---

## 6. 牌型与比较规则（builtin）

每一手牌都属于以下之一：

| `category` | 张数 | 说明 | 比较 |
|---|---|---|---|
| `single`           | 1     | 单张 | 单张点数 |
| `pair`             | 2     | 对子 | 对子点数 |
| `trio`             | 3     | 三张 | 三张点数 |
| `trio_single`      | 4     | 三带一 | 三张点数 |
| `trio_pair`        | 5     | 三带一对 | 三张点数 |
| `straight`         | 5+    | 顺子（连续单张，无 2/王，3..A） | 起始点数；**只能压同长度顺子** |
| `pair_straight`    | 6+ 偶 | 连对（3+ 连续对子，无 2/王） | 起始；同长度 |
| `airplane`         | 6+ 三的倍数 | 飞机（k 个连续三张，无 2/王，k≥2） | 起始；同长度 |
| `airplane_single`  | 4k    | 飞机带 k 张单 | 起始；同长度 |
| `airplane_pair`    | 5k    | 飞机带 k 对 | 起始；同长度 |
| `four_two_single`  | 6     | 四带两单 | 四张点数 |
| `four_two_pair`    | 8     | 四带两对 | 四张点数 |
| `bomb`             | 4     | 炸弹（四张点数相同） | 炸弹点数；**可压任何非炸弹/王炸** |
| `rocket`           | 2     | 王炸（`RJ`+`BJ`） | **可压一切** |

比较总规则：

1. 王炸压一切。
2. 炸弹压一切非炸弹/王炸；炸弹之间比点数。
3. 其余牌型：`category` 和 `length` 都相同时才能比，比 `main_value`（起始/主牌点数）。

> 如果创建房间时用了 `rule_mode=referee`，则上述规则由外部裁判 agent 实现，可能不同。这种情况下 agent 应当先用一手 `single` 试探或读取裁判端的规约文档。

---

## 7. 错误码

所有错误统一为 HTTP `400 {"detail": "..."}`，常见 `detail`：

- `"game not found"` — `game_id` 无效（HTTP 404）
- `"invalid token"` — token 与房间不匹配
- `"game already started"` — 房间已满
- `"not in bidding phase"` / `"not in playing phase"` — 当前阶段不对
- `"not your turn"` / `"not your turn to bid"`
- `"bid must be 0/1/2/3"` / `"bid must be > current bid (X)"`
- `"card XX not in hand"`
- `"illegal combination"` — 牌型非法
- `"does not beat previous play"` — 没压过
- `"cannot pass: you must lead a trick"` — 你坐庄不能过牌

收到 400 时**不会**改变游戏状态，agent 应当读最新 state 再决策。

---

## 8. 一个最小 demo（3 个一起跑）

```bash
# 终端 1：建房
GID=$(curl -s -X POST http://192.168.137.4:8765/api/games -H 'Content-Type: application/json' -d '{}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["game_id"])')
echo "GAME=$GID"

# 终端 1/2/3：各加入一次
T1=$(curl -s -X POST http://192.168.137.4:8765/api/games/$GID/join -H 'Content-Type: application/json' -d '{"player_name":"A"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
T2=$(curl -s -X POST http://192.168.137.4:8765/api/games/$GID/join -H 'Content-Type: application/json' -d '{"player_name":"B"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
T3=$(curl -s -X POST http://192.168.137.4:8765/api/games/$GID/join -H 'Content-Type: application/json' -d '{"player_name":"C"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

# 看初始状态（谁先叫地主）
curl -s "http://192.168.137.4:8765/api/games/$GID/state?token=$T1" | python3 -m json.tool
```

之后按 `bid_turn` / `current_turn` 轮流喂决策即可。Web UI（`http://192.168.137.4:8765/`）也可以作为人类观察席同时围观。

---

## 9. 备注

- 状态机是纯内存的，服务重启后所有房间清空。
- 没有超时机制：agent 不出牌就会卡住。建议在你自己 agent 里加超时。
- CORS 全放开，浏览器侧也能直接 fetch。
