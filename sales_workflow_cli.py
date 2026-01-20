#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Sales Workflow Agent (CLI MVP)
- run: extract fields -> score -> generate actions/email -> write outputs + track to SQLite
- export-crm: produce a CRM-friendly payload (Salesforce-style mapping)
- history: inspect recent runs from tracking DB

Default extractor is heuristic (offline). To plug in an LLM:
- implement call_llm(prompt: str) -> str JSON
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------
# Logging
# -----------------------------
def setup_logger(level: str) -> logging.Logger:
    logger = logging.getLogger("sales_workflow_agent")
    if logger.handlers:
        return logger
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    h = logging.StreamHandler()
    fmt = logging.Formatter("[%(levelname)s] %(message)s")
    h.setFormatter(fmt)
    logger.addHandler(h)
    return logger


# -----------------------------
# Config
# -----------------------------
def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# -----------------------------
# IO
# -----------------------------
def read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def read_stdin() -> str:
    return sys.stdin.read().strip()


def ensure_dir(p: str) -> None:
    Path(p).mkdir(parents=True, exist_ok=True)


def write_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# -----------------------------
# PII redaction (basic, extendable)
# -----------------------------
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:(?:\+?86)?\s*)?(?:1[3-9]\d{9})\b|(?:\b\d{3}[-\s]?\d{3}[-\s]?\d{4}\b)")
IDCN_RE = re.compile(r"\b\d{17}[\dXx]\b")

def redact_pii(text: str) -> Tuple[str, bool]:
    redacted = text
    hit = False

    def _sub(pattern: re.Pattern, repl: str, s: str) -> Tuple[str, bool]:
        new_s, n = pattern.subn(repl, s)
        return new_s, (n > 0)

    redacted, h = _sub(EMAIL_RE, "[REDACTED_EMAIL]", redacted); hit = hit or h
    redacted, h = _sub(PHONE_RE, "[REDACTED_PHONE]", redacted); hit = hit or h
    redacted, h = _sub(IDCN_RE, "[REDACTED_ID]", redacted); hit = hit or h
    return redacted, hit


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# -----------------------------
# Extraction (heuristic default)
# -----------------------------
def call_llm(prompt: str) -> str:
    """
    Optional:
      - Replace with real LLM call.
      - Must return JSON string.
    """
    return "{}"


def find_first(text: str, patterns: List[str]) -> Optional[str]:
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def looks_like_company_name(s: str) -> bool:
    if not s:
        return False
    candidate = s.strip()
    if len(candidate) < 4 or len(candidate) > 40:
        return False
    for prefix in ["我们想", "想做", "搞个", "有没有", "能不能", "就是", "现在"]:
        if candidate.startswith(prefix):
            return False
    suffixes = [
        "有限公司",
        "股份有限公司",
        "集团",
        "科技",
        "贸易",
        "物流",
        "医疗",
        "信息",
        "网络",
        "软件",
        "咨询",
        "公司",
    ]
    return any(candidate.endswith(suf) for suf in suffixes)


def heuristic_extract(text: str) -> Dict[str, Any]:
    """
    Heuristic extractor (offline):
    - Prefer bullet lines like "- 预算：" and "- 时间线：" when present
    - Extract industry detail from patterns like "（B2B 医疗器械）"
    - Classify 'bot' as Nice-to-have by default
    """
    account = find_first(text, [
        r"客户[:：]\s*([^\n（]+)",
        r"Company[:：]\s*([^\n]+)"
    ])
    if account and not looks_like_company_name(account):
        account = None

    # Business model (B2B/B2C) and industry detail (e.g., 医疗器械)
    business_model = find_first(text, [
        r"\b(B2B|B2C)\b",
        r"（\s*(B2B|B2C)\b"
    ]) or "Unknown"
    business_model_unknown = business_model == "Unknown"
    business_model_inferred = False
    if business_model_unknown:
        leadership_hit = re.search(r"(领导|管理层|老板|总监|management|manager|director)", text, flags=re.IGNORECASE)
        enterprise_hit = re.search(r"(\bCRM\b|销售效率|流程|复盘|看数据|dashboard)", text, flags=re.IGNORECASE)
        if leadership_hit and enterprise_hit:
            business_model = "Likely B2B (inferred)"
            business_model_inferred = True

    industry_detail = find_first(text, [
        r"（\s*(?:B2B|B2C)\s*([^\)）]+)[）\)]",   # e.g., （B2B 医疗器械）
        r"我们是[^\n]*?一家([^\n，。;；]+?)(?:公司|企业|集团|机构|团队)",
        r"行业[:：]\s*([^\n]+)"
    ])

    industry = industry_detail.strip() if industry_detail else "Unknown"

    # Prefer explicit bullet lines under sections like "预算/时间线："
    budget = find_first(text, [
        r"[-•]\s*预算[:：]\s*([^\n]+)",
        r"预算[:：]\s*([^\n]+)",
        r"budget[:：]\s*([^\n]+)"
    ])

    timeline = find_first(text, [
        r"[-•]\s*时间线[:：]\s*([^\n]+)",
        r"时间线[:：]\s*([^\n]+)",
        r"timeline[:：]\s*([^\n]+)",
        r"(2\s*周内|1-2\s*个月|两周内|本月|下月|Q[1-4])"
    ])
    if not timeline:
        urgency = find_first(text, [
            r"(越快越好|尽快|ASAP|as soon as possible)"
        ])
        if urgency:
            timeline = "ASAP（越快越好）"

    # Simple keyword buckets
    pain_kw = [
        "手动",
        "低效",
        "遗漏",
        "数据不一致",
        "分散",
        "节奏很乱",
        "未跟进",
        "不太爱填",
        "很乱",
        "manual",
        "slow",
        "漏跟进",
        "麻烦",
    ]
    must_kw = [
        "自动化",
        "workflow",
        "tracking",
        "数据追踪",
        "CRM",
        "Salesforce",
        "发票",
        "invoice",
        "dashboard",
        "提醒",
        "超过48小时未跟进",
        "会后总结",
        "复盘",
        "英文",
        "email",
        "邮箱",
        "WhatsApp",
        "微信",
        "导出 Excel/CSV",
        "导出Excel/CSV",
    ]
    nice_kw = ["同步", "集成", "导出", "Slack", "企微", "飞书", "小程序", "bot"]

    pain_points = [kw for kw in pain_kw if re.search(re.escape(kw), text, flags=re.IGNORECASE)]
    must_haves = [kw for kw in must_kw if re.search(re.escape(kw), text, flags=re.IGNORECASE)]
    nice_to_haves = [kw for kw in nice_kw if re.search(re.escape(kw), text, flags=re.IGNORECASE)]
    crm_mentioned = re.search(r"\bCRM\b", " ".join(must_haves), flags=re.IGNORECASE)
    crm_known = re.search(r"\bSalesforce\b", text, flags=re.IGNORECASE)
    crm_negated = re.search(r"(没有|无|未用|不用|不使用).{0,6}CRM", text)
    crm_question_needed = business_model_inferred or (
        crm_mentioned and not crm_known and not crm_negated
    )

    stakeholders = []
    for kw in ["CEO", "CTO", "采购", "财务", "运营", "销售总监", "老板", "procurement", "finance", "ops", "sales"]:
        if re.search(re.escape(kw), text, flags=re.IGNORECASE):
            stakeholders.append(kw)
    if not stakeholders:
        for kw in ["领导", "管理层", "总监", "management", "manager", "director"]:
            if re.search(re.escape(kw), text, flags=re.IGNORECASE):
                stakeholders.append(kw)
    leadership_marker = re.compile(r"(领导|管理层|management)", flags=re.IGNORECASE)
    if any(leadership_marker.search(s) for s in stakeholders):
        stakeholders = [s for s in stakeholders if not leadership_marker.search(s)]
        stakeholders.append("领导/管理层（Reporting stakeholder）")

    open_questions = []
    if not account:
        open_questions.append("Company name?（公司名称？）")
    if not industry or industry == "Unknown":
        open_questions.append("Industry?（行业？）")
    if business_model_unknown:
        open_questions.append("B2B or B2C?（B2B 还是 B2C？）")
    if crm_question_needed:
        open_questions.append("Which CRM are you using?（目前用的 CRM 是什么？）")
    if not budget:
        open_questions.append("Budget range?（预算范围？）")
    if not timeline:
        open_questions.append("Target timeline?（期望上线时间？）")
    if not stakeholders:
        open_questions.append("Decision makers involved?（决策链角色？）")

    use_case = "Sales workflow automation"
    if re.search(r"发票|invoice", text, flags=re.IGNORECASE):
        use_case = "Sales workflow + invoice checks"
    if (
        re.search(r"会后总结", text)
        and re.search(r"跟进提醒", text)
        and re.search(r"(领导|管理层|老板|总监|management|manager|director)", text, flags=re.IGNORECASE)
    ):
        use_case = "Sales workflow + meeting summary + follow-up reminders + reporting"

    return {
        "account_name": account or "Unknown",
        "industry": industry,
        "business_model": business_model,
        "use_case": use_case,
        "pain_points": list(dict.fromkeys(pain_points)) or ["Unclear pain points"],
        "must_haves": list(dict.fromkeys(must_haves)) or ["Unclear requirements"],
        "nice_to_haves": list(dict.fromkeys(nice_to_haves)) or [],
        "budget": budget or "Unknown",
        "timeline": timeline or "Unknown",
        "stakeholders": list(dict.fromkeys(stakeholders)) or ["Unknown"],
        "open_questions": open_questions,
    }


def extract_fields(text: str, schema_json: str, cfg: Dict[str, Any], logger: logging.Logger) -> Dict[str, Any]:
    # Try LLM (stub) then merge with heuristic
    prompt = f"""You are a sales ops assistant. Extract structured lead info in JSON.
Schema:
{schema_json}

Text:
{text}

Return JSON only.
"""
    llm_out = call_llm(prompt)
    llm_data: Dict[str, Any] = {}
    try:
        parsed = json.loads(llm_out) if llm_out else {}
        if isinstance(parsed, dict):
            llm_data = parsed
    except Exception:
        llm_data = {}

    heur = heuristic_extract(text)
    merged = {**heur, **{k: v for k, v in llm_data.items() if v not in [None, "", [], {}]}}

    # Add required metadata fields
    merged.setdefault("source", "Unknown")
    merged.setdefault("pii_redacted", bool(cfg.get("redact_pii", True)))
    merged.setdefault("raw_text_excerpt", "")
    merged.setdefault("text_hash", "")
    return merged


# -----------------------------
# Scoring & Stage
# -----------------------------
def score_and_stage(fields: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    sc = cfg.get("scoring", {})
    fit = int(sc.get("base_fit", 50))
    intent = int(sc.get("base_intent", 50))

    # Fit signals
    if fields.get("industry") and fields["industry"] != "Unknown":
        fit += int(sc.get("fit_industry_known", 10))
    if re.search(r"\bSalesforce\b", " ".join(fields.get("must_haves", [])), flags=re.IGNORECASE):
        fit += int(sc.get("fit_crm_salesforce", 10))
    if any(k in " ".join(fields.get("must_haves", [])) for k in ["自动化", "tracking", "数据追踪", "workflow", "dashboard"]):
        fit += int(sc.get("fit_mentions_automation_tracking", 10))

    # Intent signals
    if fields.get("budget") and fields["budget"] != "Unknown":
        intent += int(sc.get("intent_budget_known", 15))
    if fields.get("timeline") and fields["timeline"] != "Unknown":
        intent += int(sc.get("intent_timeline_known", 10))
    if len(fields.get("open_questions", [])) <= 1:
        intent += int(sc.get("intent_few_open_questions", 10))

    fit = max(0, min(100, fit))
    intent = max(0, min(100, intent))

    stage = "Early (Needs discovery)"
    for rule in cfg.get("stage_rules", []):
        if fit >= int(rule.get("min_fit", 0)) and intent >= int(rule.get("min_intent", 0)):
            stage = rule.get("name", stage)
            break

    # Simple rating for CRM
    rating = "Cold"
    if stage.startswith("SQL"):
        rating = "Hot"
    elif stage.startswith("MQL"):
        rating = "Warm"

    return {"fit_score": fit, "intent_score": intent, "stage": stage, "rating": rating}


# -----------------------------
# Actions & Email (template-based)
# -----------------------------
def generate_actions(fields: Dict[str, Any], scores: Dict[str, Any]) -> List[str]:
    actions = [
        "Confirm key stakeholders & decision process（确认决策链与对接人）",
        "Schedule a 20-min discovery call to validate requirements（安排需求澄清电话）",
        "Share a short workflow prototype outline + expected data fields（发送流程原型大纲与字段清单）"
    ]
    crm_mentioned = re.search(r"\bCRM\b", " ".join(fields.get("must_haves", [])), flags=re.IGNORECASE)
    if crm_mentioned or fields.get("business_model") == "Likely B2B (inferred)":
        actions.insert(0, "Confirm current CRM and data sources（确认当前 CRM 与数据来源/字段）")
    if re.search(r"发票|invoice", " ".join(fields.get("must_haves", [])), flags=re.IGNORECASE):
        actions.append("Collect 3–5 sample invoices to define validation rules（收集样例发票定义校验规则）")
    if scores["stage"].startswith("SQL"):
        actions.insert(0, "Propose a POC scope & timeline this week（本周给出 POC 范围与时间线）")
    return actions


def generate_followup_email(fields: Dict[str, Any], scores: Dict[str, Any], owner: str, lang: str) -> str:
    # Minimal bilingual option
    bullets = [
        f"行业/Industry: {fields.get('industry')}",
        f"业务类型/Segment: {fields.get('business_model', 'Unknown')}",
        f"痛点/Pain points: {', '.join(fields.get('pain_points', []))}",
        f"关键需求/Must-haves: {', '.join(fields.get('must_haves', []))}",
        f"可选项/Nice-to-haves: {', '.join(fields.get('nice_to_haves', [])) if fields.get('nice_to_haves') else 'None'}",
        f"预算/Budget: {fields.get('budget')}",
        f"时间线/Timeline: {fields.get('timeline')}",
    ]
    actions = generate_actions(fields, scores)
    questions = fields.get("open_questions", [])

    # Build lines first, then use * unpacking
    question_lines_bilingual = [f"- {q}" for q in questions] if questions else ["- None for now / 暂无"]
    question_lines_zh = [f"- {q}" for q in questions] if questions else ["- 暂无"]

    if lang.upper() == "BILINGUAL":
        body = [
            "Subject: Follow-up on your requirements & next steps / 需求跟进与下一步建议",
            "",
            "Hi there / 你好，",
            "",
            "Thanks for sharing your context. I captured the key points below / 感谢分享需求背景，关键信息如下：",
            *[f"- {b}" for b in bullets],
            "",
            "Proposed next steps / 建议下一步：",
            *[f"{i+1}) {a}" for i, a in enumerate(actions[:3])],
            "",
            "Quick questions / 需要确认的问题：",
            *question_lines_bilingual,
            "",
            "If you're available, I can share a short prototype and align on a POC plan this week.",
            "如方便，我可以本周分享一个简版原型并对齐 POC 计划。",
            "",
            f"Best / 谢谢，\n{owner}"
        ]
        return "\n".join(body).strip()

    # Default Chinese
    body = [
        "主题：需求跟进与下一步建议",
        "",
        "你好，",
        "",
        "感谢分享需求背景。我先把关键信息整理如下：",
        *[f"- {b.split(':',1)[0]}：{b.split(':',1)[1].strip()}" for b in bullets],
        "",
        "建议下一步：",
        *[f"{i+1}) {a}" for i, a in enumerate(actions[:3])],
        "",
        "需要进一步确认的问题：",
        *question_lines_zh,
        "",
        "如果你方便，我可以本周分享一个简版 workflow 原型，并对齐 POC 范围与时间线。",
        "",
        f"谢谢，\n{owner}"
    ]
    return "\n".join(body).strip()


# -----------------------------
# Reporting
# -----------------------------
def build_report_md(fields: Dict[str, Any], scores: Dict[str, Any], actions: List[str], email: str) -> str:
    md = []
    md.append("# Lead Summary\n")
    md.append(f"- **Lead ID**: {fields.get('lead_id')}")
    md.append(f"- **Account**: {fields.get('account_name')}")
    md.append(f"- **Industry**: {fields.get('industry')}")
    md.append(f"- **Use case**: {fields.get('use_case')}")
    md.append(f"- **Budget**: {fields.get('budget')}")
    md.append(f"- **Timeline**: {fields.get('timeline')}")
    md.append(f"- **Pain points**: {', '.join(fields.get('pain_points', []))}")
    md.append(f"- **Must-haves**: {', '.join(fields.get('must_haves', []))}")
    md.append(f"- **Stakeholders**: {', '.join(fields.get('stakeholders', []))}")
    md.append(f"- **PII redacted**: {fields.get('pii_redacted')}")
    md.append(f"- **Text hash**: `{fields.get('text_hash')}`\n")

    md.append("## Scores\n")
    md.append(f"- **Fit score**: {scores['fit_score']}")
    md.append(f"- **Intent score**: {scores['intent_score']}")
    md.append(f"- **Stage**: {scores['stage']}")
    md.append(f"- **Rating**: {scores.get('rating','')}\n")

    md.append("## Next actions\n")
    for a in actions:
        md.append(f"- {a}")

    md.append("\n## Follow-up email\n")
    md.append("```")
    md.append(email)
    md.append("```")

    if fields.get("open_questions"):
        md.append("\n## Open questions\n")
        for q in fields["open_questions"]:
            md.append(f"- {q}")

    return "\n".join(md).strip()


# -----------------------------
# Tracking DB
# -----------------------------
def init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
CREATE TABLE IF NOT EXISTS lead_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_ts TEXT NOT NULL,
  lead_id TEXT NOT NULL,
  input_source TEXT,
  account_name TEXT,
  industry TEXT,
  budget TEXT,
  timeline TEXT,
  fit_score INTEGER,
  intent_score INTEGER,
  stage TEXT,
  out_dir TEXT
);
""")
    conn.commit()
    conn.close()


def insert_run(db_path: str, record: Dict[str, Any]) -> None:
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
INSERT INTO lead_runs
(run_ts, lead_id, input_source, account_name, industry, budget, timeline, fit_score, intent_score, stage, out_dir)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (
        record["run_ts"], record["lead_id"], record["input_source"],
        record.get("account_name"), record.get("industry"),
        record.get("budget"), record.get("timeline"),
        record.get("fit_score"), record.get("intent_score"),
        record.get("stage"), record.get("out_dir")
    ))
    conn.commit()
    conn.close()


def fetch_history(db_path: str, limit: int) -> List[Tuple[Any, ...]]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
SELECT run_ts, lead_id, account_name, industry, fit_score, intent_score, stage, out_dir
FROM lead_runs ORDER BY id DESC LIMIT ?
""", (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


# -----------------------------
# CRM export (Salesforce-style mapping)
# -----------------------------
def export_salesforce_payload(fields: Dict[str, Any], scores: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    mapping = cfg.get("crm_export", {}).get("salesforce", {}).get("Lead", {})
    # Build a short description/summary
    summary_lines = [
        f"Use case: {fields.get('use_case')}",
        f"Pain points: {', '.join(fields.get('pain_points', []))}",
        f"Must-haves: {', '.join(fields.get('must_haves', []))}",
        f"Open questions: {', '.join(fields.get('open_questions', []))}" if fields.get("open_questions") else "Open questions: None"
    ]
    summary_text = "\n".join(summary_lines).strip()

    payload: Dict[str, Any] = {}
    for sf_field, src_key in mapping.items():
        if src_key == "summary_text":
            payload[sf_field] = summary_text
        elif src_key == "stage":
            payload[sf_field] = scores.get("stage")
        elif src_key == "rating":
            payload[sf_field] = scores.get("rating")
        else:
            payload[sf_field] = fields.get(src_key, "Unknown")

    # Include external id hint
    payload["External_Id__c"] = fields.get("lead_id")
    return {"object": "Lead", "action": "upsert", "payload": payload}


# -----------------------------
# Commands
# -----------------------------
def cmd_run(args: argparse.Namespace, logger: logging.Logger) -> None:
    cfg = load_config(args.config)
    schema_json = read_text_file(args.schema)

    raw_text = read_stdin() if args.stdin else read_text_file(args.input)
    # Always hash raw text (but don't persist raw full text)
    raw_hash = text_sha256(raw_text)

    processed_text = raw_text
    pii_hit = False
    if cfg.get("redact_pii", True) and not args.no_redact:
        processed_text, pii_hit = redact_pii(raw_text)

    lead_id = args.lead_id or f"LEAD-{uuid.uuid4().hex[:8].upper()}"
    excerpt_len = int(cfg.get("max_excerpt_chars", 500))
    excerpt = processed_text[:excerpt_len] + ("..." if len(processed_text) > excerpt_len else "")

    fields = extract_fields(processed_text, schema_json, cfg, logger)
    fields["lead_id"] = lead_id
    fields["source"] = args.source or fields.get("source", "Unknown")
    fields["pii_redacted"] = bool(cfg.get("redact_pii", True) and not args.no_redact)
    fields["text_hash"] = raw_hash
    fields["raw_text_excerpt"] = excerpt

    scores = score_and_stage(fields, cfg)
    actions = generate_actions(fields, scores)
    owner = args.owner or cfg.get("owner", "You")
    lang = args.lang or cfg.get("language", "ZH")
    email = generate_followup_email(fields, scores, owner=owner, lang=lang)

    ensure_dir(args.out)
    write_json(os.path.join(args.out, "fields.json"), fields)
    write_json(os.path.join(args.out, "scores.json"), scores)
    write_text(os.path.join(args.out, "next_actions.txt"), "\n".join(actions))
    write_text(os.path.join(args.out, "follow_up_email.txt"), email)
    report = build_report_md(fields, scores, actions, email)
    write_text(os.path.join(args.out, "report.md"), report)

    # Track to DB
    if args.db:
        record = {
            "run_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "lead_id": lead_id,
            "input_source": "stdin" if args.stdin else args.input,
            "account_name": fields.get("account_name"),
            "industry": fields.get("industry"),
            "budget": fields.get("budget"),
            "timeline": fields.get("timeline"),
            "fit_score": scores.get("fit_score"),
            "intent_score": scores.get("intent_score"),
            "stage": scores.get("stage"),
            "out_dir": args.out
        }
        insert_run(args.db, record)

    logger.info(f"OK: outputs saved to {args.out}")
    if args.db:
        logger.info(f"OK: tracked in DB {args.db}")
    if pii_hit:
        logger.info("Note: PII-like strings were redacted in outputs.")


def cmd_export_crm(args: argparse.Namespace, logger: logging.Logger) -> None:
    cfg = load_config(args.config)
    fields = json.loads(read_text_file(os.path.join(args.out, "fields.json")))
    scores = json.loads(read_text_file(os.path.join(args.out, "scores.json")))

    fmt = args.format.lower()
    if fmt != "salesforce":
        raise SystemExit(f"Unsupported format: {args.format} (only 'salesforce' in this demo)")

    payload = export_salesforce_payload(fields, scores, cfg)
    out_path = args.output or os.path.join(args.out, "crm_payload.json")
    write_json(out_path, payload)
    logger.info(f"OK: CRM payload written to {out_path}")


def cmd_history(args: argparse.Namespace, logger: logging.Logger) -> None:
    rows = fetch_history(args.db, args.limit)
    if not rows:
        print("(no history)")
        return
    # Simple table
    headers = ["run_ts", "lead_id", "account", "industry", "fit", "intent", "stage", "out_dir"]
    print("\t".join(headers))
    for r in rows:
        print("\t".join(str(x) if x is not None else "" for x in r))


# -----------------------------
# CLI parser
# -----------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sales-workflow-agent", description="Sales Workflow Agent (CLI MVP)")
    p.add_argument("--config", type=str, default="config.json", help="Path to config.json")
    p.add_argument("--schema", type=str, default="schemas/lead_schema.json", help="Path to lead schema JSON")
    p.add_argument("--log-level", type=str, default="INFO", help="Log level (DEBUG/INFO/WARN/ERROR)")

    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run extraction + scoring + action/email generation")
    run.add_argument("--input", type=str, help="Path to input text file")
    run.add_argument("--stdin", action="store_true", help="Read input from stdin")
    run.add_argument("--out", type=str, required=True, help="Output directory")
    run.add_argument("--db", type=str, default="", help="SQLite DB path for tracking (optional)")
    run.add_argument("--owner", type=str, default="", help="Name shown in follow-up email signature")
    run.add_argument("--lang", type=str, default="", help="ZH or BILINGUAL")
    run.add_argument("--source", type=str, default="", help="Lead source (e.g., inbound, event, referral)")
    run.add_argument("--lead-id", type=str, default="", help="Optional lead id (otherwise auto-generated)")
    run.add_argument("--no-redact", action="store_true", help="Disable PII redaction (NOT recommended)")
    run.set_defaults(func=cmd_run)

    exp = sub.add_parser("export-crm", help="Export CRM payload from an output directory")
    exp.add_argument("--out", type=str, required=True, help="Output directory containing fields.json and scores.json")
    exp.add_argument("--format", type=str, default="salesforce", help="Export format: salesforce")
    exp.add_argument("--output", type=str, default="", help="Output file path (default: <out>/crm_payload.json)")
    exp.set_defaults(func=cmd_export_crm)

    hist = sub.add_parser("history", help="Show recent runs from tracking DB")
    hist.add_argument("--db", type=str, required=True, help="SQLite DB path")
    hist.add_argument("--limit", type=int, default=10, help="Number of rows to show")
    hist.set_defaults(func=cmd_history)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logger = setup_logger(args.log_level)

    # Validation for run
    if args.command == "run":
        if args.stdin and args.input:
            parser.error("Use only one: --input or --stdin.")
        if (not args.stdin) and (not args.input):
            parser.error("Either --input or --stdin is required.")

    args.func(args, logger)


if __name__ == "__main__":
    main()
