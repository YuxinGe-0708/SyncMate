# Backend integration

## Request shape

Pass the helper:

```python
result = analyze_receipts(
    images=[{"filename": "receipt.jpg", "content_type": "image/jpeg", "content_base64": "..."}],
    instruction="小王请客午饭，其他开销所有人 AA",
    members=[{"id": 1, "nickname": "小王"}, {"id": 2, "nickname": "小李"}],
    api_key=os.environ["DASHSCOPE_API_KEY"],
)
```

`members` must be the members of the selected `group_id`; the helper does not query the database. The API caller should authenticate the user and authorize membership before calling it.

## Persistence flow

1. Reject `status != "ok"` with HTTP 422 and show `errors` to the user.
2. Validate that payer and participant IDs are members of the selected group.
3. Insert a bill with `status="pending"`, `ai_generated=1`, the `AI分析` tag, the original instruction, and the returned raw analysis.
4. Insert payer and split rows in the same database transaction.
5. Return the transfers to the UI as a preview. Do not create payment transactions until an owner/admin confirms the bill.
6. On confirmation, re-run the server-side total and split validations, then atomically change the bill to `active`.

## Error handling

Do not retry a malformed model response as if it were a valid bill. The helper distinguishes API failures, invalid JSON, unknown members, missing payer, and inconsistent totals. Log a request correlation ID and the model error, but never log the API key or full receipt image payload.
