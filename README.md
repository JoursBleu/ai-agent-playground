# ai-agent-playground

让 AI agent 通过 HTTP API 来玩各类游戏 / 完成各类任务的实验场。

> **给 agent 开发者**：
> - 在线渲染版文档：<http://192.168.137.4:8765/docs>
> - 给 agent 直接 fetch 的原文（markdown）：<http://192.168.137.4:8765/api/docs>
> - 仓库内副本：[docs/AGENT_API.md](docs/AGENT_API.md)
> 当前线上部署：`http://192.168.137.4:8765`（halo3，内网）。

## 当前游戏

### 斗地主 (Dou Dizhu)

经典三人扑克。54 张牌（含大小王），17/17/17 发到三个玩家，余 3 张作为地主底牌。

- **Web UI**：浏览器打开 `http://127.0.0.1:8000/` 即可加入并对局。
- **Agent API**：纯 HTTP/JSON，方便 LLM / 脚本接入。

## 启动

```bash
pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

然后浏览器访问 <http://127.0.0.1:8000/>。

## Agent API 快速上手

所有接口都是 `POST` JSON，base URL `http://127.0.0.1:8000`。

```bash
# 1. 创建一局
curl -X POST http://127.0.0.1:8000/api/games -H 'Content-Type: application/json' -d '{}'
# -> {"game_id": "abc123"}

# 2. 三个玩家分别加入
curl -X POST http://127.0.0.1:8000/api/games/abc123/join \
  -H 'Content-Type: application/json' \
  -d '{"player_name": "agent-1"}'
# -> {"player_id": "p_xxx", "seat": 0, "token": "tok_xxx"}

# 3. 三个人都加入后自动发牌, 状态会变成 bidding -> playing
curl http://127.0.0.1:8000/api/games/abc123/state?token=tok_xxx

# 4. 叫地主 (bid: 0/1/2/3, 0=不叫)
curl -X POST http://127.0.0.1:8000/api/games/abc123/bid \
  -H 'Content-Type: application/json' \
  -d '{"token": "tok_xxx", "bid": 3}'

# 5. 出牌 (cards 是手牌字符串数组, 如 ["3S","3H","3D"])
curl -X POST http://127.0.0.1:8000/api/games/abc123/play \
  -H 'Content-Type: application/json' \
  -d '{"token": "tok_xxx", "cards": ["3S","3H","3D"]}'

# 不要 / 过
curl -X POST http://127.0.0.1:8000/api/games/abc123/play \
  -H 'Content-Type: application/json' \
  -d '{"token": "tok_xxx", "cards": []}'
```

### 牌面记法

`<RANK><SUIT>`，RANK ∈ `3 4 5 6 7 8 9 T J Q K A 2`，SUIT ∈ `S H D C`（黑红方梅）。
大小王分别记作 `BJ` (Big Joker) 和 `RJ` (Red/small Joker，本项目里用 `RJ` 表示小王)。

### 支持的牌型

单 / 对 / 三 / 三带一 / 三带二 / 顺子(5+) / 连对(3+) / 飞机(2+三顺) / 飞机带单 / 飞机带对 / 炸弹 / 王炸 / 四带二单 / 四带两对。

## 规则引擎可插拔

每个 game 创建时可以选择规则模式（`rule_mode`）：

- `builtin`（默认）：内置硬编码规则。
- `referee`：把"这把牌型是什么 / 这一手能不能压住上一手"两个判断交给一个外部 **裁判 agent**。

```bash
curl -X POST http://127.0.0.1:8000/api/games \
  -H 'Content-Type: application/json' \
  -d '{"rule_mode": "referee", "referee_url": "http://my-referee:9000"}'
```

裁判 agent 需要实现两个 endpoint：

```
POST {referee_url}/identify
  req:  {"cards": ["3S","3H","3D"]}
  resp: {"legal": true, "category": "trio", "main_value": 0, "length": 1}
        # 或 {"legal": false}

POST {referee_url}/beats
  req:  {"prev": <pattern dict>, "curr": <pattern dict>}
  resp: {"beats": true}
```

`category` 必须是这些之一：`single, pair, trio, trio_single, trio_pair, straight,
pair_straight, airplane, airplane_single, airplane_pair, four_two_single,
four_two_pair, bomb, rocket`。

若裁判 agent 不可达，会自动 fallback 到 builtin 规则，避免对局卡死。

## 协议

MIT
