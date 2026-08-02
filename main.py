"""
twinsoul v3 - 双子Soul插件（完整版）
让尤里家双子（扎恩斯 & 威廉）在群聊中进行有记忆的长对话

核心特性:
  1. 长对话上下文记忆（保留最近N轮）
  2. 定时随机问候（早起、吃饭、晚安，像真人一样）
  3. 插话机制（有人在群里和双子说话时，另一人概率性插话）
  4. 时段感知（不同时段问候概率不同）
  5. 双账号分离（各用各的QQ发消息）
  6. 全部参数可调
  7. WebUI 管理面板

指令:
  /ts              - 帮助
  /ts 开启         - 启动定时对话+问候
  /ts 关闭         - 停止
  /ts 对话 [话题]  - 手动触发一轮
  /ts 重置         - 清空记忆
  /ts 状态         - 查看状态
  /ts 设置 k v     - 改配置
"""

import os, time, random, asyncio, json, yaml
from typing import Optional
from datetime import datetime, time as dtime

from astrbot.api.event import AstrMessageEvent
from astrbot.api.event import filter as filter_mod
from astrbot.api.star import Context, Star, register
from astrbot.api.web import json_response, error_response, request
from astrbot.api import logger
from astrbot.core.star.star_handler import EventType, StarHandlerMetadata, star_handlers_registry

PLUGIN_NAME = "twinsoul"
BASE_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
HISTORY_PATH = os.path.join(BASE_DIR, "chat_history.json")
CONTEXT_PATH = os.path.join(BASE_DIR, "context_memory.json")
SCHEDULE_PATH = os.path.join(BASE_DIR, "schedule.json")

# ─── 工具函数 ──────────────────────────────────────────────

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)

def load_history() -> list:
    if not os.path.exists(HISTORY_PATH): return []
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return []

def save_history(history: list):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history[-500:], f, ensure_ascii=False, indent=2)

def load_context() -> dict:
    if not os.path.exists(CONTEXT_PATH): return {"zaiens": [], "william": []}
    try:
        with open(CONTEXT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict): return data
            return {"zaiens": [], "william": []}
    except: return {"zaiens": [], "william": []}

def save_context(ctx: dict):
    # 容量保护：每角色最多200条，防磁盘写爆
    for k in list(ctx.keys()):
        if isinstance(ctx[k], list) and len(ctx[k]) > 200:
            ctx[k] = ctx[k][-200:]
    with open(CONTEXT_PATH, "w", encoding="utf-8") as f:
        json.dump(ctx, f, ensure_ascii=False, indent=2)

# 各时段的问候种子
MORNING_SEEDS = [
    "早上了", "起床了", "今天天气不错", "早上吃什么",
    "新的一天", "睡醒了没", "早啊",
]
NOON_SEEDS = [
    "中午了", "午饭吃什么", "饿了", "今天中午吃啥",
    "饭点了", "忙了一上午",
]
EVENING_SEEDS = [
    "晚上了", "晚饭吃什么", "今天累不累", "收工了",
    "天黑了", "该吃饭了",
]
NIGHT_SEEDS = [
    "不早了", "睡了", "晚安", "早点休息",
    "今天差不多了", "关店了",
]

# 通用种子（不分时段）
SEEDS = [
    "刚忙完", "今天客人多", "酒馆刚收拾完",
    "外面下雨了", "看到你了", "没什么事",
    "李先生今天来过了", "有点无聊", "想着你",
]

def get_hour_seed() -> str:
    """根据当前时段返回合适的问候种子"""
    h = datetime.now().hour
    if 6 <= h < 9:
        return random.choice(MORNING_SEEDS)
    elif 11 <= h < 13:
        return random.choice(NOON_SEEDS)
    elif 17 <= h < 19:
        return random.choice(EVENING_SEEDS)
    elif h >= 22 or h < 6:
        return random.choice(NIGHT_SEEDS)
    else:
        return random.choice(SEEDS)

# ─── 每日日程（酒馆的一天）────────────────────────────────
# (窗口起, 窗口止, 标题, 固定?, 细节)  固定=时间钉死，浮动=窗内随机
SCHEDULE_TEMPLATE = [
    ("05:30", "06:30", "起床", True, "煮一壶俄式浓茶，把楼梯口的灯留着"),
    ("06:00", "07:00", "早市采购", False, "去城南码头进货，顺带两份早餐"),
    ("07:00", "08:30", "备货", False, "擦吧台、摆酒、冰镇啤酒杯"),
    ("08:30", "11:00", "事务所时段", False, "爱德华整理卷宗，艾文尼尔轮班接委托"),
    ("11:00", "11:50", "叫扎恩斯起床", False, "上楼喊弟弟吃饭，唠叨两句"),
    ("12:00", "12:00", "午市开门", True, "开店，简单做几个下酒菜"),
    ("12:00", "14:00", "午市", False, "扎恩斯调酒，威廉跑堂兼掌勺"),
    ("14:00", "16:00", "歇午", False, "店里清静，打盹看报"),
    ("17:00", "17:00", "晚市开门", True, "霓虹亮起来，店里开始上人"),
    ("17:00", "21:00", "晚市高峰", False, "招呼客人，记着谁爱喝什么"),
    ("21:00", "22:30", "渐静", False, "客人散场，收拾吧台"),
    ("22:30", "23:20", "打烊准备", False, "锁门熄灯，水果包一份放冰箱"),
    ("23:30", "23:30", "打烊", True, "账本合上，上楼睡觉"),
]

def _hm(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def _mh(mins: int) -> str:
    return f"{mins // 60:02d}:{mins % 60:02d}"

def _gen_schedule(date_str: str) -> list:
    """按日期种子生成当天节点，固定时间钉死、浮动节点窗内随机且递增"""
    rng = random.Random(f"twinsoul-schedule-{date_str}")
    nodes = []
    prev = 0
    for ws, we, title, fixed, detail in SCHEDULE_TEMPLATE:
        ws_m, we_m = _hm(ws), _hm(we)
        if fixed:
            t = ws_m
        else:
            lo = max(ws_m, prev + 2)
            hi = we_m - 2
            t = lo if hi <= lo else rng.randint(lo, hi)
        nodes.append({
            "time": _mh(t), "title": title, "detail": detail,
            "fixed": fixed, "status": "pending", "manual": False,
        })
        prev = t
    return nodes

def _save_schedule(data: dict):
    try:
        with open(SCHEDULE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"twinsoul: 日程保存失败 {e}")

def _load_schedule() -> dict:
    """读今日日程，日期不符则重新生成（同一天内多次读取结果一致）"""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("date") == today:
            return data
    except Exception:
        pass
    data = {"date": today, "nodes": _gen_schedule(today)}
    _save_schedule(data)
    return data

def _refresh_schedule_status(data: dict) -> dict:
    """按当前时间刷新节点状态（手动标记的节点不覆盖）"""
    now = datetime.now()
    cur = now.hour * 60 + now.minute
    nodes = data.get("nodes", [])
    active_idx = -1
    for n in nodes:
        if n.get("manual"):
            continue
        n["status"] = "done" if cur >= _hm(n["time"]) else "pending"
    # 进行中 = 最后一个时间已到的节点（若当前还没到第一个节点则无进行中）
    for i, n in enumerate(nodes):
        if cur >= _hm(n["time"]):
            active_idx = i
        else:
            break
    if active_idx >= 0 and not nodes[active_idx].get("manual"):
        nodes[active_idx]["status"] = "active"
    data["active_idx"] = active_idx
    return data

def get_time_context() -> str:
    """根据真实时间生成角色视角的情景描述（不直接报数字时间）"""
    now = datetime.now()
    h = now.hour
    wd = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
    if 5 <= h < 9:
        period = "大清早"
    elif 9 <= h < 11:
        period = "上午"
    elif 11 <= h < 14:
        period = "中午"
    elif 14 <= h < 17:
        period = "下午"
    elif 17 <= h < 19:
        period = "傍晚"
    elif 19 <= h < 23:
        period = "晚上"
    else:
        period = "深夜"
    parts = [f"{period}，星期{wd}"]
    if 11 <= h < 13:
        parts.append("到饭点了")
    elif 17 <= h < 20:
        parts.append("快到饭点了")
    elif 21 <= h < 23:
        parts.append("夜已深，该收摊歇息了")
    elif h >= 23 or h < 5:
        parts.append("夜深人静，都歇下了")
    # 日程注入：当前进行中的事项
    try:
        _d = _refresh_schedule_status(_load_schedule())
        for _n in _d.get("nodes", []):
            if _n.get("status") == "active":
                parts.append(f"现在正{_n['title']}（{_n['time']}）")
                break
    except Exception:
        pass
    return "、".join(parts)

def get_time_bonus(cfg: dict) -> int:
    """获取当前时段的额外概率加成"""
    h = datetime.now().hour
    if 6 <= h < 9: return cfg.get("morning_boost", 25)
    elif 11 <= h < 13: return cfg.get("noon_boost", 20)
    elif 17 <= h < 19: return cfg.get("evening_boost", 20)
    elif h >= 22 or h < 6: return cfg.get("night_boost", 15)
    return 0

CLOSING_PHRASES = ["晚安", "睡吧", "早点歇", "先忙", "明儿见", "拜拜", "先下", "不聊",
                 "睡了", "歇着吧", "关店", "打烊", "明天见", "明天再说", "睡吧"]

def is_closing_line(text: str) -> bool:
    """快速判断一句话是否已是结束语/收尾（规则兜底，不调LLM）"""
    t = text.strip()
    if not t:
        return True
    # 极短应承：嗯/好/行/哦/哈哈 等
    if len(t) <= 8 and any(w in t for w in ["嗯", "好", "行", "哦", "哈哈", "ok", "知道", "是啊"]):
        return True
    return any(w in t for w in CLOSING_PHRASES)

def is_in_sleep_window(cfg: dict) -> bool:
    """判断当前是否处于睡眠时间窗（支持跨天，如 23:00-7:00）"""
    try:
        start = int(cfg.get("sleep_start_hour", 23))
        end = int(cfg.get("sleep_end_hour", 7))
    except:
        start, end = 23, 7
    if start == end:
        return False
    h = datetime.now().hour
    if start < end:
        return start <= h < end
    return h >= start or h < end

def wants_to_sleep(cfg: dict) -> bool:
    """睡眠时间窗内，概率熬夜后仍是否应当休息。
    返回 True 表示应该休息（不活动），False 表示今晚没睡/还在熬夜。"""
    if not is_in_sleep_window(cfg):
        return False
    chance = cfg.get("sleep_talk_chance", 15)
    try: chance = int(chance)
    except: chance = 15
    return random.randint(1, 100) > chance

# ─── 主插件类 ──────────────────────────────────────────────

@register(PLUGIN_NAME, "扎恩斯", "双子Soul v3.1 - 长对话+问候+插话+延迟+睡眠+WebUI", "3.1.0")
class TwinSoulPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config = load_config()
        self._running = False
        self._emergency_stop = False
        self._task: Optional[asyncio.Task] = None
        self._bot_map: dict = {}
        self.context_memory = load_context()
        self._chat_history = load_history()

        # 手动注册消息监听（替代不存在的 @filter.on_message）
        self._register_message_handler()

        # 注册 Web API
        self._register_apis()

        # 配置了群号则自动开启（重启后无需手动 /ts 开启）
        if self.config.get("group_id"):
            try:
                self._task = asyncio.create_task(self._auto_start())
            except Exception as e:
                logger.error(f"twinsoul 自动启动失败: {e}")

        logger.info(f"{PLUGIN_NAME} v3 加载完成")

    def _register_message_handler(self):
        """手动注册一个无过滤条件的消息处理器，用于插话"""
        md = StarHandlerMetadata(
            event_type=EventType.AdapterMessageEvent,
            handler_full_name=f"{__name__}_twinsoul_on_group_message",
            handler_name="on_group_message",
            handler_module_path=__name__,
            handler=self.on_group_message,
            event_filters=[],
            desc="twinsoul 插话：监听群消息"
        )
        star_handlers_registry.append(md)

    def _register_apis(self):
        apis = [
            ("status",       self._api_status,       ["GET"]),
            ("config",       self._api_get_config,    ["GET"]),
            ("config/save",  self._api_save_config,   ["POST"]),
            ("chat",         self._api_do_chat,       ["POST"]),
            ("history",      self._api_history,       ["GET"]),
            ("history/clear",self._api_clear_history, ["POST"]),
            ("context",      self._api_context,       ["GET"]),
            ("context/clear",self._api_clear_context, ["POST"]),
            ("history/remove", self._api_remove_history, ["POST"]),
            ("context/remove", self._api_remove_context, ["POST"]),
            ("schedule",     self._api_schedule,       ["GET"]),
            ("schedule/toggle", self._api_schedule_toggle, ["POST"]),
            ("schedule/regen", self._api_schedule_regen, ["POST"]),
            ("start",        self._api_start,         ["POST"]),
            ("stop",         self._api_stop,          ["POST"]),
            ("greet",        self._api_greet,         ["POST"]),
        ]
        for route, handler, methods in apis:
            self.context.register_web_api(
                f"/{PLUGIN_NAME}/{route}", handler, methods, f"{PLUGIN_NAME} {route}"
            )

    async def _auto_start(self):
        """插件加载后自动开启：等 3 秒让 provider/bot 就绪，再启动定时循环"""
        try:
            await asyncio.sleep(3)
            if self._running:
                return
            await self._refresh_bot_map()
            zq = self.config.get("zaiens_qq", "")
            wq = self.config.get("william_qq", "")
            if not self._get_bot_by_qq(zq) or not self._get_bot_by_qq(wq):
                logger.warning("twinsoul 自动启动: 未找到双子 bot，等待下一次重载")
                return
            self._running = True
            self._task = asyncio.create_task(self._timed_loop())
            logger.info("twinsoul 已自动开启（定时对话+插话）")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"twinsoul 自动启动异常: {e}")

    # ─── Bot映射 ───────────────────────────────────────────

    async def _refresh_bot_map(self):
        self._bot_map.clear()
        for inst in self.context.platform_manager.platform_insts:
            bot = getattr(inst, 'bot', None)
            if not bot: continue
            try:
                info = await bot.call_action("get_login_info")
                qq = str(info.get("user_id", ""))
                if qq: self._bot_map[qq] = bot
            except: pass

    def _get_bot_by_qq(self, qq: str):
        return self._bot_map.get(qq)

    # ─── 核心：说话 ────────────────────────────────────────

    def _build_prompt(self, persona_name: str, seed: str, 
                      is_greeting: bool = False, is_interject: bool = False,
                      is_long: bool = False,
                      replied_to: str = "") -> str:
        """构建 prompt：原始设定 + 最近聊天 + 当前情景"""
        # persona_name 可能是 '111'/'William'（数据库ID），映射到记忆key
        mem_key = "zaiens" if persona_name in ("zaiens", "111") else "william"
        memory = self.context_memory.get(mem_key, [])
        ctx_rounds = self.config.get("context_rounds", 12)
        recent = memory[-(ctx_rounds * 2):] if len(memory) > ctx_rounds * 2 else memory

        # 从数据库获取原始人格设定原文
        raw_prompt = ""
        try:
            personality = self.context.persona_manager.get_persona_v3_by_id(persona_name)
            if personality and personality.get("prompt"):
                raw_prompt = personality["prompt"]
        except:
            pass

        lines = ["=== 人物设定 ==="]
        lines.append(raw_prompt if raw_prompt else f"你是{persona_name}。")
        lines.append("")

        if recent:
            lines.append("=== 最近聊天 ===")
            for entry in recent:
                rn = "扎恩斯" if entry["role"] == "zaiens" else "威廉"
                txt = entry["text"].replace("\n", " ").strip()[:50]
                lines.append(f"{rn}: {txt}")
            lines.append("")

        lines.append("=== 说话要求 ===")
        lines.append("自然口语化，直接说内容。别用「嗯」「啊」「哦」「那」等口头禅开头或填充；别重复对方刚说过的话或观点；话题自然结束就简单收尾，别硬续。")
        lines.append("")

        lines.append("=== 当前 ===")
        lines.append(f"【时间情景】{get_time_context()}。顺着这个情景说话，但别直接报几点几分。")
        if replied_to:
            lines.append(f"刚才{replied_to}说了话，你回应一句。")
        elif is_greeting:
            lines.append("刚打开群聊，随口打个招呼。")
        elif is_interject:
            lines.append("群里有人在说话，你随口接一句。")
        elif is_long:
            lines.append("顺着话题继续聊。如果是自然结束点，末尾加【END】。")
        elif seed:
            lines.append(f"聊聊{seed}。")
        else:
            lines.append("说句日常话。")

        return "\n".join(lines)

    async def _speak_as(self, group_id: str, qq: str, persona_name: str,
                         seed_text: str = "",
                         is_greeting: bool = False,
                         is_interject: bool = False,
                         is_long: bool = False,
                         replied_to: str = "",
                         use_delay: bool = True) -> Optional[str]:
        if use_delay:
            await self._simulate_reply_delay()
        try:
            provider = self.context.get_using_provider(
                umo=f"zaiens:GroupMessage:{group_id}"
            )
            if not provider: return None

            prompt = self._build_prompt(persona_name, seed_text, is_greeting, is_interject, is_long, replied_to)
            dbg = self.config.get("debug_log", True)

            if dbg:
                scene = ("问候" if is_greeting else "插话" if is_interject else
                         "续聊" if is_long else "话题" if seed_text else "日常")
                pname = getattr(provider, "provider_name", None) or type(provider).__name__
                logger.info(f"[twinsoul] ▶ {persona_name} 发言 | 情景={scene} | 回复对象={replied_to or '-'} | 延迟={'开' if use_delay else '关'} | provider={pname}")
                logger.info(f"[twinsoul]   prompt共{len(prompt)}字, 前220字: {prompt[:220].replace(chr(10), ' ⏎ ')}...")

            t0 = time.time()
            ret = await provider.text_chat(
                prompt=prompt,
                session_id=f"twinsoul_{persona_name}_{group_id}",
                contexts=[], image_urls=[],
            )
            cost = time.time() - t0

            if ret and ret.completion_text:
                if dbg:
                    rc = getattr(ret, "reasoning_content", None)
                    if rc:
                        logger.info(f"[twinsoul]   🧠思维链({persona_name}): {str(rc)[:300]}")
                    usage = getattr(ret, "usage", None)
                    if usage:
                        tin = (getattr(usage, "input_other", 0) or 0) + (getattr(usage, "input_cached", 0) or 0)
                        tout = getattr(usage, "output", 0) or 0
                        logger.info(f"[twinsoul]   ⓪耗时{cost:.1f}s | tokens in={tin} out={tout}")
                    else:
                        logger.info(f"[twinsoul]   ⓪耗时{cost:.1f}s")
                    logger.info(f"[twinsoul]   原始回复: {ret.completion_text[:200]}")
                reply = ret.completion_text.strip().replace("【END】", "").replace("[END]", "").strip()
                reply = reply.split("\n")[0].strip()[:80]
                if len(reply) < 2: return None
                bot = self._get_bot_by_qq(qq)
                if not bot: return None
                await bot.call_action("send_group_msg", group_id=int(group_id), message=reply)
                if dbg:
                    logger.info(f"[twinsoul] ✓ 已发送({persona_name}): {reply}")
                return reply
            if dbg:
                logger.info(f"[twinsoul] ✗ {persona_name} 无回复 (耗时{cost:.1f}s)")
            return None
        except Exception as e:
            logger.error(f"twinsoul _speak_as 出错: {e}")
            return None

    async def _simulate_reply_delay(self):
        """模拟真人回复延迟：多数情况短（人正看着屏幕），偶尔长（思考/懒得回）。
        短延迟 2~delay_short_sec 秒；小概率走长延迟 delay_long_min_sec~delay_long_max_sec 秒。"""
        cfg = self.config
        try:
            short_max = float(cfg.get("delay_short_sec", 20))
            long_min = float(cfg.get("delay_long_min_sec", 60))
            long_max = float(cfg.get("delay_long_max_sec", 180))
            long_chance = float(cfg.get("delay_long_chance", 20))
        except Exception:
            short_max, long_min, long_max, long_chance = 20, 60, 180, 20
        if long_min > long_max:
            long_min = long_max
        if random.random() * 100 < long_chance:
            secs = random.uniform(long_min, long_max)
        else:
            secs = random.uniform(2, short_max)
        if secs > 0:
            await asyncio.sleep(secs)

    def _update_context(self, persona_name: str, text: str, role: str):
        """更新双方记忆"""
        for name in ["zaiens", "william"]:
            if name not in self.context_memory:
                self.context_memory[name] = []
            self.context_memory[name].append({
                "role": role, "text": text,
                "time": datetime.now().isoformat()
            })
        save_context(self.context_memory)

    # ─── 一轮对话 ──────────────────────────────────────────

    async def _should_continue_chat(self, last_reply: str, group_id: str) -> bool:
        """用 LLM 判断对话是否应该继续"""
        try:
            provider = self.context.get_using_provider(
                umo=f"zaiens:GroupMessage:{group_id}"
            )
            if not provider: return False
            judge_prompt = f"""判断下面这句话是否是一个话题的自然结束。
出现以下情况回答 NO（终止本轮对话）：
- 晚安、睡吧、早点歇、先忙了、明儿见、拜拜、睡了 等告别或收尾
- 只是简单应承：嗯、好的、知道了、行、哈哈、哦、是啊
- 在重复前面已经说过的内容（车轱辘话、客套话来回拉扯）
- 话题已聊尽，没有新信息可接
出现以下情况回答 YES（继续回复）：
- 提出疑问、反问、邀请对方说话
- 分享新信息、吐槽、提到新话题
只回答 YES 或 NO，不要多余内容。

对方最后一句话：{last_reply}"""
            ret = await provider.text_chat(
                prompt=judge_prompt,
                session_id="twinsoul_judge",
                contexts=[], image_urls=[],
            )
            if ret and ret.completion_text:
                result = ret.completion_text.strip().upper()
                go = "YES" in result
                if self.config.get("debug_log", True):
                    logger.info(f"[twinsoul]   状态判定(LLM): 「{last_reply[:30]}」→ {'继续回复' if go else '终止本轮对话'}")
                return go
            return False
        except:
            return False

    async def _do_chat_round(self, custom_seed: str = "", force: bool = False):
        group_id = self.config.get("group_id", "").strip()
        if not group_id: return

        # 睡眠窗口内默认休息；只有手动触发(force)才可能熬夜聊
        if not force and wants_to_sleep(self.config):
            logger.info("twinsoul: 睡眠时间内，双子已休息，跳过对话")
            return

        await self._refresh_bot_map()
        zq = self.config.get("zaiens_qq", "")
        wq = self.config.get("william_qq", "")
        zp = self.config.get("zaiens_persona", "zaiens")
        wp = self.config.get("william_persona", "william")

        if not self._get_bot_by_qq(zq) or not self._get_bot_by_qq(wq):
            logger.error("twinsoul: bot映射不完整"); return

        wc = self.config.get("william_initiate_chance", 55)
        roll = random.randint(1, 100)
        seed = custom_seed or get_hour_seed()
        max_rounds = self.config.get("max_chat_rounds", 8)
        round_data = []
        ts = datetime.now().timestamp()
        stop_reason = "normal"

        # 互斥：同一时间只允许一个对话轮在跑，防止并发拉扯
        if getattr(self, "_chat_active", False):
            if self.config.get("debug_log", True):
                logger.info("[twinsoul] ⏳ 已有对话进行中，本次触发跳过（防并发拉扯）")
            return
        self._chat_active = True
        try:
            # 发起者先说话
            if roll <= wc:
                first_speaker_qq, first_speaker_persona = wq, wp
                first_speaker_role = "william"
                second_speaker_qq, second_speaker_persona = zq, zp
                second_speaker_role = "zaiens"
            else:
                first_speaker_qq, first_speaker_persona = zq, zp
                first_speaker_role = "zaiens"
                second_speaker_qq, second_speaker_persona = wq, wp
                second_speaker_role = "william"

            if self.config.get("debug_log", True):
                logger.info(f"[twinsoul] === 对话轮开始 | 发起={first_speaker_role} | seed={seed[:30]} | 上限{max_rounds}轮 ===")
            first = await self._speak_as(group_id, first_speaker_qq, first_speaker_persona, seed, use_delay=not force)
            if not first: return
            round_data.append({"time": ts, "role": first_speaker_role, "text": first, "qq": first_speaker_qq})
            self._update_context(first_speaker_persona, first, first_speaker_role)
            last_reply = first

            # 长对话循环
            for r in range(max_rounds):
                if self._emergency_stop:
                    stop_reason = "emergency_stop"
                    if self.config.get("debug_log", True):
                        logger.info("[twinsoul] ⛔ 状态判定: 收到急停 → 终止本轮对话")
                    break
                await asyncio.sleep(random.uniform(2, 6))
                is_second = (r % 2 == 0)
                qq = second_speaker_qq if is_second else first_speaker_qq
                pn = second_speaker_persona if is_second else first_speaker_persona
                role = second_speaker_role if is_second else first_speaker_role
                if self.config.get("debug_log", True):
                    logger.info(f"[twinsoul] --- 轮次{r} | 说话={role} ---")

                reply = await self._speak_as(
                    group_id, qq, pn, seed,
                    is_long=True, replied_to=last_reply,
                    use_delay=not force
                )
                # 失败重试一次，避免对话硬断
                if not reply:
                    await asyncio.sleep(3)
                    reply = await self._speak_as(
                        group_id, qq, pn, seed,
                        is_long=True, replied_to=last_reply,
                        use_delay=False
                    )
                if not reply:
                    stop_reason = "no_reply"; break

                round_data.append({"time": datetime.now().timestamp(), "role": role, "text": reply, "qq": qq})
                self._update_context(pn, reply, role)
                last_reply = reply

                # 规则兜底：结束语/短应承直接终止（不调LLM，快且准）
                if is_closing_line(reply) and r >= 1:
                    stop_reason = "closing_rule"
                    if self.config.get("debug_log", True):
                        logger.info(f"[twinsoul] 状态判定(规则): 「{reply[:30]}」→ 终止本轮对话")
                    break

                # LLM 判断（聊得够久才问，省调用）
                if r >= 3:
                    should_stop = not await self._should_continue_chat(reply, group_id)
                    if should_stop:
                        stop_reason = "llm_judge"; break
                    if self.config.get("debug_log", True):
                        logger.info(f"[twinsoul] 状态判定(LLM): 「{reply[:30]}」→ 继续回复")

            logger.info(f"twinsoul: 对话结束，共{r+1}轮，原因={stop_reason}")

            if round_data:
                self._chat_history.extend(round_data)
                save_history(self._chat_history)

        # ─── 问候 ──────────────────────────────────────────────
        finally:
            self._chat_active = False


    async def _do_greeting(self, force: bool = False):
        """随机问候：根据时段选一个人说话"""
        group_id = self.config.get("group_id", "").strip()
        if not group_id: return

        # 睡眠窗口内默认不主动问候
        if not force and wants_to_sleep(self.config):
            logger.info("twinsoul: 睡眠时间内，双子已休息，跳过问候")
            return

        await self._refresh_bot_map()
        zq = self.config.get("zaiens_qq", "")
        wq = self.config.get("william_qq", "")
        zp = self.config.get("zaiens_persona", "zaiens")
        wp = self.config.get("william_persona", "william")

        if not self._get_bot_by_qq(zq) or not self._get_bot_by_qq(wq):
            return

        # 随机选谁问候
        if random.randint(1, 100) <= 50:
            seed = get_hour_seed()
            text = await self._speak_as(group_id, zq, zp, seed, is_greeting=True, use_delay=not force)
            if text:
                self._update_context(zp, text, "zaiens")
                self._chat_history.append({"time": datetime.now().timestamp(), "role": "zaiens", "text": text, "qq": zq, "type": "greeting"})
                save_history(self._chat_history)
        else:
            seed = get_hour_seed()
            text = await self._speak_as(group_id, wq, wp, seed, is_greeting=True, use_delay=not force)
            if text:
                self._update_context(wp, text, "william")
                self._chat_history.append({"time": datetime.now().timestamp(), "role": "william", "text": text, "qq": wq, "type": "greeting"})
                save_history(self._chat_history)

    # ─── 插话 ──────────────────────────────────────────────

    async def _maybe_interject(self, event: AstrMessageEvent):
        """有人在群里和双子说话时，另一人概率插话"""
        if not self.config.get("interject_chance", 30):
            return

        # 急停后不插话
        if self._emergency_stop:
            return

        # 睡眠窗口内默认不插话（概率熬夜例外）
        if wants_to_sleep(self.config):
            return

        group_id = self.config.get("group_id", "").strip()
        if not group_id: return
        if str(group_id) != str(event.get_group_id()): return

        text = event.message_str.strip()
        sender_qq = event.get_sender_id()

        # 只对提到扎恩斯或威廉的内容触发
        zq = self.config.get("zaiens_qq", "")
        wq = self.config.get("william_qq", "")
        mentioned = False
        replied_to = ""

        # 检查是否@了扎恩斯或威廉
        for comp in event.get_messages():
            if hasattr(comp, "type") and comp.type == "at":
                if comp.qq == zq:
                    mentioned = True; replied_to = "扎恩斯"
                elif comp.qq == wq:
                    mentioned = True; replied_to = "威廉"

        # 检查内容里是否提到了名字
        if not mentioned:
            if "扎恩斯" in text or "zaiens" in text.lower():
                mentioned = True; replied_to = "扎恩斯"
            elif "威廉" in text or "william" in text.lower():
                mentioned = True; replied_to = "威廉"

        if not mentioned: return

        # 发消息的人如果是双子自己，不触发
        if sender_qq in (zq, wq): return

        chance = self.config.get("interject_chance", 30)
        if random.randint(1, 100) > chance: return

        await self._refresh_bot_map()

        # 被提到的是扎恩斯，威廉插话；反之亦然
        if replied_to == "扎恩斯":
            speaker_qq = wq
            speaker_p = self.config.get("william_persona", "william")
            speaker_role = "william"
        else:
            speaker_qq = zq
            speaker_p = self.config.get("zaiens_persona", "zaiens")
            speaker_role = "zaiens"

        if not self._get_bot_by_qq(speaker_qq): return

        seed = f"看到有人在和{replied_to}说：{text[:30]}"
        reply = await self._speak_as(group_id, speaker_qq, speaker_p, seed,
                                      is_interject=True, replied_to=replied_to)
        if reply:
            self._update_context(speaker_p, reply, speaker_role)
            self._chat_history.append({
                "time": datetime.now().timestamp(), "role": speaker_role,
                "text": reply, "qq": speaker_qq, "type": "interject"
            })
            save_history(self._chat_history)

    # ─── 主循环（定时对话+问候） ───────────────────────────

    async def _timed_loop(self):
        """主循环：同时处理定时对话和问候"""
        last_greet_time = time.time()

        while self._running:
            try:
                now = datetime.now()

                # 定时对话
                if self.config.get("enable_timed_chat", True):
                    await self._do_chat_round()

                # 问候：按实际时间间隔检查，不再依赖计数器
                if self.config.get("greeting_enabled", True):
                    greet_interval = self.config.get("greeting_check_interval", 30) * 60  # 转秒
                    if time.time() - last_greet_time >= greet_interval:
                        base_chance = self.config.get("greeting_chance", 35)
                        bonus = get_time_bonus(self.config)
                        total_chance = min(base_chance + bonus, 80)
                        if random.randint(1, 100) <= total_chance:
                            await self._do_greeting()
                        last_greet_time = time.time()

                interval = self.config.get("chat_interval_minutes", 90)
                await asyncio.sleep(interval * 60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"twinsoul 主循环异常: {e}")
                await asyncio.sleep(60)

    # ═══════════════════════════════════════════════════════
    # Web API
    # ═══════════════════════════════════════════════════════

    async def _api_schedule(self):
        data = _refresh_schedule_status(_load_schedule())
        _save_schedule(data)
        return json_response(data)

    async def _api_schedule_toggle(self, id: int = 0):
        data = _load_schedule()
        nodes = data.get("nodes", [])
        if not (0 <= id < len(nodes)):
            return json_response({"message": "节点不存在"})
        n = nodes[id]
        n["manual"] = True
        n["status"] = "pending" if n["status"] == "done" else "done"
        _save_schedule(data)
        return json_response({"message": f"已切换：{n['title']} → {'已完成' if n['status']=='done' else '待开始'}"})

    async def _api_schedule_regen(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data = {"date": today, "nodes": _gen_schedule(today)}
        _save_schedule(data)
        return json_response({"message": "已重新生成今日日程", "schedule": data})

    async def _api_status(self):
        await self._refresh_bot_map()
        ctx_z = len(self.context_memory.get("zaiens", []))
        ctx_w = len(self.context_memory.get("william", []))
        cfg = self.config
        return json_response({
            "running": self._running,
            "group_id": cfg.get("group_id", ""),
            "zaiens_qq": cfg.get("zaiens_qq", ""),
            "william_qq": cfg.get("william_qq", ""),
            "zaiens_persona": cfg.get("zaiens_persona", "zaiens"),
            "william_persona": cfg.get("william_persona", "william"),
            "timed_chat": cfg.get("enable_timed_chat", True),
            "interval": cfg.get("chat_interval_minutes", 90),
            "william_chance": cfg.get("william_initiate_chance", 55),
            "zaiens_chance": cfg.get("zaiens_initiate_chance", 45),
            "context_rounds": cfg.get("context_rounds", 5),
            "interject_chance": cfg.get("interject_chance", 30),
            "greeting_enabled": cfg.get("greeting_enabled", True),
            "greeting_chance": cfg.get("greeting_chance", 35),
            "greeting_check_interval": cfg.get("greeting_check_interval", 30),
            "morning_boost": cfg.get("morning_boost", 25),
            "noon_boost": cfg.get("noon_boost", 20),
            "evening_boost": cfg.get("evening_boost", 20),
            "night_boost": cfg.get("night_boost", 15),
            "delay_short_sec": cfg.get("delay_short_sec", 20),
            "delay_long_min_sec": cfg.get("delay_long_min_sec", 60),
            "delay_long_max_sec": cfg.get("delay_long_max_sec", 180),
            "delay_long_chance": cfg.get("delay_long_chance", 20),
            "sleep_start_hour": cfg.get("sleep_start_hour", 23),
            "sleep_end_hour": cfg.get("sleep_end_hour", 7),
            "sleep_talk_chance": cfg.get("sleep_talk_chance", 15),
            "sleeping": wants_to_sleep(cfg),
            "found_bots": list(self._bot_map.keys()),
            "history_count": len(self._chat_history),
            "context_zaiens": ctx_z,
            "context_william": ctx_w,
        })

    async def _api_get_config(self):
        return json_response(dict(self.config))

    async def _api_save_config(self):
        payload = await request.json(default={})
        if not payload: return error_response("无效请求")
        for k, v in payload.items():
            if isinstance(k, str) and k and not k.startswith("_"):
                self.config[k] = v
        save_config(self.config)
        return json_response({"saved": True, "config": dict(self.config)})

    async def _api_do_chat(self):
        if not self.config.get("group_id"): return error_response("未设置群号")
        payload = await request.json(default={})
        seed = payload.get("seed", "") if isinstance(payload, dict) else ""
        asyncio.create_task(self._do_chat_round(custom_seed=seed, force=True))
        return json_response({"message": "对话已触发"})

    async def _api_greet(self):
        if not self.config.get("group_id"): return error_response("未设置群号")
        asyncio.create_task(self._do_greeting(force=True))
        return json_response({"message": "问候已触发"})

    async def _api_history(self):
        limit = request.query.get("limit", 200, type=int)
        role = request.query.get("role", "all")
        src = self._chat_history
        start = max(0, len(src) - limit)
        out = []
        for i in range(start, len(src)):
            d = src[i]
            if role != "all" and d.get("role") != role:
                continue
            out.append({"index": i, **d})
        return json_response(out)

    async def _api_clear_history(self):
        self._chat_history.clear()
        save_history(self._chat_history)
        logger.info("twinsoul: 历史已清空")
        return json_response({"cleared": True})

    async def _api_context(self):
        out = {}
        for role, arr in self.context_memory.items():
            out[role] = [{"index": i, **d} for i, d in enumerate(arr)]
        return json_response(out)

    async def _api_clear_context(self):
        self.context_memory = {"zaiens": [], "william": []}
        save_context(self.context_memory)
        logger.info("twinsoul: 上下文已清空")
        return json_response({"cleared": True})

    async def _api_remove_history(self):
        payload = await request.json(default={})
        idx = payload.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(self._chat_history)):
            return error_response("无效索引")
        removed = self._chat_history.pop(idx)
        save_history(self._chat_history)
        logger.info(f"twinsoul: 删除历史 #{idx}: {str(removed.get('text',''))[:30]}")
        return json_response({"removed": True})

    async def _api_remove_context(self):
        payload = await request.json(default={})
        role = payload.get("role", "")
        idx = payload.get("index")
        arr = self.context_memory.get(role)
        if not isinstance(arr, list) or not isinstance(idx, int) or not (0 <= idx < len(arr)):
            return error_response("无效参数")
        removed = arr.pop(idx)
        save_context(self.context_memory)
        logger.info(f"twinsoul: 删除记忆 {role} #{idx}: {str(removed.get('text',''))[:30]}")
        return json_response({"removed": True})

    async def _api_start(self):
        if self._running: return json_response({"message": "已在运行"})
        self._emergency_stop = False
        if not self.config.get("group_id"): return error_response("未设置群号")
        await self._refresh_bot_map()
        zq, wq = self.config.get("zaiens_qq", ""), self.config.get("william_qq", "")
        missing = []
        if not self._get_bot_by_qq(zq): missing.append("zaiens")
        if not self._get_bot_by_qq(wq): missing.append("william")
        if missing: return error_response(f"bot缺失: {', '.join(missing)}")
        self._running = True
        self._task = asyncio.create_task(self._timed_loop())
        return json_response({"message": "已开启"})

    async def _api_stop(self):
        self._emergency_stop = True
        self._running = False
        if self._task: self._task.cancel(); self._task = None
        return json_response({"message": "已急停：当前对话终止，定时循环已停"})

    # ═══════════════════════════════════════════════════════
    # QQ指令
    # ═══════════════════════════════════════════════════════

    @filter_mod.command("ts")
    async def ts(self, event: AstrMessageEvent, action: str = "",
                 key: str = "", value: str = ""):
        cmd = action.strip().lower()

        if cmd == "开启":
            if not self.config.get("group_id"):
                yield event.plain_result("请先设置 group_id")
                return
            if self._running:
                yield event.plain_result("已在运行")
                return
            await self._refresh_bot_map()
            zq, wq = self.config.get("zaiens_qq", ""), self.config.get("william_qq", "")
            missing = []
            if not self._get_bot_by_qq(zq): missing.append(f"扎恩斯({zq})")
            if not self._get_bot_by_qq(wq): missing.append(f"威廉({wq})")
            if missing:
                yield event.plain_result(f"找不到bot: {', '.join(missing)}")
                return
            self._emergency_stop = False
            self._running = True
            self._task = asyncio.create_task(self._timed_loop())
            yield event.plain_result("双子对话已开启（含定时问候+插话）")

        elif cmd == "关闭":
            self._running = False
            if self._task: self._task.cancel(); self._task = None
            yield event.plain_result("已关闭")

        elif cmd in ("停止", "stop", "急停"):
            self._emergency_stop = True
            self._running = False
            if self._task: self._task.cancel(); self._task = None
            yield event.plain_result("⛔ 已急停：当前对话立即终止，定时循环已停（ts 开启 恢复）")

        elif cmd == "对话":
            if not self.config.get("group_id"):
                yield event.plain_result("请先设置 group_id"); return
            self._emergency_stop = False
            seed = " ".join([key, value]).strip() if key else ""
            yield event.plain_result("双子对话中..." if not seed else f"话题：{seed}")
            await self._do_chat_round(custom_seed=seed, force=True)

        elif cmd == "问候":
            if not self.config.get("group_id"):
                yield event.plain_result("请先设置 group_id"); return
            self._emergency_stop = False
            yield event.plain_result("问候中...")
            await self._do_greeting(force=True)

        elif cmd in ("日程", "schedule"):
            data = _refresh_schedule_status(_load_schedule())
            _save_schedule(data)
            marks = {"pending": "⏳", "active": "▶️", "done": "✅"}
            lines = [f"📅 今日日程（{data['date']}）"]
            for n in data.get("nodes", []):
                lines.append(f"{marks.get(n['status'], '⏳')} {n['time']} {n['title']}")
            yield event.plain_result("\n".join(lines))

        elif cmd == "重置":
            self.context_memory = {"zaiens": [], "william": []}
            save_context(self.context_memory)
            yield event.plain_result("上下文记忆已清空")

        elif cmd == "状态":
            await self._refresh_bot_map()
            ctx_z = len(self.context_memory.get("zaiens", []))
            ctx_w = len(self.context_memory.get("william", []))
            h = datetime.now().hour
            yield event.plain_result(
                f"【twinsoul v3】\n"
                f"群: {self.config.get('group_id', '未设置')}\n"
                f"扎恩斯: {self.config.get('zaiens_qq', '')} ({self.config.get('zaiens_persona', 'zaiens')})\n"
                f"威廉: {self.config.get('william_qq', '')} ({self.config.get('william_persona', 'william')})\n"
                f"Bot: {list(self._bot_map.keys())}\n"
                f"定时: {'开' if self.config.get('enable_timed_chat', True) else '关'} "
                f"每{self.config.get('chat_interval_minutes', 90)}分\n"
                f"问候: {'开' if self.config.get('greeting_enabled', True) else '关'} "
                f"概率{self.config.get('greeting_chance', 35)}% "
                f"时段加成+{get_time_bonus(self.config)}\n"
                f"插话概率: {self.config.get('interject_chance', 30)}%\n"
                f"回复延迟: 短{self.config.get('delay_short_sec', 20)}s内/长{self.config.get('delay_long_min_sec', 60)}-{self.config.get('delay_long_max_sec', 180)}s 概率{self.config.get('delay_long_chance', 20)}%\n"
                f"睡眠: {self.config.get('sleep_start_hour', 23)}:{'00'}~{self.config.get('sleep_end_hour', 7)}:00 "
                f"熬夜概率{self.config.get('sleep_talk_chance', 15)}% "
                f"{'(休息中)' if wants_to_sleep(self.config) else '(清醒)'}\n"
                f"运行: {'是' if self._running else '否'}\n"
                f"历史: {len(self._chat_history)}条 | "
                f"记忆: 扎{ctx_z}条 威{ctx_w}条\n"
                f"当前时间: {h}:00左右"
            )

        elif cmd == "设置":
            valid_keys = [
                "group_id", "zaiens_qq", "william_qq",
                "zaiens_persona", "william_persona",
                "enable_timed_chat", "chat_interval_minutes",
                "william_initiate_chance", "zaiens_initiate_chance",
                "context_rounds", "interject_chance",
                "greeting_enabled", "greeting_chance", "greeting_check_interval",
                "enable_timed_chat", "chat_interval_minutes",
                "william_initiate_chance", "zaiens_initiate_chance",
                "context_rounds", "interject_chance",
                "greeting_enabled", "greeting_chance", "greeting_check_interval",
                "morning_boost", "noon_boost", "evening_boost", "night_boost",
                "delay_short_sec", "delay_long_min_sec", "delay_long_max_sec", "delay_long_chance",
                "sleep_start_hour", "sleep_end_hour", "sleep_talk_chance",
            ]
            if not key:
                yield event.plain_result(f"可用项: {', '.join(valid_keys)}")
                return
            if key not in valid_keys:
                yield event.plain_result(f"无效项: {key}"); return
            if key in ("enable_timed_chat", "greeting_enabled"):
                value = value.lower() in ("true", "1", "yes", "开启", "是")
            elif key in ("delay_short_sec", "delay_long_min_sec", "delay_long_max_sec", "delay_long_chance"):
                try: value = float(value)
                except: yield event.plain_result("请输入数字"); return
            elif key in ("chat_interval_minutes", "william_initiate_chance",
                         "zaiens_initiate_chance", "context_rounds",
                         "interject_chance", "greeting_chance",
                         "greeting_check_interval", "morning_boost",
                         "noon_boost", "evening_boost", "night_boost",
                         "sleep_start_hour", "sleep_end_hour", "sleep_talk_chance"):
                try: value = int(value)
                except: yield event.plain_result("请输入数字"); return
            self.config[key] = value
            save_config(self.config)
            yield event.plain_result(f"已设置 {key} = {value}")

        else:
            yield event.plain_result(
                "twinsoul v3 指令:\n"
                "  /ts 开启 / 关闭\n"
                "  /ts 对话 [话题]\n"
                "  /ts 问候（手动触发一次问候）\n"
                "  /ts 重置（清空记忆）\n"
                "  /ts 状态\n"
                "  /ts 设置 <key> <val>\n"
                "WebUI: 管理面板-插件页"
            )

    # ═══════════════════════════════════════════════════════
    # 事件监听：插话（在 _register_message_handler 中注册）
    # ═══════════════════════════════════════════════════════

    async def on_group_message(self, event: AstrMessageEvent):
        """监听群消息，触发插话"""
        if not self._running: return
        try:
            await self._maybe_interject(event)
        except Exception as e:
            logger.error(f"twinsoul 插话处理异常: {e}")

    async def terminate(self):
        self._running = False
        if self._task: self._task.cancel(); self._task = None
        save_context(self.context_memory)
        save_history(self._chat_history)