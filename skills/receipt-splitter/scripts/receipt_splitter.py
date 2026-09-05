#!/usr/bin/env python3
"""Qwen receipt extraction + deterministic bill validation/settlement helper.

The helper is intentionally database-agnostic. A backend supplies the selected
group's members and persists the returned pending bill in its own transaction.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import httpx


MAX_FILES = 8
MAX_SINGLE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 24 * 1024 * 1024
DEFAULT_BASE_URL = "https://llm-mwkswiy08jkjxquo.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3-vl-plus"


class ReceiptSplitError(Exception):
    def __init__(self, code: str, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []


def allocate(total: int, weights: list[tuple[int, int]]) -> dict[int, int]:
    if total < 0 or not weights or any(weight <= 0 for _, weight in weights):
        raise ReceiptSplitError("invalid_split", "分摊金额或权重无效")
    weight_sum = sum(weight for _, weight in weights)
    result: dict[int, int] = {}
    remainders: list[tuple[int, int]] = []
    assigned = 0
    for user_id, weight in weights:
        numerator = total * weight
        amount, remainder = divmod(numerator, weight_sum)
        result[user_id] = amount
        assigned += amount
        remainders.append((remainder, user_id))
    for _, user_id in sorted(remainders, key=lambda item: (-item[0], item[1]))[: total - assigned]:
        result[user_id] += 1
    return result


def minimum_cash_flow(payers: list[dict], participants: list[dict]) -> list[dict]:
    balances: dict[int, int] = {}
    for row in payers:
        balances[int(row["user_id"])] = balances.get(int(row["user_id"]), 0) + int(row["amount_cents"])
    for row in participants:
        balances[int(row["user_id"])] = balances.get(int(row["user_id"]), 0) - int(row["amount_cents"])
    creditors = [[user_id, amount] for user_id, amount in balances.items() if amount > 0]
    debtors = [[user_id, -amount] for user_id, amount in balances.items() if amount < 0]
    creditors.sort(key=lambda item: (-item[1], item[0]))
    debtors.sort(key=lambda item: (-item[1], item[0]))
    result = []
    ci = di = 0
    while ci < len(creditors) and di < len(debtors):
        amount = min(creditors[ci][1], debtors[di][1])
        result.append({"from_user_id": debtors[di][0], "to_user_id": creditors[ci][0], "amount_cents": amount})
        creditors[ci][1] -= amount
        debtors[di][1] -= amount
        if creditors[ci][1] == 0:
            ci += 1
        if debtors[di][1] == 0:
            di += 1
    return result


def _member_map(members: list[dict]) -> dict[str, int]:
    names: dict[str, int] = {}
    for member in members:
        for field in ("nickname", "group_nickname", "username"):
            value = str(member.get(field) or "").strip().lower()
            if value:
                if value in names and names[value] != int(member["id"]):
                    raise ReceiptSplitError("ambiguous_member", f"群内存在重复称呼“{value}”，请使用唯一昵称")
                names[value] = int(member["id"])
    return names


def _resolve(name: Any, names: dict[str, int]) -> int:
    key = str(name or "").strip().lower()
    if key not in names:
        raise ReceiptSplitError("unknown_member", f"无法将“{name}”匹配到群组成员")
    return names[key]


def _safe_resolve_many(values: list[Any], names: dict[str, int]) -> list[int]:
    resolved = []
    for value in values:
        try:
            resolved.append(_resolve(value, names))
        except ReceiptSplitError as error:
            if error.code != "unknown_member":
                raise
    return list(dict.fromkeys(resolved))


def _meal_period_from_time(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        hour = int(text[:2])
    except (TypeError, ValueError):
        return None
    if hour < 6:
        return "夜宵"
    if hour < 10:
        return "早餐"
    if hour < 14:
        return "午餐"
    if hour < 18:
        return "下午茶"
    return "晚餐"


def validate_meal_scope(raw: dict, instruction: str) -> None:
    """Reject meal-scoped rules when receipt timing cannot support them.

    A model must not decide that an evening receipt is lunch merely because the
    instruction mentions lunch.  The prompt asks for receipt_time/meal_period;
    this guard turns missing or contradictory timing into a clarification.
    """
    text = str(instruction or "").lower()
    targets: list[str] = []
    if any(term in text for term in ("早餐", "早饭", "早餐")):
        targets.append("早餐")
    if any(term in text for term in ("午餐", "午饭", "中饭")):
        targets.append("午餐")
    if any(term in text for term in ("晚餐", "晚饭")):
        targets.append("晚餐")
    if not targets:
        return
    receipts = [row for row in (raw.get("receipts") or []) if isinstance(row, dict)]
    if not receipts:
        raise ReceiptSplitError("clarification_required", "规则指定了餐次，但票据未提供逐张时间")
    expected = set(targets)
    unknown: list[str] = []
    conflicting: list[str] = []
    matching = 0
    for index, receipt in enumerate(receipts, start=1):
        receipt_index = int(receipt.get("receipt_index") or index)
        period = str(receipt.get("meal_period") or "").strip()
        if not period:
            period = _meal_period_from_time(receipt.get("receipt_time") or receipt.get("time")) or ""
        if not period or period == "未知":
            unknown.append(str(receipt_index))
            continue
        if period in expected:
            matching += 1
        elif any(marker in text for marker in ("只有", "仅", "对应", "这顿", "该餐")):
            conflicting.append(f"第{receipt_index}张({period})")
    if unknown:
        raise ReceiptSplitError("clarification_required", "无法从小票时间确认餐次范围，请明确指定按第几张小票分摊", [f"缺少时间：第{item}张" for item in unknown])
    if matching == 0 or conflicting:
        details = conflicting or [f"目标餐次：{'、'.join(targets)}"]
        raise ReceiptSplitError("clarification_required", "规则中的餐次与小票时间不一致，请明确指定小票范围", details)


def normalize_analysis(raw: dict, members: list[dict], actual_payer_id: int | None = None) -> dict:
    if not isinstance(raw, dict):
        raise ReceiptSplitError("invalid_json", "模型返回的数据不是 JSON 对象")
    names = _member_map(members)
    ambiguities = raw.get("ambiguities") or []
    if actual_payer_id is not None:
        ambiguities = [
            item for item in ambiguities
            if not any(keyword in str(item).lower() for keyword in ("付款人", "谁付款", "垫付人", "谁垫付", "payer", "paid"))
        ]
    if ambiguities:
        raise ReceiptSplitError("clarification_required", "票据或分账规则存在歧义，请补充说明", [str(item) for item in ambiguities])
    subtotal = int(raw.get("subtotal_cents") or 0)
    total = int(raw.get("total_cents") or 0)
    if total <= 0:
        discount = int(raw.get("discount_percent") or 100)
        total = subtotal * discount // 100 + int(raw.get("service_fee_cents") or 0) - int(raw.get("coupon_cents") or 0) + int(raw.get("rounding_cents") or 0)
    if total <= 0:
        raise ReceiptSplitError("missing_total", "无法确认账单总额")
    if subtotal <= 0:
        subtotal = total

    member_ids = {int(member["id"]) for member in members}
    if actual_payer_id is not None:
        if int(actual_payer_id) not in member_ids:
            raise ReceiptSplitError("unknown_member", "实际付款人不属于目标群组")
        payer_ids = [int(actual_payer_id)]
    else:
        payer_names = raw.get("payer_names") or []
        if not payer_names:
            raise ReceiptSplitError("missing_payer", "无法确认实际付款人")
        payer_ids = list(dict.fromkeys(_resolve(name, names) for name in payer_names))
    participant_rows = raw.get("participants") if isinstance(raw.get("participants"), list) else []
    participant_ids = _safe_resolve_many([row.get("name") for row in participant_rows if isinstance(row, dict) and row.get("name")], names)
    if not participant_ids:
        participant_ids = _safe_resolve_many(raw.get("participant_names") or [], names)
    if not participant_ids:
        participant_ids = [int(member["id"]) for member in members]
    participant_ids = list(dict.fromkeys(participant_ids))

    split_method = str(raw.get("split_method") or "equal")
    if split_method not in {"equal", "ratio", "fixed", "item"}:
        split_method = "equal"
    source_items = [item for item in (raw.get("items") or []) if isinstance(item, dict) and item.get("name") and int(item.get("amount_cents") or 0) > 0]
    if split_method == "fixed":
        amounts = {_resolve(row.get("name"), names): int(row.get("amount_cents") or 0) for row in participant_rows if isinstance(row, dict) and row.get("name")}
        if sum(amounts.get(user_id, 0) for user_id in participant_ids) != total:
            raise ReceiptSplitError("inconsistent_split", "固定分摊金额之和不等于账单总额")
        participants = [{"user_id": user_id, "amount_cents": amounts[user_id]} for user_id in participant_ids]
    elif split_method == "ratio":
        weights = {_resolve(row.get("name"), names): max(1, int(row.get("value") or 0)) for row in participant_rows if isinstance(row, dict) and row.get("name")}
        participants = [{"user_id": user_id, "amount_cents": amount} for user_id, amount in allocate(total, [(user_id, weights.get(user_id, 1)) for user_id in participant_ids]).items()]
    elif split_method == "item":
        if not raw.get("items"):
            raise ReceiptSplitError("missing_items", "无法识别商品明细")
        source_items = [item for item in raw.get("items") if isinstance(item, dict) and item.get("name") and int(item.get("amount_cents") or 0) > 0]
        item_sum = sum(int(item.get("amount_cents") or 0) for item in source_items)
        if item_sum <= 0:
            raise ReceiptSplitError("inconsistent_items", "商品明细金额无效")
        receipt_totals = {int(row.get("receipt_index") or 1): int(row.get("total_cents") or 0) for row in (raw.get("receipts") or []) if isinstance(row, dict) and int(row.get("total_cents") or 0) > 0}
        if receipt_totals:
            by_receipt: dict[int, list[tuple[int, int]]] = {}
            for index, item in enumerate(source_items):
                by_receipt.setdefault(int(item.get("receipt_index") or 1), []).append((index, int(item.get("amount_cents") or 0)))
            adjusted_amounts: dict[int, int] = {}
            for receipt_index, indexes in by_receipt.items():
                target = receipt_totals.get(receipt_index)
                if target:
                    adjusted_amounts.update(allocate(target, indexes))
            source_items = [{**item, "amount_cents": adjusted_amounts.get(index, int(item.get("amount_cents") or 0))} for index, item in enumerate(source_items)]
            item_sum = sum(int(item["amount_cents"]) for item in source_items)
            subtotal = max(subtotal, sum(receipt_totals.values()))
        item_totals: dict[int, int] = {}
        items = []
        for item in source_items:
            if not isinstance(item, dict) or not item.get("name") or int(item.get("amount_cents") or 0) <= 0:
                continue
            ids = _safe_resolve_many(item.get("participant_names") or [], names)
            if not ids:
                ids = participant_ids
            ids = list(dict.fromkeys(ids))
            allocation = allocate(int(item["amount_cents"]), [(user_id, 1) for user_id in ids])
            for user_id, amount in allocation.items():
                item_totals[user_id] = item_totals.get(user_id, 0) + amount
            items.append({"name": str(item["name"]), "amount_cents": int(item["amount_cents"]), "participant_ids": ids, "receipt_index": int(item.get("receipt_index") or 1), "claim_mode": item.get("claim_mode", "exclusive"), "category": item.get("category", raw.get("category", "其他"))})
        adjustment = total - sum(item_totals.values())
        if adjustment:
            adjusted = allocate(abs(adjustment), [(user_id, max(1, amount)) for user_id, amount in item_totals.items()])
            for user_id, amount in adjusted.items():
                item_totals[user_id] = item_totals.get(user_id, 0) + (amount if adjustment > 0 else -amount)
        if any(amount < 0 for amount in item_totals.values()):
            raise ReceiptSplitError("invalid_discount", "优惠金额过大，导致商品分摊金额为负")
        participants = [{"user_id": user_id, "amount_cents": item_totals.get(user_id, 0)} for user_id in participant_ids]
    else:
        participants = [{"user_id": user_id, "amount_cents": amount} for user_id, amount in allocate(total, [(user_id, 1) for user_id in participant_ids]).items()]
    if split_method != "item":
        items = []
        for item in source_items:
            if not isinstance(item, dict) or not item.get("name") or int(item.get("amount_cents") or 0) <= 0:
                continue
            ids = _safe_resolve_many(item.get("participant_names") or [], names) or participant_ids
            items.append({"name": str(item["name"]), "amount_cents": int(item["amount_cents"]), "participant_ids": list(dict.fromkeys(ids)), "receipt_index": int(item.get("receipt_index") or 1), "claim_mode": item.get("claim_mode", "exclusive"), "category": item.get("category", raw.get("category", "其他"))})

    raw_payers = raw.get("payers") if isinstance(raw.get("payers"), list) else []
    if actual_payer_id is not None:
        payer_amounts = {int(actual_payer_id): total}
    elif raw_payers:
        payer_amounts = {_resolve(row.get("name"), names): int(row.get("amount_cents") or 0) for row in raw_payers if isinstance(row, dict) and row.get("name")}
        if set(payer_amounts) != set(payer_ids) or sum(payer_amounts.values()) != total:
            raise ReceiptSplitError("inconsistent_payers", "多人垫付金额之和不等于账单总额")
    else:
        payer_amounts = allocate(total, [(user_id, 1) for user_id in payer_ids])
    payers = [{"user_id": user_id, "amount_cents": amount} for user_id, amount in payer_amounts.items()]
    bill = {
        "title": str(raw.get("title") or "AI 账单"),
        "category": str(raw.get("category") or "其他"),
        "bill_date": str(raw.get("bill_date") or date.today().isoformat()),
        "currency": str(raw.get("currency") or "CNY").upper(),
        "total_cents": total,
        "subtotal_cents": subtotal,
        "payers": payers,
        "participants": participants,
        "items": items,
        "split_method": split_method,
        "ai_generated": True,
        "requires_confirmation": True,
        "receipts": raw.get("receipts") or [],
    }
    transfers = minimum_cash_flow(payers, participants)
    if sum(row["amount_cents"] for row in payers) != total or sum(row["amount_cents"] for row in participants) != total:
        raise ReceiptSplitError("inconsistent_total", "付款和分摊金额未守恒")
    return {"version": "1.0", "status": "ok", "bill": bill, "transfers": transfers, "explanation": str(raw.get("explanation") or ""), "raw_analysis": raw}


def _extract_json(value: Any) -> dict:
    if isinstance(value, list):
        value = "\n".join(str(item.get("text", "")) for item in value if isinstance(item, dict))
    text = str(value or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ReceiptSplitError("invalid_json", "模型返回的内容不是有效 JSON")
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as error:
            raise ReceiptSplitError("invalid_json", "模型返回的 JSON 无法解析") from error
    if not isinstance(parsed, dict):
        raise ReceiptSplitError("invalid_json", "模型返回的数据结构无效")
    return parsed


def _image_part(image: dict) -> dict:
    content_type = str(image.get("content_type") or "image/jpeg")
    encoded = str(image.get("content_base64") or "")
    if not content_type.lower().startswith("image/"):
        raise ReceiptSplitError("invalid_image", f"{image.get('filename', '文件')} 不是图片")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise ReceiptSplitError("invalid_image", f"{image.get('filename', '图片')} 内容无效") from error
    if not raw or len(raw) > MAX_SINGLE_BYTES:
        raise ReceiptSplitError("image_too_large", "单张图片为空或超过 8MB")
    return {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{encoded}"}}


def analyze_receipts(images: list[dict], instruction: str, members: list[dict], api_key: str | None = None, current_user_id: int | None = None, actual_payer_id: int | None = None, base_url: str | None = None, model: str | None = None) -> dict:
    if not instruction.strip():
        raise ReceiptSplitError("missing_instruction", "请输入分账要求")
    if not images:
        raise ReceiptSplitError("missing_images", "请至少上传一张小票图片")
    if len(images) > MAX_FILES:
        raise ReceiptSplitError("too_many_images", f"最多上传 {MAX_FILES} 张图片")
    total_bytes = 0
    parts = []
    for image in images:
        part = _image_part(image)
        total_bytes += len(base64.b64decode(image["content_base64"]))
        if total_bytes > MAX_TOTAL_BYTES:
            raise ReceiptSplitError("images_too_large", "图片总大小不能超过 24MB")
        parts.append(part)
    token = (api_key or os.environ.get("DASHSCOPE_API_KEY", "")).strip()
    if not token:
        raise ReceiptSplitError("missing_api_key", "未配置 DASHSCOPE_API_KEY")
    current = next((member for member in members if int(member["id"]) == current_user_id), None)
    actual_payer = next((member for member in members if int(member["id"]) == actual_payer_id), None)
    member_text = "、".join(f"{member['nickname']} (id={member['id']})" for member in members)
    current_text = current["nickname"] if current else "未指定"
    schema = {"title": "账单标题", "category": "餐饮", "bill_date": date.today().isoformat(), "total_cents": 0, "subtotal_cents": 0, "service_fee_cents": 0, "coupon_cents": 0, "rounding_cents": 0, "currency": "CNY", "payer_names": [], "payers": [{"name": "付款人昵称", "amount_cents": 0}], "split_method": "item", "participant_names": [], "items": [{"receipt_index": 1, "name": "商品", "amount_cents": 0, "participant_names": ["实际承担费用的成员昵称"], "category": "餐饮"}], "receipts": [{"receipt_index": 1, "merchant": "商户", "receipt_time": "HH:MM:SS 或 null", "meal_period": "早餐/午餐/晚餐/未知", "total_cents": 0}], "ambiguities": [], "explanation": ""}
    payer_text = actual_payer["nickname"] if actual_payer else "未指定"
    prompt = f"""你是 SyncMate 的票据识别和分账规则解释器。只输出一个严格 JSON 对象，不要 Markdown。图片按出现顺序编号为 1..N。
群组成员只能使用这些准确昵称：{member_text}。当前上传者是：{current_text}，规则中的“我”指当前上传者。
界面已明确选择实际付款人为：{payer_text}。这不是待推断信息；payer_names 必须填写该昵称，payers 必须填写该成员承担全部实付金额，不要把付款人列为歧义。
用户规则：{instruction}
逐张识别商户、日期、交易时间、商品和实付总额，所有金额转为人民币分的整数。尽量从小票底部读取 receipt_time（HH:MM:SS）；若图片确实没有时间，填写 null，绝不能猜测。根据真实交易时间填写 meal_period（早餐/午餐/晚餐/未知），绝不能仅凭用户规则猜测餐次。total_cents 是所有图片实付金额之和；subtotal_cents 是用于分摊的 items 金额之和。items 必须覆盖所有消费，receipt_index 必须正确。
每个 item 的 participant_names 表示最终承担该项费用的人。“A请客某项”表示 A 独自承担该项，participant_names 只能填 A；“全员AA”表示所有群成员平均承担；绝不能把“请客”解释为被请的人承担。若规则说“午饭我请，其他消费全员AA”，请把午饭对应的商品全部归给当前上传者，把其他商品归给全体成员。
payers 表示实际垫付款。界面所选实际付款人优先于小票中的支付方式或模型推测；只有界面也未指定付款人时才需要将付款人列为歧义。付款合计必须等于 total_cents。
固定使用 split_method="item"。JSON 模板：{json.dumps(schema, ensure_ascii=False)}"""
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt}, *parts]}]
    try:
        api_base = (base_url or os.environ.get("QWEN_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        model_name = model or os.environ.get("SYNCMATE_QWEN_MODEL") or DEFAULT_MODEL
        response = httpx.post(f"{api_base}/chat/completions", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json={"model": model_name, "messages": messages, "temperature": 0.0, "response_format": {"type": "json_object"}}, timeout=120)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        raw = _extract_json(content)
        validate_meal_scope(raw, instruction)
        result = normalize_analysis(raw, members, actual_payer_id=actual_payer_id)
        if actual_payer_id is not None:
            result["bill"]["actual_payer_id"] = int(actual_payer_id)
        return result
    except httpx.HTTPStatusError as error:
        if error.response.status_code in {401, 403}:
            raise ReceiptSplitError("qwen_auth_error", "Qwen API Key 无效或无权访问当前工作空间，请检查密钥是否已过期、被撤销，并重启后端进程") from error
        raise ReceiptSplitError("qwen_http_error", f"Qwen API 请求失败（HTTP {error.response.status_code}）") from error
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as error:
        raise ReceiptSplitError("qwen_unavailable", "Qwen API 暂时不可用") from error


def _main() -> int:
    parser = argparse.ArgumentParser(description="Analyze receipt images and print validated settlement JSON")
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--members", required=True, help="JSON array: [{\"id\":1,\"nickname\":\"小王\"}]")
    parser.add_argument("images", nargs="*", help="receipt image paths")
    args = parser.parse_args()
    try:
        members = json.loads(args.members)
        images = [{"filename": path, "content_type": "image/jpeg", "content_base64": base64.b64encode(Path(path).read_bytes()).decode()} for path in args.images]
        print(json.dumps(analyze_receipts(images, args.instruction, members), ensure_ascii=False, indent=2))
        return 0
    except (OSError, json.JSONDecodeError, ReceiptSplitError) as error:
        payload = {"version": "1.0", "status": "error", "error": {"code": getattr(error, "code", "input_error"), "message": str(error), "details": getattr(error, "details", [])}}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(_main())
