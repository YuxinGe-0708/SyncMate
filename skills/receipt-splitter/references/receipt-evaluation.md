# Receipt evaluation and training guidance

Fine-tuning is not required for the first version. Qwen Vision already performs general receipt OCR and item extraction. Start with prompt constraints, deterministic validation, and a small evaluation set.

Use synthetic or fully redacted receipts with expected JSON labels. Cover:

- one payer and equal split;
- “某人请客，其他人 AA”;
- multiple payers;
- fixed and ratio splits;
- item-level participants;
- discounts, service fees, rounding, and non-CNY currency;
- unreadable totals and unknown names;
- duplicate or conflicting item totals.

Keep a holdout set that is never used to tune prompts. Track total accuracy, payer/participant accuracy, amount reconciliation, and transfer conservation (`sum credits == sum debts`). Fine-tune only if a sufficiently large, licensed, representative dataset shows repeated recognition errors after prompt and validation improvements.
